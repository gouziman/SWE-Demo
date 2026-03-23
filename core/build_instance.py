import docker
import os
import subprocess
import shutil
import openai
import time
import requests  # 确保已安装: pip install requests

# ==========================================
# 1. 密钥配置区域 (在此填写 API KEY)
# ==========================================
GITHUB_TOKEN = "YOUR_GITHUB_TOKEN_HERE"  # <--- 在此填写你的 GitHub Personal Access Token
# LLM API 已经在 TaskBackTranslator 类中通过环境变量或参数传入，无需在此重复
# ==========================================

client = docker.from_env()

# --- 新增：GitHub API 数据发现模块 ---
class GitHubDiscovery:
    def __init__(self, token=None):
        self.token = token
        self.headers = {"Authorization": f"token {token}"} if token else {}
        self.base_url = "https://api.github.com"

    def get_high_quality_repos(self, lang="python", min_stars=5000, limit=5):
        """搜索高质量（高星）项目"""
        print(f"--- [GitHub API] 正在搜索高质量 {lang} 项目... ---")
        url = f"{self.base_url}/search/repositories?q=language:{lang}+stars:>{min_stars}&sort=stars&order=desc&per_page={limit}"
        try:
            resp = requests.get(url, headers=self.headers).json()
            return [repo['clone_url'] for repo in resp.get('items', [])]
        except Exception as e:
            print(f"GitHub API Error: {e}")
            return []

# --- 核心构建逻辑 (保持原有接口) ---
class TaskBackTranslator:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or "https://api.openai.com/v1"
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate_issue_description(self, commit_msg, diff_content):
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
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM Generation Failed: {str(e)}"

class R2EBuilder:
    def __init__(self, repo_url, local_path):
        self.repo_url = repo_url
        self.repo_path = local_path
        self.translator = TaskBackTranslator()
        self._prepare_repo()

    def _prepare_repo(self):
        # 如果目录已存在且不为空，先清理掉，确保拉取的是最新目标
        if os.path.exists(self.repo_path):
            shutil.rmtree(self.repo_path)
        
        print(f"--- 正在克隆仓库: {self.repo_url} ---")
        subprocess.run(["git", "clone", "--depth", "200", self.repo_url, self.repo_path], check=True)

    def find_eligible_commits(self, limit=1):
        print(f"--- 正在扫描 {self.repo_url} 符合条件的 Commit ---")
        # 增加筛选力度：必须包含 fix/bug/patch，且限制为 python 文件
        cmd = ["git", "-C", self.repo_path, "log", "--grep=fix", "--grep=bug", "--grep=solve", "--pretty=format:%H", "-n", "50"]
        try:
            all_commits = subprocess.check_output(cmd).decode().split('\n')
        except:
            return []
        
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

        self._build_image(sha, "post-fix")
        self._build_image(parent_sha, "pre-fix", inject_tests_from=sha, test_paths=test_files)

    def _build_image(self, commit_sha, mode, inject_tests_from=None, test_paths=None):
        instance_id = f"r2e-{commit_sha[:8]}-{mode}"
        build_dir = f"temp_{instance_id}"
        
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)

        subprocess.run(["git", "clone", self.repo_path, build_dir], check=True)
        subprocess.run(["git", "-C", build_dir, "checkout", "-f", commit_sha], check=True)

        if inject_tests_from and test_paths:
            print(f"  [Inject] 正在注入测试文件到 {mode} 环境...")
            for tp in test_paths:
                subprocess.run(["git", "-C", build_dir, "checkout", inject_tests_from, "--", tp], check=False)

        problem_statement = "No description generated."
        if mode == "pre-fix":
            print(f"  [LLM] 正在反向生成任务书...")
            diff_content = subprocess.check_output(["git", "-C", self.repo_path, "show", inject_tests_from]).decode('utf-8', 'ignore')
            commit_msg = subprocess.check_output(["git", "-C", self.repo_path, "log", "-1", "--pretty=%B", inject_tests_from]).decode('utf-8', 'ignore')
            problem_statement = self.translator.generate_issue_description(commit_msg, diff_content)

        with open(os.path.join(build_dir, "INSTRUCTION.md"), "w", encoding="utf-8") as f:
            f.write(f"# R2E Task: {instance_id}\n\n## 任务描述\n{problem_statement}\n\n---\n**目标**：修复问题。")

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
        shutil.rmtree(build_dir, ignore_errors=True) # 构建完立即清理占用空间

# --- 验证逻辑 (保持原有接口) ---
class R2EValidator:
    def __init__(self):
        self.client = docker.from_env()

    def validate_instance(self, pre_fix_tag, post_fix_tag, test_cmd="pytest"):
        print(f"--- [Validation] 正在验证: {pre_fix_tag} ---")
        pre_status = self._run_test(pre_fix_tag, test_cmd)
        post_status = self._run_test(post_fix_tag, test_cmd)
        
        if pre_status != 0 and post_status == 0:
            print("🎉 验证成功！符合 F2P (Fail to Pass) 规范。")
            return True
        else:
            print(f"❌ 验证失败 (Pre:{pre_status}, Post:{post_status})")
            return False

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
        except:
            return -1

# --- 主程序 (逻辑升级：全网发现) ---
if __name__ == "__main__":
    # 1. 发现高质量项目
    discovery = GitHubDiscovery(token=GITHUB_TOKEN)
    target_repos = discovery.get_high_quality_repos(lang="python", min_stars=1000, limit=3)
    
    validator = R2EValidator()
    
    for repo_url in target_repos:
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        local_path = f"./source_{repo_name}"
        
        try:
            builder = R2EBuilder(repo_url, local_path)
            # 从每个仓库里找 1 个最典型的 Bug Fix Commit
            eligible_tasks = builder.find_eligible_commits(limit=1)
            
            for task in eligible_tasks:
                builder.build_pair(task)
                
                pre_tag = f"r2e-{task['sha'][:8]}-pre-fix"
                post_tag = f"r2e-{task['sha'][:8]}-post-fix"
                
                if validator.validate_instance(pre_tag, post_tag):
                    print(f"✅ 任务保存: {pre_tag}")
                else:
                    print(f"🗑️ 清理无效镜像: {pre_tag}")
                    try:
                        client.images.remove(pre_tag, force=True)
                        client.images.remove(post_tag, force=True)
                    except: pass
            
            # 清理源码节省空间
            shutil.rmtree(local_path, ignore_errors=True)
            
        except Exception as e:
            print(f"处理仓库 {repo_url} 时出错: {e}")
            continue