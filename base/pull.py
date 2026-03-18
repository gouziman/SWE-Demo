import docker
import os

client = docker.from_env()

def build_instance_image(repo_url, commit_sha, image_tag):
    """
    输入：仓库地址、具体的 Commit、你给镜像起的名字
    输出：构建成功的镜像对象
    """
    # 1. 在宿主机临时克隆仓库 (或者利用 Docker 的上下文)
    # 注意：为了对齐 R2E-Gym，建议先在宿主机 git clone 
    os.system(f"git clone {repo_url} temp_repo")
    os.system(f"cd temp_repo && git checkout {commit_sha}")

    # 2. 调用 Docker SDK 构建
    print(f"正在构建镜像: {image_tag} ...")
    image, build_logs = client.images.build(
        path="./temp_repo",
        dockerfile="../base_envs/Dockerfile.template", # 指向你刚才写的模板
        tag=image_tag,
        rm=True
    )
    
    for line in build_logs:
        if 'stream' in line:
            print(line['stream'].strip())
            
    return image

# 测试一下
# build_instance_image("https://github.com/django/django.git", "[某个哈希值]", "swe-django-test")