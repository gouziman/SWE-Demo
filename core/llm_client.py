import openai
import os

class TaskBackTranslator:
    def __init__(self, api_key=None, base_url=None):
        # 也可以从环境变量读取
        self.client = openai.OpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or "https://api.openai.com/v1"
        )

    def generate_issue_description(self, commit_msg, diff_content):
        """
        根据代码差异反向生成 Issue 描述
        """
        prompt = f"""
你是一名资深的开源软件测试工程师。
我将给你一个修复 Bug 的代码补丁（Diff）和当时的提交信息（Commit Message）。
请你根据这些信息，反向推导并写出一个详细的 GitHub Issue 描述。

要求：
1. 站在用户的视角：描述用户在使用软件时遇到了什么现象/错误。
2. 严禁直接提到补丁里的修复代码或具体的函数修改。
3. 包含：问题背景、复现步骤、预期行为、实际行为。
4. 语言：中文（或英文，取决于你的 Agent 偏好）。

---
Commit Message: {commit_msg}
---
Code Diff:
{diff_content[:2000]} 
---
"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o", # 或 o1-mini
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Failed to generate description: {str(e)}"