import docker
import os
import subprocess
import shutil

client = docker.from_env()

class R2EBuilder:
    def __init__(self, repo_url, local_path):
        self.repo_url = repo_url
        self.repo_path = local_path
        self._prepare_repo()

    def _prepare_repo(self):
        """确保本地有源码库用于扫描"""
        if not os.path.exists(self.repo_path):
            print(f"--- 正在克隆仓库: {self.repo_url} ---")
            subprocess.run(["git", "clone", self.repo_url, self.repo_path], check=True)

    def find_eligible_commits(self, limit=3):
        """匹配 R2E 逻辑：包含 fix 关键字且同时修改了源码和测试"""
        print(f"--- 正在扫描符合条件的 Commit ---")
        cmd = [
            "git", "-C", self.repo_path, "log", 
            "--grep=fix", "--grep=bug", "--grep=solve", 
            "--pretty=format:%H", "-n", "100"
        ]
        all_commits = subprocess.check_output(cmd).decode().split('\n')
        
        eligible = []
        for sha in all_commits:
            if not sha: continue
            # 检查变更文件
            files = subprocess.check_output(["git", "-C", self.repo_path, "show", "--name-only", sha]).decode().split('\n')
            has_src = any(f.endswith('.py') and 'test' not in f.lower() for f in files if f)
            # 提取具体的测试文件路径，后续注入要用
            test_files = [f for f in files if 'test' in f.lower() and f.endswith('.py')]
            
            if has_src and test_files:
                eligible.append({"sha": sha, "test_files": test_files})
                if len(eligible) >= limit: break
        return eligible

    def build_pair(self, commit_info):
        """构建 Pre-fix (故障+新测试) 和 Post-fix (修复) 镜像"""
        sha = commit_info['sha']
        test_files = commit_info['test_files']
        
        # 获取父节点 (故障点)
        parent_sha = subprocess.check_output(["git", "-C", self.repo_path, "rev-parse", f"{sha}^"]).decode().strip()

        # 1. 构建 Post-fix (修复态)
        self._build_image(sha, "post-fix")

        # 2. 构建 Pre-fix (故障态 + 注入新测试)
        self._build_image(parent_sha, "pre-fix", inject_tests_from=sha, test_paths=test_files)

    def _build_image(self, commit_sha, mode, inject_tests_from=None, test_paths=None):
        instance_id = f"r2e-{commit_sha[:8]}-{mode}"
        build_dir = f"temp_{instance_id}"
        
        if os.path.exists(build_dir): shutil.rmtree(build_dir)
        
        # 准备代码环境
        subprocess.run(["git", "clone", self.repo_path, build_dir], check=True)
        subprocess.run(["git", "-C", build_dir, "checkout", "-f", commit_sha], check=True)

        # R2E 关键：如果是 pre-fix，把修复后的测试文件拉过来覆盖掉旧的（或新增）
        if inject_tests_from and test_paths:
            print(f"  [Inject] 正在注入测试文件到 {mode} 环境...")
            for tp in test_paths:
                subprocess.run(["git", "-C", build_dir, "checkout", inject_tests_from, "--", tp], check=False)

        # 写入任务说明 (简单逻辑，后续可接 LLM Back-translation)
        with open(os.path.join(build_dir, "INSTRUCTION.md"), "w") as f:
            f.write(f"# R2E Task: {instance_id}\nMode: {mode}\nTarget Commit: {commit_sha}")

        # 复用你原来的 Dockerfile 逻辑
        dockerfile_content = f"""
FROM swe-base-test
COPY . /testbed
RUN echo 'alias hint="cat /testbed/INSTRUCTION.md"' >> ~/.bashrc
# 注意：如果是随机仓库，setup_env.sh 需要能处理各种依赖安装
RUN /usr/local/bin/setup_env.sh || echo "Environment setup skipped"
"""
        with open(os.path.join(build_dir, "Dockerfile.task"), "w") as f:
            f.write(dockerfile_content)

        print(f"--- 正在构建 {mode} 镜像: {instance_id} ---")
        client.images.build(path=build_dir, dockerfile="Dockerfile.task", tag=instance_id, rm=True)
        print(f"✅ {instance_id} 构建成功")

if __name__ == "__main__":
    # 填入你想挖掘的本地路径或 URL
    REPO_URL = "https://github.com/astropy/astropy.git"
    LOCAL_REPO = "./astropy_source"
    
    builder = R2EBuilder(REPO_URL, LOCAL_REPO)
    tasks = builder.find_eligible_commits(limit=2) # 先挖2个试试
    
    for task in tasks:
        builder.build_pair(task)