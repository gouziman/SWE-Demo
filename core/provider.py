import docker
import json
import os

class EnvironmentProvider:
    def __init__(self, registry_path="data/registry.json"):
        self.client = docker.from_env()
        self.registry_path = registry_path
        self._registry_cache = {}
        self._load_registry()

    def _load_registry(self):
        """加载环境映射注册表"""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, 'r') as f:
                    self._registry_cache = json.load(f)
                print(f"--- [Registry] 成功加载 {len(self._registry_cache)} 个任务映射 ---")
            except Exception as e:
                print(f"--- [Error] 解析注册表失败: {e} ---")
        else:
            print(f"--- [Warning] 注册表 {self.registry_path} 不存在，Agent 将无法定位环境 ---")

    def get_image_for_task(self, instance_id):
        """
        Agent 调用的核心接口：
        O(1) 复杂度通过 instance_id 定位具体的 Docker Image Tag
        """
        if instance_id not in self._registry_cache:
            print(f"--- [Error] 任务 {instance_id} 在注册表中未注册 ---")
            return None

        target_tag = self._registry_cache[instance_id]
        
        try:
            # 二次校验本地镜像库，确保镜像未被意外删除
            self.client.images.get(target_tag)
            print(f"--- [Found] 验证成功，映射镜像: {target_tag} ---")
            return target_tag
        except docker.errors.ImageNotFound:
            print(f"--- [Fatal] 注册表存在记录，但本地环境丢失: {target_tag} ---")
            return None

    def list_available_tasks(self):
        """暴露当前系统内所有准备就绪的任务 ID"""
        return list(self._registry_cache.keys())

# --- Agent 模拟交互演示 ---
if __name__ == "__main__":
    provider = EnvironmentProvider()
    available = provider.list_available_tasks()
    
    if not available:
        print("当前没有任何可用的测试环境，请先运行 build_instance.py")
    else:
        print(f"当前可用任务: {available[:3]} ...")
        # 模拟 Agent 请求
        my_task = available[0]
        image_name = provider.get_image_for_task(my_task)
        print(f"\n[Agent] 已获取任务 {my_task} 的底层镜像: {image_name}")