import docker
import os
import subprocess
import shutil
import requests
import json
import re
from datetime import datetime
from llm_client import TaskBackTranslator # 确保复用你现有的 LLM 模块

# ==========================================
# 1. 生产级配置区域
# ==========================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN_HERE")
DATA_DIR = "data"
OUTPUT_FILE = os.path.join(DATA_DIR, "instances.jsonl")
REGISTRY_FILE = os.path.join(DATA_DIR, "registry.json")

class GitHubDiscovery:
    def __init__(self, token=None):
        self.headers = {"Authorization": f"token {token}"} if token else {}
        self.base_url = "https://api.github.com"

    def get_high_quality_repos(self, lang="python", min_stars=5000, limit=3):
        print(f"--- [GitHub API] 正在搜索高质量 {lang} 项目... ---")
        url = f"{self.base_url}/search/repositories?q=language:{lang}+stars:>{min_stars}&sort=stars&order=desc&per_page={limit}"
        try:
            resp = requests.get(url, headers=self.headers).json()
            return [repo['clone_url'] for repo in resp.get('items', [])]
        except Exception as e:
            print(f"API Error: {e}")
            return []

    def get_issue_comments(self, repo_full_name, commit_msg):
        """精准爬取 Issue 讨论作为 hints_text"""
        match = re.search(r'(?:Fixes|Resolves|Closes)?\s*#(\d+)', commit_msg, re.IGNORECASE)
        if not match:
            return ""
        
        issue_num = match.group(1)
        print(f"--- [GitHub API] 探测到关联 Issue #{issue_num}，正在抓取 Hints ---")
        url = f"{self.base_url}/repos/{repo_full_name}/issues/{issue_num}/comments"
        try:
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200:
                comments = resp.json()
                return "\n\n".join([f"Comment by {c['user']['login']}:\n{c['body']}" for c in comments])
            return ""
        except:
            return ""

class R2EBuilder:
    def __init__(self, repo_url, local_path, github_api):
        self.repo_url = repo_url
        self.repo_path = local_path
        self.github_api = github_api
        self.translator = TaskBackTranslator()
        self.repo_full_name = "/".join(self.repo_url.split("/")[-2:]).replace(".git", "")
        self.client = docker.from_env()
        self._prepare_repo()

    def _prepare_repo(self):
        if os.path.exists(self.repo_path):
            shutil.rmtree(self.repo_path)
        subprocess.run(["git", "clone", "--depth", "200", self.repo_url, self.repo_path], check=True)

    def find_eligible_commits(self, limit=1):
        cmd = ["git", "-C", self.repo_path, "log", "--grep=fix", "--grep=bug", "--pretty=format:%H", "-n", "50"]
        all_commits = subprocess.check_output(cmd).decode().split('\n')
        
        eligible = []
        for sha in all_commits:
            if not sha: continue
            files = subprocess.check_output(["git", "-C", self.repo_path, "show", "--name-only", "--format=", sha]).decode().strip().split('\n')
            test_files = [f for f in files if 'test' in f.lower() and f.endswith('.py')]
            src_files = [f for f in files if f.endswith('.py') and f not in test_files]
            
            if src_files and test_files:
                eligible.append({"sha": sha, "src_files": src_files, "test_files": test_files})
                if len(eligible) >= limit: break
        return eligible

    def build_pair(self, commit_info):
        sha = commit_info['sha']
        test_files = commit_info['test_files']
        src_files = commit_info['src_files']
        
        parent_sha = subprocess.check_output(["git", "-C", self.repo_path, "rev-parse", f"{sha}^"]).decode().strip()
        created_at = subprocess.check_output(["git", "-C", self.repo_path, "show", "-s", "--format=%cI", sha]).decode().strip()
        commit_msg = subprocess.check_output(["git", "-C", self.repo_path, "log", "-1", "--pretty=%B", sha]).decode('utf-8', 'ignore')

        # 1. 严格分离 Patch
        gold_patch = subprocess.check_output(["git", "-C", self.repo_path, "diff", parent_sha, sha, "--"] + src_files).decode('utf-8', 'ignore')
        test_patch = subprocess.check_output(["git", "-C", self.repo_path, "diff", parent_sha, sha, "--"] + test_files).decode('utf-8', 'ignore')

        # 2. 获取 Hints
        hints_text = self.github_api.get_issue_comments(self.repo_full_name, commit_msg)

        # 3. 探测版本号 (Heuristic)
        try:
            setup_content = subprocess.check_output(["git", "-C", self.repo_path, "show", f"{sha}:setup.py"], stderr=subprocess.DEVNULL).decode()
            version_match = re.search(r'version=[\'"]([^\'"]+)[\'"]', setup_content)
            version = version_match.group(1) if version_match else "1.0"
        except:
            version = "1.0"

        # 4. 构建 Docker 环境
        self._build_image(sha, "post-fix")
        problem_statement = self._build_image(parent_sha, "pre-fix", inject_tests_from=sha, test_paths=test_files, commit_msg=commit_msg)

        instance_id = f"{self.repo_full_name.replace('/', '__')}-{sha[:8]}"
        
        return {
            "instance_id": instance_id,
            "repo": self.repo_full_name,
            "base_commit": parent_sha,
            "problem_statement": problem_statement,
            "hints_text": hints_text, 
            "created_at": created_at,
            "patch": gold_patch,
            "test_patch": test_patch,
            "version": version,
            "environment_setup_commit": parent_sha,
        }, test_files

    def _build_image(self, commit_sha, mode, inject_tests_from=None, test_paths=None, commit_msg=""):
        instance_id = f"r2e-{commit_sha[:8]}-{mode}"
        build_dir = f"temp_{instance_id}"
        
        shutil.rmtree(build_dir, ignore_errors=True)
        subprocess.run(["git", "clone", self.repo_path, build_dir], check=True)
        subprocess.run(["git", "-C", build_dir, "checkout", "-f", commit_sha], check=True)

        if inject_tests_from and test_paths:
            for tp in test_paths:
                subprocess.run(["git", "-C", build_dir, "checkout", inject_tests_from, "--", tp], check=False)

        problem_statement = "No description generated."
        if mode == "pre-fix":
            diff_content = subprocess.check_output(["git", "-C", self.repo_path, "show", inject_tests_from]).decode('utf-8', 'ignore')
            problem_statement = self.translator.generate_issue_description(commit_msg, diff_content)

        with open(os.path.join(build_dir, "INSTRUCTION.md"), "w", encoding="utf-8") as f:
            f.write(f"## 任务描述\n{problem_statement}")

        # 引入 uv 加速构建，适合在云服务器环境中进行快速隔离验证
        dockerfile_content = """FROM python:3.9-slim
RUN pip install uv pytest
COPY . /testbed
WORKDIR /testbed
RUN uv pip install --system -e . || echo 'install skipped'
"""
        with open(os.path.join(build_dir, "Dockerfile.task"), "w") as f:
            f.write(dockerfile_content)

        self.client.images.build(path=build_dir, dockerfile="Dockerfile.task", tag=instance_id, rm=True)
        shutil.rmtree(build_dir, ignore_errors=True)
        return problem_statement

class R2EValidator:
    def __init__(self):
        self.client = docker.from_env()

    def _parse_pytest_output(self, output):
        """精准提取 pytest 的 node IDs"""
        passed, failed = set(), set()
        for line in output.split('\n'):
            match = re.search(r'^(.*?\.py::.*?)\s+(PASSED|FAILED)', line)
            if match:
                node_id, status = match.groups()
                if status == 'PASSED':
                    passed.add(node_id)
                else:
                    failed.add(node_id)
        return passed, failed

    def validate_and_extract(self, pre_tag, post_tag, test_files):
        print(f"--- [Validation] 正在执行严格的 F2P & P2P 验证 ---")
        test_cmd = f"pytest -v {' '.join(test_files)}"
        
        pre_code, pre_out = self._run_test(pre_tag, test_cmd)
        post_code, post_out = self._run_test(post_tag, test_cmd)
        
        pre_pass, pre_fail = self._parse_pytest_output(pre_out)
        post_pass, post_fail = self._parse_pytest_output(post_out)

        # 严格集合运算：
        # FAIL_TO_PASS: 之前失败，现在通过
        fail_to_pass = list(pre_fail.intersection(post_pass))
        # PASS_TO_PASS: 之前通过，现在依然通过
        pass_to_pass = list(pre_pass.intersection(post_pass))

        is_valid = len(fail_to_pass) > 0  # 必须至少修复了一个用例
        return is_valid, fail_to_pass, pass_to_pass

    def _run_test(self, image_tag, test_cmd):
        try:
            container = self.client.containers.run(
                image_tag,
                command=f"bash -c '{test_cmd}'",
                detach=True, working_dir="/testbed"
            )
            result = container.wait(timeout=300)
            output = container.logs().decode('utf-8', 'ignore')
            container.remove()
            return result['StatusCode'], output
        except Exception as e:
            return -1, str(e)

def update_registry(instance_id, image_tag):
    """更新 Docker 环境注册表"""
    registry = {}
    if os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, 'r') as f:
            registry = json.load(f)
    registry[instance_id] = image_tag
    with open(REGISTRY_FILE, 'w') as f:
        json.dump(registry, f, indent=4)

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    github_api = GitHubDiscovery(token=GITHUB_TOKEN)
    target_repos = github_api.get_high_quality_repos(limit=2)
    validator = R2EValidator()
    client = docker.from_env()

    for repo_url in target_repos:
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        local_path = f"./source_{repo_name}"
        
        try:
            builder = R2EBuilder(repo_url, local_path, github_api)
            eligible_tasks = builder.find_eligible_commits(limit=1)
            
            for task in eligible_tasks:
                instance_data, test_files = builder.build_pair(task)
                
                pre_tag = f"r2e-{task['sha'][:8]}-pre-fix"
                post_tag = f"r2e-{task['sha'][:8]}-post-fix"
                
                success, f2p, p2p = validator.validate_and_extract(pre_tag, post_tag, test_files)
                
                if success:
                    instance_data["FAIL_TO_PASS"] = json.dumps(f2p)
                    instance_data["PASS_TO_PASS"] = json.dumps(p2p)
                    
                    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(instance_data, ensure_ascii=False) + "\n")
                    
                    # 写入注册表，绑定实例 ID 与修复前的测试环境
                    update_registry(instance_data["instance_id"], pre_tag)
                    
                    print(f"✅ 生产级任务已生成: {instance_data['instance_id']}")
                    # 清理无用的 post-fix 镜像释放服务器空间
                    client.images.remove(post_tag, force=True)
                else:
                    print(f"🗑️ 验证未通过 (未检测到有效修复)，清理现场: {pre_tag}")
                    client.images.remove(pre_tag, force=True)
                    client.images.remove(post_tag, force=True)
            
            shutil.rmtree(local_path, ignore_errors=True)
        except Exception as e:
            print(f"Error processing {repo_url}: {e}")
            continue