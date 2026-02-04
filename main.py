import os
import sys
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("OPENAI_MODEL_NAME", "gemini-3-flash-preview")


if not api_key:
    print("❌ 错误：未找到 API Key。请检查 .env 文件！")
    sys.exit(1)

print(f"🚀 正在连接 Google Gemini 服务器...")
print(f"🤖 使用模型: {model_name}")


try:
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )
except Exception as e:
    print(f"❌ 初始化失败: {e}")
    sys.exit(1)


messages = [
    {"role": "system", "content": "你是一个乐于助人的 AI 助手。请用中文回答用户的问题。"}
]

print("-" * 50)
print("✅ Agent 已启动！(输入 'exit' 或 'quit' 退出)")
print("-" * 50)

# 5. 主循环
while True:
    try:
      
        user_input = input("\n👤 你: ").strip()

    
        if user_input.lower() in ['quit', 'exit']:
            print("👋 再见！")
            break
        
        if not user_input:
            continue

       
        messages.append({"role": "user", "content": user_input})

        
        print("🤖 Gemini 正在思考...", end="", flush=True)
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=1.0
        )

        
        bot_reply = response.choices[0].message.content
        print(f"\r🤖 Gemini: {bot_reply}") 

        
        messages.append({"role": "assistant", "content": bot_reply})

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")