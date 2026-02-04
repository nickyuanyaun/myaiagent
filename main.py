import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from datetime import datetime # 【关键】引入时间库
from dotenv import load_dotenv
from openai import OpenAI
from ddgs import DDGS

# 1. 加载配置
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")
model_name = os.getenv("OPENAI_MODEL_NAME", "gemini-2.0-flash")

# 2. 获取“活”的当前日期
# 这样每次运行，它都知道今天是哪一天，绝不会过时！
current_date = datetime.now().strftime("%Y年%m月%d日")
current_year = datetime.now().strftime("%Y") # 单独提取年份，比如 "2026"

# 3. 初始化客户端
client = OpenAI(api_key=api_key, base_url=base_url)

# 4. 定义搜索函数
def search_web(query):
    print(f"\n🔍 正在搜索互联网 (全球/全时间): {query} ...")
    try:
        # region="wt-wt": 全球搜索
        # max_results=10: 多抓几条
        results = DDGS().text(query, region="wt-wt", backend="html", max_results=10)
        
        if not results:
            return "搜索引擎返回空结果。"
        
        search_summary = ""
        for i, res in enumerate(results):
            search_summary += f"[{i+1}] {res['title']}\n摘要: {res['body']}\n链接: {res['href']}\n\n"
        return search_summary

    except Exception as e:
        return f"搜索出错: {e}"

# 5. 定义最强版 System Prompt (注入时间观念)
SYSTEM_PROMPT = f"""
你是一个精通多语言的智能助手。
【当前系统时间】：{current_date} (注意：今年是 {current_year} 年)

### 核心思维与时间观 (Time & Logic)
1. **你是最新的:** 你的运行时间是 {current_date}。必须时刻用这个时间去校准搜索结果。
2. **警惕旧关键词:** 在生成搜索关键词时，**务必包含 "{current_year}"**，绝对不要主动添加 "2024" 或 "2025" 这种旧年份，除非用户明确问过去的事。
3. **事实核查 (针对时事):** - 已知事实：委内瑞拉总统马杜罗已于 **2026年1月3日** 被美军逮捕。
   - 如果搜到说他“依然在任”的 2025 年文章，直接判定为**已过时信息**并忽略。

### 搜索与回答策略 (Protocol)
1. **关键词转译 (关键):** 为了获取全球一手资讯，涉及国际新闻、科技新品（如显卡、手机）时，**必须将中文关键词翻译成英文**去搜索。
   - 例：问“马杜罗被抓”，输出 `SEARCH: Maduro arrested by US Delta Force Jan {current_year}` (自动填入今年)
   - 例：问“RTX 5090 评测”，输出 `SEARCH: RTX 5090 review specs release date {current_year}`
2. **阅读与翻译:** 搜索回来的一般是英文网页，你必须**阅读理解**，然后**用中文**总结回答用户。
3. **禁止二次搜索:** 收到搜索结果后，必须直接作答，**严禁**再次输出 "SEARCH:" 指令。

### 输出规则
- 需要搜索时，只输出：SEARCH: <英文关键词>
- 不需要搜索时，直接用中文回答。
"""

messages = [{"role": "system", "content": SYSTEM_PROMPT}]

print("-" * 50)
print(f"🚀 AI Agent 已启动 | 当前时间: {current_date}")
print(f"🤖 使用模型: {model_name}")
print("-" * 50)

# 6. 主循环
while True:
    try:
        user_input = input("\n👤 你: ").strip()
        if user_input.lower() in ['quit', 'exit']:
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        # --- 第一轮：AI 思考 ---
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7
        )
        bot_reply = response.choices[0].message.content.strip()

        # --- 判断：AI 是否想上网？ ---
        if bot_reply.startswith("SEARCH:"):
            keyword = bot_reply.replace("SEARCH:", "").strip()
            
            # 执行搜索
            search_data = search_web(keyword)
            
            # 喂给 AI
            messages.append({"role": "assistant", "content": bot_reply})
            messages.append({"role": "user", "content": f"系统提示：这是搜索结果：\n{search_data}\n\n请根据以上搜索结果（特别是日期）回答用户的问题。"})
            
            print(f"📖 正在阅读网页内容...")

            # --- 第二轮：AI 根据资料回答 ---
            response_final = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7
            )
            final_answer = response_final.choices[0].message.content
            print(f"\r🤖 Gemini (联网版): {final_answer}")
            messages.append({"role": "assistant", "content": final_answer})

        else:
            print(f"🤖 Gemini: {bot_reply}")
            messages.append({"role": "assistant", "content": bot_reply})

    except Exception as e:
        print(f"\n❌ 出错: {e}")