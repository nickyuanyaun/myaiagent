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

import json
import signal

# 1. Load Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(id_str.strip()) for id_str in os.getenv("ALLOWED_USER_IDS", "").split(",") if id_str.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gemini-3-flash-preview")
MEMORY_FILE = "memory.json"
MAX_CONTEXT_MESSAGES = 20 # Only send last 20 messages to API to save tokens

# 2. Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 3. Helper Functions
def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load memory: {e}")
        return {}

def save_memory(memory_data):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(memory_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save memory: {e}")

def get_system_prompt():
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().strftime("%Y")
    return f"""You are a helpful and friendly AI assistant. 
Current Date: {current_date} (Year: {current_year})

PROTOCOL:
1. Analyze the user's request.
2. If the user asks about **weather**, current events, news, stock prices, or any information that changes with time, you **MUST** perform a web search.
3. To search, respond ONLY with: SEARCH: <English Keywords>
   - Translate the query to English for better results.
   - Example: User "Suzhou weather", Output: SEARCH: Suzhou weather forecast
4. If the user asks a general question or chit-chat, respond directly in Chinese.
5. **CRITICAL**: Do not make up facts or dates. If you are not sure, SEARCH.
6. You are allowed ONLY ONE search turn. If you receive search results, you must answer the user's question in Chinese based on those results.
7. If the search results are empty or irrelevant, you must admit you don't know (in Chinese).
"""

def search_web(query):
    logging.info(f"Searching web for: {query}")
    try:
        # region="wt-wt": Global search
        # backend="html": More robust backend
        results = DDGS().text(query, region="wt-wt", backend="html", max_results=10)
        
        if not results:
            logging.warning("DDGS returned empty results.")
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
    str_user_id = str(user_id)

    # --- Load Memory ---
    memory = load_memory()
    if str_user_id not in memory:
        memory[str_user_id] = []
    
    user_history = memory[str_user_id]

    # --- Construct Context for API (Sliding Window) ---
    # Always include System Prompt
    messages = [{"role": "system", "content": get_system_prompt()}]
    
    # Append recent history (last N messages) + current user input
    # Note: user_history is a list of stored dicts
    recent_history = user_history[-MAX_CONTEXT_MESSAGES:] if user_history else []
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_input})

    try:
        # Initialize Async Client per request
        client = AsyncOpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL
        )

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # --- Round 1: Thinking ---
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            temperature=0.6,
            messages=messages
        )
        ai_message = response.choices[0].message.content.strip()

        # Update temporary conversation list for Round 2 if needed
        # We don't save Round 1 "SEARCH:" commands to long-term memory to keep it clean,
        # OR we can save them. Let's ONLY save the final QA pairs to keep memory clean.

        # --- Check for Search Command ---
        if ai_message.startswith("SEARCH:"):
            search_query = ai_message.replace("SEARCH:", "").strip()
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

            # Perform Search
            search_results = search_web(search_query)
            
            # --- Round 2: Answering with Data ---
            messages.append({"role": "assistant", "content": ai_message})
            messages.append({"role": "user", "content": f"System: verified search results:\n{search_results}\n\nPlease answer the original question in Chinese based on these results."})
            
            response_final = await client.chat.completions.create(
                model=OPENAI_MODEL_NAME,
                temperature=0.7,
                messages=messages
            )
            final_answer = response_final.choices[0].message.content
            
            await context.bot.send_message(chat_id=chat_id, text=final_answer)
            
            # --- Save Final Interaction to Memory ---
            user_history.append({"role": "user", "content": user_input})
            user_history.append({"role": "assistant", "content": final_answer})

        else:
            # Direct answer
            await context.bot.send_message(chat_id=chat_id, text=ai_message)
            
            # --- Save Direct Interaction to Memory ---
            user_history.append({"role": "user", "content": user_input})
            user_history.append({"role": "assistant", "content": ai_message})

        # --- Persist Memory ---
        memory[str_user_id] = user_history
        save_memory(memory)

    except Exception as e:
        logging.error(f"Error handling message: {e}")
        await context.bot.send_message(chat_id=chat_id, text="抱歉，处理您的请求时出现错误。")

# 5. Signal Handling for Graceful Shutdown
def signal_handler(signum, frame):
    print("\nReceived termination signal. Exiting gracefully...")
    # Add any specific cleanup code here if needed
    sys.exit(0)

# 6. Main Entry
if __name__ == '__main__':
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables.")
        sys.exit(1)

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    
    application.add_handler(start_handler)
    application.add_handler(message_handler)
    
    print("Telegram Bot is running... (Press Ctrl+C to stop)")
    application.run_polling()