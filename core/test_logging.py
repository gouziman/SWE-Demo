#!/usr/bin/env python3
"""
测试日志记录功能
"""
import sys
from container_session import ContainerSession

if __name__ == "__main__":
    # 使用一个简单的Docker镜像进行测试
    # 注意：这个镜像需要存在，或者你可以替换为你本地有的镜像
    test_image = "ubuntu:latest"
    
    print("=== 测试日志记录功能 ===")
    print(f"使用镜像: {test_image}")
    
    session = ContainerSession(test_image)
    
    try:
        # 启动容器
        container_id = session.start()
        print(f"容器启动成功，ID: {container_id}")
        
        # 执行一些测试命令
        print("\n执行测试命令...")
        
        # 测试命令1：查看系统信息
        res1 = session.execute("uname -a")
        print(f"命令1执行结果: Exit Code {res1['exit_code']}")
        print(f"输出: {res1['output'][:100]}...")
        
        # 测试命令2：查看当前目录
        res2 = session.execute("pwd")
        print(f"\n命令2执行结果: Exit Code {res2['exit_code']}")
        print(f"输出: {res2['output']}")
        
        # 测试命令3：创建一个测试文件
        res3 = session.execute("echo 'test' > test.txt && cat test.txt")
        print(f"\n命令3执行结果: Exit Code {res3['exit_code']}")
        print(f"输出: {res3['output']}")
        
        print("\n=== 测试完成 ===")
        print(f"日志文件已保存到: {session.log_file}")
        
    except Exception as e:
        print(f"测试失败: {e}")
    finally:
        # 关闭容器
        print("\n清理容器...")
        session.close()
        print("容器已关闭")
