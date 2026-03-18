import docker
import os
import json
from datasets import load_dataset

client = docker.from_env()

def create_task_environment(instance):
    """
    完全对齐官方逻辑的构建函数：
    instance: 数据集中的一个条目（Dict）
    """
    # 提取官方字段
    instance_id = instance['instance_id']
    repo_url = f"https://github.com/{instance['repo']}.git"
    commit_sha = instance['base_commit']
    problem_statement = instance['problem_statement'] # 任务书内容

    work_dir = f"temp_{instance_id}"
    
    # 1. 动态爬取实例代码
    if not os.path.exists(work_dir):
        print(f"--- [Step 1] 正在爬取仓库: {instance['repo']} ---")
        os.system(f"git clone {repo_url} {work_dir}")
    
    # 切换到对应的故障发生前的 Commit
    os.system(f"cd {work_dir} && git checkout -f {commit_sha}")

    # 2. [关键更新] 任务书注入：自动生成任务说明
    print(f"--- [Step 2] 正在注入任务书 (Instruction) ---")
    instruction_path = os.path.join(work_dir, "INSTRUCTION.md")
    with open(instruction_path, "w", encoding="utf-8") as f:
        f.write(f"# Task Instruction for {instance_id}\n\n")
        f.write("## Problem Statement\n")
        f.write(problem_statement)
        f.write("\n\n## Goal\n修复上述问题，并确保所有测试通过。")

    # 3. 准备定制化的 Dockerfile
    dockerfile_content = f"""
FROM swe-base-test
COPY . /testbed
# 确保任务书在最显眼的地方
RUN echo 'alias hint="cat /testbed/INSTRUCTION.md"' >> ~/.bashrc
RUN /usr/local/bin/setup_env.sh
"""
    with open(os.path.join(work_dir, "Dockerfile.task"), "w") as f:
        f.write(dockerfile_content)

    # 4. 自动化构建
    print(f"--- [Step 3] 正在构建镜像: {instance_id} ---")
    image, logs = client.images.build(
        path=work_dir,
        dockerfile="Dockerfile.task",
        tag=f"swe-instance-{instance_id.lower().replace('.', '_')}",
        rm=True
    )
    print(f"✅ 任务 {instance_id} 环境构建成功！")
    return image

# --- 批量处理逻辑 ---
if __name__ == "__main__":
    # 1. 加载官方数据集 (以 SWE-bench Verified 为例，它是精简过的 500 个任务)
    print("正在连接 HuggingFace 加载数据集...")
    dataset = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

    # 2. 模拟 R2E-Gym 的采样逻辑：比如我们先取前 3 个任务做实验
    for i in range(3):
        task_instance = dataset[i]
        try:
            create_task_environment(task_instance)
        except Exception as e:
            print(f"❌ 任务 {task_instance['instance_id']} 构建失败: {e}")