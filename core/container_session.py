import docker
import time
import os
import json
from datetime import datetime

class ContainerSession:
    def __init__(self, image_name, timeout=600, log_dir="agent_logs"):
        self.client = docker.from_env()
        self.image_name = image_name
        self.timeout = timeout
        self.container = None
        self.log_dir = log_dir
        self.log_file = None
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.logs = []
        self._setup_logging()

    def _setup_logging(self):
        """设置日志目录和文件"""
        # 创建日志目录
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        # 生成结构化的日志文件名
        image_name_clean = self.image_name.replace('/', '_').replace(':', '_')
        self.log_file = os.path.join(self.log_dir, f"agent_{image_name_clean}_{self.session_id}.json")
        
    def _log_event(self, event_type, message, data=None):
        """记录事件到日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "message": message,
            "data": data
        }
        self.logs.append(log_entry)
        
    def _save_logs(self):
        """保存日志到文件"""
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(self.logs, f, ensure_ascii=False, indent=2)
        print(f"--- [Log] 日志已保存到: {self.log_file} ---")

    def start(self):
        """启动一个长连接的后台容器"""
        print(f"--- [Session] 正在启动实例: {self.image_name} ---")
        
        # 记录启动事件
        self._log_event("session_start", f"启动容器: {self.image_name}")
        
        self.container = self.client.containers.run(
            self.image_name,
            command="/bin/bash",
            detach=True,
            tty=True,
            stdin_open=True,
            working_dir="/testbed",
            # 限制资源，防止 Agent 搞挂服务器
            mem_limit="4g",
            cpu_period=100000,
            cpu_quota=100000 # 限制为 1 核
        )
        
        # 记录启动成功
        self._log_event("session_started", f"容器启动成功: {self.container.id}")
        # 保存日志
        self._save_logs()
        
        return self.container.id

    def execute(self, command):
        """执行命令并返回结果"""
        if not self.container:
            error_msg = "Error: Session not started."
            self._log_event("error", error_msg)
            self._save_logs()
            return error_msg
        
        print(f"--- [Exec] 运行指令: {command} ---")
        # 记录命令执行开始
        self._log_event("command_start", f"执行命令: {command}")
        
        # 使用 exec_run 进入已经启动的容器
        exit_code, output = self.container.exec_run(
            cmd=["/bin/bash", "-c", command],
            workdir="/testbed"
        )
        
        result = output.decode('utf-8')
        execution_result = {
            "exit_code": exit_code,
            "output": result
        }
        
        # 记录命令执行结果
        self._log_event("command_completed", f"命令执行完成", execution_result)
        # 保存日志
        self._save_logs()
        
        return execution_result

    def close(self):
        """强制清理现场"""
        if self.container:
            print(f"--- [Cleanup] 正在销毁容器: {self.container.id[:10]} ---")
            # 记录容器关闭开始
            self._log_event("session_close", f"关闭容器: {self.container.id[:10]}")
            
            self.container.stop()
            self.container.remove()
            self.container = None
            
            # 记录容器关闭完成
            self._log_event("session_closed", "容器已关闭")
            # 保存最终日志
            self._save_logs()



'''
# --- Agent 调用流程演示 ---
if __name__ == "__main__":
    # 1. 假设 Agent 找到了镜像
    image_to_use = "swe-instance-flask-test-1" 
    
    session = ContainerSession(image_to_use)
    try:
        session.start()
        
        # 2. Agent 第一步：看任务书
        res = session.execute("cat INSTRUCTION.md")
        print(f"任务书内容:\n{res['output']}")
        
        # 3. Agent 第二步：跑一下初始测试，确认 Bug 存在
        # 假设我们知道测试脚本的名字
        test_res = session.execute("pytest tests/test_basic.py")
        print(f"测试结果 (Exit Code {test_res['exit_code']}):\n{test_res['output']}")
        
    finally:
        # 4. 无论成功失败，必须关掉容器，否则服务器内存会炸
        session.close()
'''