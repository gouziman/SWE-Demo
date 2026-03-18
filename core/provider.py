import docker

class EnvironmentProvider:
    def __init__(self):
        self.client = docker.from_env()
        self.prefix = "swe-instance-"

    def _normalize_id(self, instance_id):
        """将官方 ID 转换为 Docker 标签合规格式"""
        return instance_id.lower().replace('.', '_').replace('/', '_')

    def get_image_for_task(self, instance_id):
        """
        Agent 调用的核心接口：
        输入 instance_id，返回可用的本地镜像名。
        如果镜像不存在，可以触发自动构建逻辑（可选）。
        """
        target_tag = f"{self.prefix}{self._normalize_id(instance_id)}"
        
        try:
            # 检查本地是否有这个镜像
            image = self.client.images.get(target_tag)
            print(f"--- [Found] 找到匹配环境: {target_tag} ---")
            return target_tag
        except docker.errors.ImageNotFound:
            print(f"--- [Error] 环境未就绪: {target_tag} ---")
            # 这里可以扩展：如果没找到，是否调用之前的 create_task_environment()?
            return None

    def list_available_tasks(self):
        """让 Agent 知道目前它能处理哪些任务"""
        images = self.client.images.list()
        task_images = [img.tags[0] for img in images if img.tags and img.tags[0].startswith(self.prefix)]
        return task_images

# --- Agent 模拟调用示例 ---
if __name__ == "__main__":
    provider = EnvironmentProvider()
    
    # 假设 Agent 拿到了一个任务
    my_task = input("请输入任务 ID: ")
    image_name = provider.get_image_for_task(my_task)
    
    if image_name:
        print(f"Agent 启动容器，使用镜像: {image_name}")
    else:
        print("环境不存在，请先运行构建流水线。")