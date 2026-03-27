import openai
import os

class TaskBackTranslator:
    def __init__(self, api_key=None, base_url=None, model=None):
        """
        初始化 LLM 客户端
        :param api_key: 优先使用传入的 Key，其次读取环境变量
        :param base_url: 可由环境变量覆盖
        :param model: 
        """
        # 安全读取环境变量，避免硬编码敏感信息
        self.api_key = api_key or os.getenv("ZHIPU_API_KEY")
        self.base_url = base_url or os.getenv("https://open.bigmodel.cn/api/paas/v4")
        self.model = model or os.getenv("GLM-4.7-Flash")

        if not self.api_key:
            raise ValueError("API Key 缺失。请设置环境变量 'ZHIPU_API_KEY' 或在构造函数中传入。")

        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model
        )

    def generate_issue_description(self, commit_msg, diff_content):
        """
        基于代码差异（Diff）和提交信息，利用链式思考（CoT）反向推导并生成高质量 GitHub Issue。
        """
        
        # 优化后的提示词：引入思维链逻辑与严格的术语限制
        system_prompt = "你是一名世界顶尖的开源软件 QA 工程师，擅长从代码变更中洞察软件漏洞。"
        
        user_prompt = f"""
任务：请根据以下提供的【开发者提交信息】和【代码补丁（Diff）】，反向推导并撰写一个标准的 GitHub Issue 描述。

--- 
【开发者提交信息】: 
{commit_msg}

【代码补丁（Diff）】:
{diff_content[:3000]} 
---

撰写准则（必须严格遵守）：
1. **视角转换**：你必须完全站在“最终用户”的视角。用户不知道代码库的存在，只知道软件在运行时出错了。
2. **严禁泄密**：禁止在 Issue 中提及“补丁”、“Commit”、“Diff”、“函数名修改”或“变量重命名”。
3. **推导逻辑**：
   - 分析 Diff：这段代码修复了什么逻辑错误（例如：边界溢出、Null 指针、并发竞争、UI 错位）？
   - 映射场景：这种错误在用户操作什么功能时会爆发？
4. **内容结构**：
   - **问题标题**：用一句话简述错误现象。
   - **【问题描述】**：详细描述该 Bug 导致的功能异常。
   - **【复现步骤】**：提供 3-5 步清晰的操作流程，引导他人稳定复现该问题。
   - **【预期行为】**：描述软件在正常情况下应该如何表现。
   - **【实际行为】**：描述软件在当前 Bug 状态下的错误表现（如报错信息、崩溃或逻辑错误）。

请使用【中文】生成该 Issue。
"""

        try:
            # 调用模型，增加 seed 保证一定程度的可复现性，temperature 设为 0.5 兼顾创造力与逻辑
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                max_tokens=2000,
                top_p=0.9
            )
            
            content = response.choices[0].message.content
            
            if not content:
                return "Error: 模型返回内容为空。"
            
            return content.strip()

        except openai.APIConnectionError as e:
            return f"网络连接异常: 无法连接至 LLM 服务器 ({str(e)})"
        except openai.AuthenticationError:
            return "鉴权失败: 请检查 API Key 是否正确。"
        except Exception as e:
            return f"任务回译失败: {str(e)}"
'''
# --- 生产级调用示例 ---
if __name__ == "__main__":
    # 模拟数据
    sample_msg = "fix: prevent division by zero in metrics calculator"
    sample_diff = "--- a/metrics.py\n+++ b/metrics.py\n@@ -10,1 +10,1 @@\n-    return total / count\n+    return total / count if count != 0 else 0"

    # 初始化时可以通过环境变量或直接传参
    # os.environ["ZHIPU_API_KEY"] = "你的Key"
    
    try:
        translator = TaskBackTranslator(model="glm-4")
        issue_text = translator.generate_issue_description(sample_msg, sample_diff)
        print("Generated Issue:\n", issue_text)
    except Exception as e:
        print(e)

'''        