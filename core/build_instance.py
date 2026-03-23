import docker
import os
import subprocess
import shutil
import openai  # 确保已安装: pip install openai

client = docker.from_env()

# --- 新增：LLM 回译模块 ---
class TaskBackTranslator:
    def __init__(self, api_key=None, base_url=None):
        # 优先从环境变量获取，也可以手动传入
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or "https://api.openai.com/v1"
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate_issue_description(self, commit_msg, diff_content):
        """根据代码差异反向生成像人写的 Issue 描述"""
        if not self.api_key:
            return "Error: API Key not set. Could not generate description."

        prompt = f"""
你是一名资深的开源软件测试工程师。我将给你一个修复 Bug 的代码补丁（Diff）和当时的提交信息（Commit Message）。
请你根据这些信息，反向推导并写出一个详细的 GitHub Issue 描述。

要求：
1. 站在用户的视角：描述用户在使用软件时遇到了什么异常现象或错误。
2. 严禁直接提到补丁里的修复代码或具体的函数修改。
3. 必须包含：【问题背景】、【复现步骤】、【预期行为】、【实际行为】。
4. 语言：中文。

---
Commit Message: {commit_msg}
---
Code Diff:
{diff_content[:2000]} 
---
"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o", # 也可以使用 gpt-4o-mini 节省成本
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM Generation Failed: {str(e)}"

# --- 核心构建逻辑 ---
class R2EBuilder:
    def __init__(self, repo_url, local_path):
        self.repo_url = repo_url
        self.repo_path = local_path
        self.translator = TaskBackTranslator() # 初始化翻译器
        self._prepare_repo()

    def _prepare_repo(self):
        if not os.path.exists(self.repo_path):
            print(f"--- 正在克隆仓库: {self.repo_url} ---")
            subprocess.run(["git", "clone", self.repo_url, self.repo_path], check=True)

    def find_eligible_commits(self, limit=3):
        print(f"--- 正在扫描符合条件的 Commit ---")
        cmd = ["git", "-C", self.repo_path, "log", "--grep=fix", "--grep=bug", "--grep=solve", "--pretty=format:%H", "-n", "100"]
        all_commits = subprocess.check_output(cmd).decode().split('\n')
        
        eligible = []
        for sha in all_commits:
            if not sha: continue
            files = subprocess.check_output(["git", "-C", self.repo_path, "show", "--name-only", sha]).decode().split('\n')
            has_src = any(f.endswith('.py') and 'test' not in f.lower() for f in files if f)
            test_files = [f for f in files if 'test' in f.lower() and f.endswith('.py')]
            
            if has_src and test_files:
                eligible.append({"sha": sha, "test_files": test_files})
                if len(eligible) >= limit: break
        return eligible

    def build_pair(self, commit_info):
        sha = commit_info['sha']
        test_files = commit_info['test_files']
        parent_sha = subprocess.check_output(["git", "-C", self.repo_path, "rev-parse", f"{sha}^"]).decode().strip()

        # 1. 构建 Post-fix (修复态)
        self._build_image(sha, "post-fix")
        # 2. 构建 Pre-fix (故障态 + 注入新测试 + LLM 任务书)
        self._build_image(parent_sha, "pre-fix", inject_tests_from=sha, test_paths=test_files)

    def _build_image(self, commit_sha, mode, inject_tests_from=None, test_paths=None):
        instance_id = f"r2e-{commit_sha[:8]}-{mode}"
        build_dir = f"temp_{instance_id}"
        
        # --- 改进的删除逻辑 ---
        if os.path.exists(build_dir):
            for i in range(3): # 尝试 3 次
                try:
                    shutil.rmtree(build_dir)
                    break
                except Exception as e:
                    print(f"等待文件释放... {e}")
                    time.sleep(1) # 等一秒再试

        if os.path.exists(build_dir): shutil.rmtree(build_dir)
        subprocess.run(["git", "clone", self.repo_path, build_dir], check=True)
        subprocess.run(["git", "-C", build_dir, "checkout", "-f", commit_sha], check=True)

        # 注入逻辑
        if inject_tests_from and test_paths:
            print(f"  [Inject] 正在注入测试文件到 {mode} 环境...")
            for tp in test_paths:
                subprocess.run(["git", "-C", build_dir, "checkout", inject_tests_from, "--", tp], check=False)

        # --- LLM Back-translation 核心逻辑 ---
        problem_statement = "No description generated."
        if mode == "pre-fix":
            print(f"  [LLM] 正在反向生成任务书...")
            diff_content = subprocess.check_output(["git", "-C", self.repo_path, "show", inject_tests_from]).decode('utf-8', 'ignore')
            commit_msg = subprocess.check_output(["git", "-C", self.repo_path, "log", "-1", "--pretty=%B", inject_tests_from]).decode('utf-8', 'ignore')
            problem_statement = self.translator.generate_issue_description(commit_msg, diff_content)

        with open(os.path.join(build_dir, "INSTRUCTION.md"), "w", encoding="utf-8") as f:
            f.write(f"# R2E Task: {instance_id}\n\n")
            f.write("## 任务描述\n")
            f.write(problem_statement)
            f.write("\n\n---\n**目标**：修复上述问题并确保所有测试通过。可以使用 `hint` 命令查看此文档。")

        # Docker 构建
        dockerfile_content = f"""
FROM swe-base-test
COPY . /testbed
RUN echo 'alias hint="cat /testbed/INSTRUCTION.md"' >> ~/.bashrc
RUN /usr/local/bin/setup_env.sh || echo "Environment setup skipped"
"""
        with open(os.path.join(build_dir, "Dockerfile.task"), "w") as f:
            f.write(dockerfile_content)

        print(f"--- 正在构建 {mode} 镜像: {instance_id} ---")
        client.images.build(path=build_dir, dockerfile="Dockerfile.task", tag=instance_id, rm=True)
        print(f"✅ {instance_id} 构建成功")

# --- 验证逻辑 ---
class R2EValidator:
    def __init__(self):
        self.client = docker.from_env()

    def validate_instance(self, pre_fix_tag, post_fix_tag, test_cmd="pytest"):
        print(f"--- [Validation] 正在验证 F2P 逻辑: {pre_fix_tag} ---")
        pre_status = self._run_test(pre_fix_tag, test_cmd)
        if pre_status == 0:
            print("❌ 预检查失败：Pre-fix 环境居然通过了测试。")
            return False
        
        post_status = self._run_test(post_fix_tag, test_cmd)
        if post_status != 0:
            print("❌ 预检查失败：Post-fix 环境未能通过测试。")
            return False
        
        print("🎉 验证成功！该任务符合 F2P 规范。")
        return True

    def _run_test(self, image_tag, test_cmd):
        try:
            container = self.client.containers.run(
                image_tag,
                command=f"bash -c 'source /opt/conda/bin/activate base && {test_cmd}'",
                detach=True,
                working_dir="/testbed"
            )
            result = container.wait(timeout=300)
            container.remove()
            return result['StatusCode']
        except Exception as e:
            print(f"Container error: {e}")
            return -1

# --- 主程序 ---
if __name__ == "__main__":
    REPO_URL = "https://github.com/astropy/astropy.git"
    LOCAL_REPO = "./astropy_source"
    
    builder = R2EBuilder(REPO_URL, LOCAL_REPO)
    validator = R2EValidator()
    
    eligible_tasks = builder.find_eligible_commits(limit=2)# 限制为 2 个任务,每个任务包含一个 pre-fix 和一个 post-fix 镜像，可以修改为其他数量
    
    for task in eligible_tasks:
        builder.build_pair(task)
        
        pre_tag = f"r2e-{task['sha'][:8]}-pre-fix"
        post_tag = f"r2e-{task['sha'][:8]}-post-fix"
        
        if validator.validate_instance(pre_tag, post_tag):
            print(f"🚀 任务存储成功: {pre_tag}")
            # 这里可以添加保存到数据库或 JSON 的代码
        else:
            print(f"🗑️ 正在清理无效镜像...")
            try:
                client.images.remove(pre_tag, force=True)
                client.images.remove(post_tag, force=True)
            except: pass