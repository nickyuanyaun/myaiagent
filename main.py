import os
import sys
import logging
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from ddgs import DDGS

# 1. Load Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(id_str.strip()) for id_str in os.getenv("ALLOWED_USER_IDS", "").split(",") if id_str.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gemini-3-flash-preview")

# 2. Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 3. Helper Functions
def get_system_prompt():
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().strftime("%Y")
    return f"""You are a helpful and friendly AI assistant. 
Current Date: {current_date} (Year: {current_year})

PROTOCOL:
1. Analyze the user's request.
2. If the user asks about current events, news, or information that might change (e.g., "latest news", "stock price", "who is the president"), you MUST perform a web search.
3. To search, respond ONLY with: SEARCH: <English Keywords>
   - Translate the query to English for better results.
   - Example: User "iPhone 16 release date", Output: SEARCH: iPhone 16 release date rumors {current_year}
4. If the user asks a general question or chit-chat, respond directly in Chinese.
5. You are allowed ONLY ONE search turn. If you receive search results, you must answer the user's question in Chinese based on those results.
6. If the search results are empty or irrelevant, you must admit you don't know (in Chinese).
"""

def search_web(query):
    logging.info(f"Searching web for: {query}")
    try:
        # region="wt-wt": Global search
        # backend="html": More robust backend
        results = DDGS().text(query, region="wt-wt", backend="html", max_results=10)
        
        if not results:
            return "No results found."
        
        summary = "Search Results:\n"
        for i, res in enumerate(results):
            summary += f"[{i+1}] {res['title']}\nSnippet: {res['body']}\nLink: {res['href']}\n\n"
        return summary
    except Exception as e:
        logging.error(f"Search error: {e}")
        return f"Error during search: {e}"

# 4. Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="你好！我是你的 AI 助手。我已经准备好回答你的问题（支持实时联网搜索）。")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, you are not authorized to use this bot.")
        return

    user_input = update.message.text
    if not user_input:
        return

    chat_id = update.effective_chat.id

    # Messages history for this turn
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": user_input}
    ]

    try:
        # Initialize Async Client per request (or globally, but lightweight enough)
        client = AsyncOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL
        )

        # Show typing status
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # --- Round 1: Thinking ---
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            temperature=1.0, # Creative for chat
            messages=messages
        )
        ai_message = response.choices[0].message.content.strip()

        # --- Check for Search Command ---
        if ai_message.startswith("SEARCH:"):
            search_query = ai_message.replace("SEARCH:", "").strip()
            
            # Notify user searching is happening (optional, but good UX)
            # await context.bot.send_message(chat_id=chat_id, text=f"🔍 正在搜索: {search_query}...")
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

            # Perform Search (Run in executor to avoid blocking async loop if DDGS blocks)
            # For simplicity, calling sync function directly; if DDGS blocks too long, might warn.
            # Ideally: loop = asyncio.get_running_loop(); await loop.run_in_executor(None, search_web, search_query)
            loop = asyncio.get_running_loop()
            search_results = await loop.run_in_executor(None, search_web, search_query)
            
            # --- Round 2: Answering with Data ---
            messages.append({"role": "assistant", "content": ai_message})
            messages.append({"role": "user", "content": f"System: verified search results:\n{search_results}\n\nPlease answer the original question in Chinese based on these results."})
            
            response_final = await client.chat.completions.create(
                model=OPENAI_MODEL_NAME,
                temperature=0.7, # More focused for grounded answers
                messages=messages
            )
            final_answer = response_final.choices[0].message.content
            
            await context.bot.send_message(chat_id=chat_id, text=final_answer)

        else:
            # Direct answer
            await context.bot.send_message(chat_id=chat_id, text=ai_message)

    except Exception as e:
        logging.error(f"Error handling message: {e}")
        await context.bot.send_message(chat_id=chat_id, text="抱歉，处理您的请求时出现错误。")

# 5. Main Entry
if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables.")
        sys.exit(1)

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    
    application.add_handler(start_handler)
    application.add_handler(message_handler)
    
    print("Telegram Bot is running...")
    application.run_polling()