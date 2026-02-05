import os
import sys
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from ddgs import DDGS
import json
import signal
import re

# Import our new brains
from memory_store import MemoryStore
from qwen_brain import QwenBrain

# 1. Load Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(id_str.strip()) for id_str in os.getenv("ALLOWED_USER_IDS", "").split(",") if id_str.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gemini-2.0-flash-exp") # Updated default
MAX_CONTEXT_MESSAGES = 20

# 2. Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 3. Global Instances
# In a robust app these would be in a Context object, but for a script globals are fine.
memory_store = None
qwen_brain = None

# 4. Helper Functions
def get_system_prompt(memories=""):
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().strftime("%Y")
    
    memory_section = ""
    if memories:
        memory_section = f"\n\n[RETRIEVED MEMORY/KNOWLEDGE]\nUse this information if relevant:\n{memories}\n"

    return f"""You are a helpful and friendly AI assistant. 
Current Date: {current_date} (Year: {current_year})
{memory_section}
PROTOCOL:
1. **SYSTEM ALERTS**: If the input starts with or contains `[SYSTEM ALERT]`, it means a background process has ALREADY taken action. You MUST acknowledge it. 
   - Example: "[SYSTEM ALERT]: Reminder set" -> You say: "Okay, I've set that reminder."
2. Analyze the user's request.
2. **SEARCH**: If the user asks about weather, news, stocks, or real-time info:
   - For general queries, respond with: SEARCH: <English Keywords>
   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>
3. If searching, translate the query to English.
4. If general chat, respond in Chinese.
5. If the retrieved memory is relevant, use it to personalize the answer.
6. **Reminders**: Your 'Subconscious Mind' (Qwen) handles reminders automatically. 
   - If you see a [SYSTEM ALERT] about a reminder being set, CONFIRM it to the user. 
   - If the user asks for a reminder, assume your Subconscious Mind handles it, and just say "好的，我会提醒你" (Okay, I will remind you). DO NOT say you cannot do it.
7. Do not make up facts.
"""

def search_web(query, time_limit=None):
    logger.info(f"Searching web for: {query} (Limit: {time_limit})")
    try:
        # Removed backend="html" to allow default (usually "api") for fresher results
        # time_limit options: 'd' (day), 'w' (week), 'm' (month), 'y' (year)
        results = DDGS().text(query, region="wt-wt", max_results=5, timelimit=time_limit)
        if not results:
            return "No results found."
        
        summary = "Search Results:\n"
        for i, res in enumerate(results):
            summary += f"[{i+1}] {res['title']}\nSnippet: {res['body']}\nLink: {res['href']}\n\n"
        return summary
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Error during search: {e}"

async def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, delay_seconds: int):
    """Schedule a job to send a reminder."""
    # Define the callback function for the job
    async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
        await context.bot.send_message(chat_id=chat_id, text=f"⏰ 提醒: {text}")

    # Use the job queue
    try:
        if context.job_queue:
            context.job_queue.run_once(reminder_job, delay_seconds, chat_id=chat_id)
            logger.info(f"Scheduled reminder for chat {chat_id} in {delay_seconds}s: {text}")
        else:
             logger.error("JobQueue not available in context!")
             await context.bot.send_message(chat_id=chat_id, text="⚠ 系统错误：定时任务队列未初始化，无法设置提醒。")
    except Exception as e:
        logger.error(f"Failed to schedule reminder: {e}")
        await context.bot.send_message(chat_id=chat_id, text="⚠ 系统错误：设置提醒失败。")

# 5. Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="你好！我是你的增强型 AI 助手。\n我拥有 Gemini 的智慧和 Qwen 的记忆。")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized.")
        return

    user_input = update.message.text
    if not user_input:
        return

    # --- Phase 1: Qwen Analysis (Parallel / Background) ---
    # We run this conceptually in parallel. For simplicity in this turn-based bot, we await it,
    # OR better: we run it in a thread so we don't block the event loop for too long.
    
    # 1. Start Gemini Typing Indicator
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2. Retrieve Memory (Synchronous ChromaDB call, fast enough usually)
    retrieved_docs = memory_store.search_memory(user_input, n_results=3)
    memory_context = qwen_brain.synthesize_context(retrieved_docs)
    logger.info(f"Memories found: {len(retrieved_docs)}")

    # 3. Analyze Message with Qwen (for saving/reminders)
    # Run in thread to avoid blocking loop
    analysis = {} # Default empty
    try:
        analysis = await asyncio.to_thread(qwen_brain.analyze_message, user_input)
        logger.info(f"Qwen Analysis: {analysis}")
    except Exception as qwen_err:
        logger.error(f"Qwen Brain Critical Failure: {qwen_err}")
        # Continue execution without Qwen features
        pass

    # Process Analysis result
    if analysis.get('save_memory') and analysis.get('extracted_knowledge'):
        knowledge = analysis['extracted_knowledge']
        # Save to DB
        await asyncio.to_thread(memory_store.add_memory, knowledge, {"source": "user_chat", "user_id": user_id})
        # Optionally notify user? No, keep it subtle.

    if analysis.get('reminder_needed') and analysis.get('reminder_content'):
        # Parse time. For MVP, we'll try to guess simple seconds or just do 60s default if parsing fails
        # A real agent needs a parser library like dateparser
        # Here we just look for simple keywords or default.
        delay = 60 # Default 1 min
        content = analysis['reminder_content']
        
        # Very naive parsing for demo
        time_str = str(analysis.get('reminder_time', '')).lower()
        if "minute" in time_str or "分" in time_str:
             # extract number?
             # import re (moved to top)
             nums = re.findall(r'\d+', time_str)
             if nums:
                 delay = int(nums[0]) * 60
        elif "second" in time_str or "秒" in time_str:
             nums = re.findall(r'\d+', time_str)
             if nums:
                 delay = int(nums[0])
        
        await schedule_reminder(context, chat_id, content, delay)
        # Note: We let Gemini confirm the reminder normally, or we can inject it into Gemini's context that we set it.
        # Let's inject it.
        memory_context += f"\n[SYSTEM ALERT]: A reminder has been set for {delay} seconds from now about '{content}'."

    # --- Phase 2: Gemini Generation ---
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        
        messages = [{"role": "system", "content": get_system_prompt(memory_context)}]
        # We should ideally keep conversation history too, but for this refactor I'm simplifying 
        # to focus on the new features. Let's add simple in-memory history if needed, 
        # or just rely on the vector memory for long term context.
        # For a chat bot, recent context is vital.
        # Check if we have a simple history list in context.user_data?
        if 'history' not in context.user_data:
            context.user_data['history'] = []
        
        # Append sliding window
        for msg in context.user_data['history'][-10:]:
            messages.append(msg)
            
        messages.append({"role": "user", "content": user_input})
        
        # Call LLM
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_NAME,
            temperature=0.6,
            messages=messages
        )
        ai_message = response.choices[0].message.content.strip()

        # Handle SEARCH
        if ai_message.startswith("SEARCH:") or ai_message.startswith("SEARCH_NEWS:"):
            is_news = ai_message.startswith("SEARCH_NEWS:")
            prefix = "SEARCH_NEWS:" if is_news else "SEARCH:"
            query = ai_message.replace(prefix, "").strip()
            
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            
            # Use 'd' (past day) for news, or None for general
            time_limit = 'd' if is_news else None
            search_res = search_web(query, time_limit)
            
            messages.append({"role": "assistant", "content": ai_message})
            messages.append({"role": "user", "content": f"Verified Search Results:\n{search_res}\n\nAnswer the original question."})
            
            response_final = await client.chat.completions.create(
                model=OPENAI_MODEL_NAME,
                temperature=0.7,
                messages=messages
            )
            final_answer = response_final.choices[0].message.content
            await context.bot.send_message(chat_id=chat_id, text=final_answer)
            
            # Update History
            context.user_data['history'].append({"role": "user", "content": user_input})
            context.user_data['history'].append({"role": "assistant", "content": final_answer})
            
        else:
            await context.bot.send_message(chat_id=chat_id, text=ai_message)
            context.user_data['history'].append({"role": "user", "content": user_input})
            context.user_data['history'].append({"role": "assistant", "content": ai_message})

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="我的大脑（Gemini）遇到了一点问题。")

# 6. Main Entry
if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN missing.")
        sys.exit(1)

    # Initialize Brains
    try:
        print("Initializing Memory Store...")
        memory_store = MemoryStore()
        print("Initializing Qwen Brain...")
        qwen_brain = QwenBrain() # Assumes Ollama is running
    except Exception as e:
        print(f"Failed to init components: {e}")
        sys.exit(1)

    # Build App
    # Post-init implies JobQueue is available by default in recent versions if dependencies installed?
    # python-telegram-bot[job-queue] might be needed. 
    # Usually it's included if 'APScheduler' is installed. 
    # Let's hope 'python-telegram-bot' full was installed or we might need 'pip install python-telegram-bot[job-queue]'
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        print("Agent is running with Dual Brains! (Ctrl+C to stop)")
        application.run_polling()
    except Exception as e:
        logger.fatal(f"Critical Error in Main Loop: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        # Consider saving a panic log file
        with open("panic.log", "w") as f:
            f.write(str(e))
        sys.exit(1)