import os
import sys
import time
import logging
import base64
import io
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
# New Google GenAI SDK
from google import genai
from google.genai import types
from PIL import Image

from telegram import Update, InputMediaPhoto
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from ddgs import DDGS
import json
import signal
import re
import uuid
import requests

# Import our new brains
from memory_store import MemoryStore
from qwen_brain import QwenBrain
from task_store import TaskStore
from metube_client import MeTubeClient
from wordpress_client import WordPressClient
from file_watcher import FileWatcher
from blog_media_store import BlogMediaStore

# 1. Load Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(id_str.strip()) for id_str in os.getenv("ALLOWED_USER_IDS", "").split(",") if id_str.strip()]
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3-flash-preview") 
MAX_CONTEXT_MESSAGES = 20

# Initialize Google GenAI Client
genai_client = genai.Client(api_key=GOOGLE_API_KEY, http_options={'api_version': 'v1beta'})

# Global Store Instances (Initialized in main)
memory_store = None
qwen_brain = None
task_store = None
metube_client = None
file_watcher = None
blog_media_store = None

# 2. Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ... (omitted parts) ...

def generate_image_native(prompt: str, negative_prompt: str = None, count: int = 1) -> list[bytes]:
    """
    Generates images using Google GenAI SDK (Nano Banana Pro / gemini-3-pro-image-preview).
    Returns a list of image bytes.
    """
    full_prompt = prompt
    if negative_prompt:
        full_prompt += f"\nNegative Prompt: {negative_prompt}"
        
    logger.info(f"Generating {count} Images via Nano Banana Pro for: {full_prompt}")
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            # Use generate_content instead of chat for one-off image generation
            config = types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                candidate_count=1 
            )
            
            current_prompt = full_prompt
            if count > 1:
                current_prompt += f"\n(Please generate {count} distinct variations)"

            # Use models.generate_content directly
            response = genai_client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=[current_prompt],
                config=config
            )
            
            found_images = []
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                                found_images.append(part.inline_data.data)
                            else:
                                try: 
                                    img = part.as_image()
                                    if img:
                                        buf = io.BytesIO()
                                        img.save(buf, format="PNG")
                                        found_images.append(buf.getvalue())
                                except: pass

            if found_images:
                # If plural, return list; if single expected, return first?
                # The caller expects a list [bytes] based on return type hint, 
                # but we'll return found_images which is already a list.
                return found_images
            else:
                raise Exception("No images found in response.")

        except Exception as e:
            error_msg = str(e)
            # Handle 503 (Service Unavailable) or 429 (Too Many Requests)
            is_retryable = "503" in error_msg or "UNAVAILABLE" in error_msg or "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg
            
            if is_retryable and attempt < max_retries - 1:
                # Exponential backoff: 4s, 8s, 16s...
                delay = base_delay * (2 ** (attempt + 1))
                logger.warning(f"Gemini API Error (Retryable) | Retry {attempt+1}/{max_retries} in {delay}s... Error: {error_msg}")
                time.sleep(delay)
                continue
            
            logger.error(f"Generate Content Error: {e}")
            raise e

def generate_image_edit(prompt: str, image_bytes: bytes, negative_prompt: str | None = None, count: int = 1) -> list[bytes]:
    """
    Bio-inspired Image Editing (Image-to-Image) using Nano Banana Pro.
    Returns list of bytes.
    """
    full_prompt = f"Edit this image to match the following description. Maintain the original composition and subject where possible: {prompt}"
    if negative_prompt:
        full_prompt += f"\nNegative Prompt: {negative_prompt}"
    
    if count > 1:
        full_prompt += f"\n(Please generate {count} distinct variations)"
        
    logger.info(f"Editing Image via Nano Banana Pro with prompt: {full_prompt}")
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            from PIL import Image
            input_img = Image.open(io.BytesIO(image_bytes))
            
            config = types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )

            # Use models.generate_content for edit too
            response = genai_client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=[input_img, full_prompt],
                config=config
            )
            
            found_images = []
            if response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                                found_images.append(part.inline_data.data)
                            else:
                                try:
                                    img = part.as_image()
                                    if img:
                                        buf = io.BytesIO()
                                        img.save(buf, format="PNG")
                                        found_images.append(buf.getvalue())
                                except: pass
            
            if found_images:
                return found_images
            else:
                raise Exception("No edited images found in response.")

        except Exception as e:
            error_msg = str(e)
            if ("503" in error_msg or "UNAVAILABLE" in error_msg) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Gemini Edit 503 | Retry {attempt+1}/{max_retries} in {delay}s... Error: {error_msg}")
                time.sleep(delay)
                continue
                
            logger.error(f"Generate Content Edit Error: {e}")
            raise e

# 3. Global Instances
# In a robust app these would be in a Context object, but for a script globals are fine.
memory_store = None
qwen_brain = None
task_store = None
metube_client = None
file_watcher = None
blog_media_store = None

# 4. Helper Functions
def get_system_prompt(memories=""):
    current_date = datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.now().strftime("%Y")

    return f"""You are a helpful and friendly AI assistant. 
Current Date: {current_date} (Year: {current_year})

PROTOCOL:
1. **SYSTEM ALERTS**: If the input starts with or contains `[SYSTEM ALERT]`, it means a background process has ALREADY taken action. You MUST acknowledge it. 
   - Example: "[SYSTEM ALERT]: Reminder set" -> You say: "Okay, I've set that reminder."

2. Analyze the user's request.

3. **SEARCH**: If the user asks about weather, news, stocks, or real-time info:
   - For general queries, respond with: SEARCH: <English Keywords>
   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>

   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>
   
   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>
   
4. **IMAGE GENERATION / EDITING (Nano Banana Pro)**:
   - If user asks to DRAW/GENERATE an image:
     - Respond: `DRAW_ADVANCED: <High Quality Positive Prompt> ||| NEGATIVE: <Negative Prompt>`
   - If user asks to EDIT/MODIFY the LAST uploaded image:
     - Respond: `EDIT_ADVANCED: <High Quality Positive Prompt> ||| NEGATIVE: <Negative Prompt>`
   - **CRITICAL**: 
     - Expand the prompt to be detailed (lighting, style, resolution).
     - Include a NEGATIVE prompt (e.g. low quality, blurry, mutated).
     - ONLY return the plain string starting with `DRAW_ADVANCED:` or `EDIT_ADVANCED:`.
   - Example 1: `DRAW_ADVANCED: a cute cat, cinematic lighting, 8k, photorealistic ||| NEGATIVE: blurry, bad anatomy, low res`
   - Example 2: `EDIT_ADVANCED: make it cyberpunk style, neon lights, high contrast ||| NEGATIVE: black and white, dull`

5. If general chat, respond in Chinese.
6. If the retrieved memory is relevant, use it to personalize the answer.

7. **Reminders**: Your 'Subconscious Mind' (Qwen) handles reminders automatically. 
   - If you see a [SYSTEM ALERT] about a reminder being set, CONFIRM it to the user. 
   - If the user asks for a reminder, assume your Subconscious Mind handles it, and just say "好的，我会提醒你" (Okay, I will remind you). DO NOT say you cannot do it.

8. Do not make up facts. Do not output internal thought processes or JSON unless explicitly asked for code.

[IMPORTANT - RETRIEVED CONTEXT]
The following information was retrieved from your long-term memory. 
You should use this information to personalize your response, BUT ONLY IF it is directly relevant to the user's current topic. 
If it is irrelevant context (e.g. user asks "how are you" and memory says "user likes apples"), IGNORE IT.
{memories}
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

def fetch_url_content(url):
    """Fetch and extract the main text content from a URL."""
    logger.info(f"Fetching full article content from: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html = response.text
        
        # Basic HTML to text extraction
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
        # Convert common block elements to newlines
        html = re.sub(r'<br\s*/?\s*>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</(p|div|h[1-6]|li|tr|blockquote)>', '\n\n', html, flags=re.IGNORECASE)
        
        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        
        # Decode HTML entities
        import html as html_module
        text = html_module.unescape(text)
        
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if len(line) > 20]  # Filter short noise lines
        text = '\n\n'.join(lines)
        
        # Limit to reasonable length (first ~8000 chars to stay within model context)
        if len(text) > 8000:
            text = text[:8000] + "\n\n[... article truncated ...]"
        
        logger.info(f"Fetched {len(text)} chars of article content from {url}")
        return text
        
    except Exception as e:
        logger.error(f"Failed to fetch URL content: {e}")
        return f"Error fetching URL: {e}"

async def reminder_callback(context: ContextTypes.DEFAULT_TYPE):
    """Refactored callback for reminders."""
    job = context.job
    try:
        await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ 提醒: {job.data}")
        logger.info(f"Reminder sent successfully to {job.chat_id}")
    except Exception as e:
        logger.error(f"Failed to send reminder to {job.chat_id}: {e}")


async def check_tasks(context: ContextTypes.DEFAULT_TYPE):
    """
    Periodic task to check for pending reminders and clean up stale downloads.
    """
    if not task_store: return
    
    pending = task_store.get_pending_tasks()
    now = datetime.now()
    
    for task in pending:
        # Only process REMINDERS here
        if task.get('type') != 'reminder':
            continue

        try:
            target_dt = datetime.strptime(task['target_timestamp'], "%Y-%m-%d %H:%M:%S")
            # If time has passed (or is very close, e.g. within 5 seconds)
            if now >= target_dt:
                # Send the reminder
                chat_id = task['chat_id']
                content = f"⏰ 提醒 (来自过去): {task['content']}"
                
                # If target is not 'me', clarify who it's for/from logic if needed, 
                # but for now let's keep it simple or reuse the stored content.
                # In process_agent_logic we arguably already formatted the content? 
                # Let's check. Yes, we formatted it.
                
                await context.bot.send_message(chat_id=chat_id, text=content)
                logger.info(f"Executed task: {task['id']}")
                
                # Mark complete
                task_store.complete_task(task['id'])
                
        except Exception as e:
            logger.error(f"Error checking task {task['id']}: {e}")

    # --- Cleanup Stale Downloads (Timeout) ---
    if task_store:
        failed_tasks = task_store.cleanup_stale_tasks(hours=0.17) # ~10 mins
        for task in failed_tasks:
            try:
                chat_id = task.get('chat_id')
                if not chat_id: continue
                
                task_type = task.get('type')
                
                if task_type == "download_req":
                    url_snippet = task.get('url', 'Unknown URL')
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ 下载任务超时 (10分钟) 已取消: {url_snippet}\n请检查 MeTube 是否正常工作或视频是否过大。")
                else:
                    # Generic timeout message for other task types
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ 任务超时 (10分钟) 已取消: {task_type}")
                    
            except Exception as e:
                logger.error(f"Failed to notify user of timeout {task['id']}: {e}")

async def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, delay_seconds: int):
    """
    DEPRECATED: Use TaskStore instead. 
    Kept for backward compatibility or immediate feedback if needed.
    """
    # We will now route this to TaskStore for persistence if delay > 10s?
    # actually, let's strictly use TaskStore for everything to ensure persistence even for short timers if crashe happens.
    # But for very short timers (< 10s), the periodic checker (every 10s) might miss it being "exact".
    # So:
    # 1. Calculate Target Time
    target_dt = datetime.now() + timedelta(seconds=delay_seconds)
    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # 2. Add to Store
    if task_store:
        task_store.add_task(text, target_str, chat_id)
        
    # 3. If delay is short (< 15s), ALSO schedule an in-memory job to ensure promptness?
    # OR just run the checker more often? 
    # Let's trust the checker for now, or maybe do both but handle deduplication?
    # Deduplication is hard. Let's start with just TaskStore.
    # To make it responsive, we can trigger a check immediately?
    # For now, let's just log it.
    logger.info(f"Task scheduled via TaskStore: {text} at {target_str}")


# 5. Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="你好！我是你的增强型 AI 助手。\n我拥有 Gemini 的智慧和 Qwen 的记忆。")

# Global Lock for Serializing Requests (Queue)
processing_lock = asyncio.Lock()

# Media Group Buffer
# Structure: { media_group_id: { 'images': [b64_1, b64_2], 'caption': "...", 'timer': <asyncio.Task> } }
media_group_cache = {}

async def process_media_group(context, chat_id, media_group_id, update):
    """
    Callback to process the buffered media group after debounce timer.
    """
    if media_group_id not in media_group_cache: return
    
    data = media_group_cache.pop(media_group_id)
    images = data['images']
    caption = data['caption']
    
    logger.info(f"Processing Media Group {media_group_id} with {len(images)} images.")
    await context.bot.send_message(chat_id=chat_id, text=f"📸 收到 {len(images)} 张图片，正在整合分析...")

    # Acquire Lock (Enter Queue)
    if processing_lock.locked():
        await context.bot.send_message(chat_id=chat_id, text="⏳ 前一名用户正在处理中，请稍候（排队中）...")
    
    async with processing_lock:
        # Pass list of images to logic
        await process_agent_logic(context, chat_id, caption, image_b64=None, update=update, additional_images=images)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Text messages."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if user.id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized.")
        return

    user_input = update.message.text
    if not user_input: return
    
    logger.info(f"TEXT Received from {user.first_name}: {user_input}")
    
    # Acquire Lock (Enter Queue)
    if processing_lock.locked():
        await context.bot.send_message(chat_id=chat_id, text="⏳ 前一名用户正在处理中，请稍候（排队中）...")
    
    async with processing_lock:
        await process_agent_logic(context, chat_id, user_input, image_b64=None, update=update)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Photo messages."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if user.id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized.")
        return

    caption = update.message.caption if update.message.caption else "Please analyze this image."
    # If part of media group, update.message.caption might be None on some parts, find strict check later or just use last non-empty.
    
    logger.info(f"PHOTO Received from {user.first_name}. GroupID: {update.message.media_group_id} Caption: {caption}")
    
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_buffer = io.BytesIO()
        await photo_file.download_to_memory(img_buffer)
        
        # Save cache for editing (Always save last single image for quick edit)
        image_bytes = img_buffer.getvalue()
        context.user_data['last_image_bytes'] = image_bytes
        
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        logger.info("Image downloaded, cached, and encoded.")
        
        # --- Media Group Logic ---
        mg_id = update.message.media_group_id
        if mg_id:
            if mg_id not in media_group_cache:
                media_group_cache[mg_id] = {
                    'images': [],
                    'caption': caption,
                    'timer': None
                }
            
            # Add image
            media_group_cache[mg_id]['images'].append(image_b64)
            
            # Update caption if current one is better (e.g. not default)
            if caption and caption != "Please analyze this image.":
                media_group_cache[mg_id]['caption'] = caption
            
            # Debounce Timer
            if media_group_cache[mg_id]['timer']:
                media_group_cache[mg_id]['timer'].cancel()
            
            async def trigger():
                await asyncio.sleep(2.0) # Wait 2 seconds for other photos
                await process_media_group(context, chat_id, mg_id, update)
                
            media_group_cache[mg_id]['timer'] = asyncio.create_task(trigger())
            return # Stop here, let timer trigger processing
        
        # --- Single Photo Logic (Legacy) ---
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        
        # Acquire Lock (Enter Queue)
        if processing_lock.locked():
             await context.bot.send_message(chat_id=chat_id, text="⏳ 前一名用户正在处理中，请稍候...")

        async with processing_lock:
            await process_agent_logic(context, chat_id, caption, image_b64=image_b64, update=update)
            
    except Exception as e:
        logger.error(f"Photo processing error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"图片处理失败: {e}")

async def update_agenda_msg(context, chat_id, agenda_msg_id, batch_id):
    """Updates the Telegram message with the current status of all tasks in a batch."""
    if not task_store or not agenda_msg_id: return
    
    tasks = task_store.get_tasks_by_batch(batch_id)
    if not tasks: return
    
    agenda_text = "📋 *任务执行清单 / Task Agenda*\n\n"
    for task in tasks:
        status = task.get("status", "pending")
        icon = "⏳"
        if status == "in_progress": icon = "🔄"
        elif status == "completed": icon = "✅"
        elif status == "failed": icon = "❌"
        
        task_type = task.get("type", "unknown")
        display_name = task_type.replace("_", " ").title()
        
        # Payload Details
        payload = task.get("payload", {})
        detail = ""
        if task_type == "web_search": detail = f": _{payload.get('query', '')}_"
        elif task_type == "image_generation": detail = f": _{payload.get('prompt', '')[:30]}..._"
        elif task_type == "wordpress_post": detail = f": _{payload.get('topic', '')}_"
        elif task_type == "translation": detail = f": _{payload.get('target_language', '翻译')}_"
        elif task_type == "reminder": detail = f": _{task.get('content', '')}_"
        
        agenda_text += f"{icon} {display_name}{detail}\n"

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=agenda_msg_id,
            text=agenda_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        # Avoid spamming logs if content didn't change (Telegram error)
        if "Message is not modified" not in str(e):
            logger.warning(f"Agenda update failed: {e}")

async def process_agent_logic(context, chat_id, user_input, image_b64, update, additional_images=None):
    """Shared Logic with Multi-Task Execution and Persistent Agenda"""
    if additional_images is None: additional_images = []
    download_status_msg = None
    batch_id = str(uuid.uuid4())
    agenda_msg_id = None
    
    # --- Phase 0: Check if user is confirming media cleanup ---
    if context.user_data.get('pending_media_cleanup'):
        lower_input = user_input.strip().lower()
        confirm_words = ['可以', '是', '好', '删除', '删', 'yes', 'ok', 'sure', '确认', '对', '好的', '嗯']
        deny_words = ['不', '别', '不要', 'no', '取消', '保留', '暂时不']
        
        if any(w in lower_input for w in confirm_words):
            if blog_media_store:
                deleted = blog_media_store.delete_published(chat_id)
                await context.bot.send_message(chat_id=chat_id, text=f"🗑️ 已删除 {deleted} 个本地博客素材文件。")
            context.user_data['pending_media_cleanup'] = False
            return
        elif any(w in lower_input for w in deny_words):
            await context.bot.send_message(chat_id=chat_id, text="👌 好的，本地素材暂时保留。")
            context.user_data['pending_media_cleanup'] = False
            return
        else:
            # Not a clear answer, clear the flag and proceed normally
            context.user_data['pending_media_cleanup'] = False
    
    # --- Phase 1: Qwen Analysis (Parallel / Background) ---
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2. Retrieve Memory
    retrieved_docs = []
    if memory_store:
        candidates = memory_store.search_memory(user_input, user_id=update.effective_user.id, n_results=10)
        if candidates:
            # Skip expensive DeepSeek filter for small candidate sets — just use them all
            if len(candidates) <= 10:
                retrieved_docs = candidates
                logger.info(f"Memory: Using all {len(candidates)} candidates directly (small set, skip filter)")
            elif qwen_brain:
                try:
                    retrieved_docs = await asyncio.to_thread(qwen_brain.filter_memories, user_input, candidates)
                    logger.info(f"Memory Filter: {len(candidates)} -> {len(retrieved_docs)}")
                    # FALLBACK: If filter returns nothing but candidates exist, use top 10
                    if not retrieved_docs:
                         logger.warning("DeepSeek filter returned 0 results. Using top 10 candidates as fallback.")
                         retrieved_docs = candidates[:10]
                except Exception as e:
                    logger.error(f"Filter failed, using top 10: {e}")
                    retrieved_docs = candidates[:10]
            else:
                retrieved_docs = candidates[:5]

    memory_context = ""
    if retrieved_docs:
        memory_context = "\n".join([f"- {m}" for m in retrieved_docs])
        logger.info(f"Memory Context Injected: {len(retrieved_docs)} items, {len(memory_context)} chars")
    else:
        logger.info("Memory Context: EMPTY (no relevant memories found)")

    # 3. Analyze Message with Qwen
    # analysis is now a dictionary containing a LIST of tasks
    analysis = {}
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if qwen_brain:
        logger.info("Starting DeepSeek Analysis (Tasks)...")
        try:
            analysis = await asyncio.wait_for(
                asyncio.to_thread(qwen_brain.analyze_message, user_input, current_time_str),
                timeout=60.0
            )
            logger.info(f"Qwen Task Plan: {analysis}")
        except Exception as qwen_err:
            logger.error(f"Qwen Error: {qwen_err}")
            
    # --- Phase 1.5: Task Registration & Agenda Init ---
    execution_log = []
    raw_tasks = analysis.get("tasks", [])
    if not isinstance(raw_tasks, list): raw_tasks = []
    
    registered_tasks = []
    if raw_tasks and task_store:
        # Register all identified tasks first
        for rt in raw_tasks:
            t_type = rt.get("type")
            # Map reminder logic slightly differently as it uses content/target_time
            if t_type == "reminder":
                new_t = task_store.add_task(rt.get("content", ""), rt.get("target_time", ""), chat_id, rt.get("target_user", "me"), batch_id=batch_id)
            else:
                new_t = task_store.add_generic_task(t_type, rt, chat_id, batch_id=batch_id)
            registered_tasks.append(new_t)
            
        # Send Agenda Message
        agenda_reply = await context.bot.send_message(
            chat_id=chat_id, 
            text="📋 *任务清单已准备...*", 
            parse_mode='Markdown'
        )
        agenda_msg_id = agenda_reply.message_id
        await update_agenda_msg(context, chat_id, agenda_msg_id, batch_id)

    # --- Phase 2: Sequential Task Execution ---
    for task_obj in registered_tasks:
        task_id = task_obj["id"]
        task_type = task_obj["type"]
        task_payload = task_obj.get("payload", task_obj) # remind uses root as payload for comp
        
        # Mark as In Progress
        if task_store:
            task_store.update_task_status(task_id, "in_progress")
            await update_agenda_msg(context, chat_id, agenda_msg_id, batch_id)
        
        success = True
        error_msg = None
        
        try:
            # --- Blog Media Save ---
            if task_type == "blog_media_save":
                if blog_media_store:
                    saved_count = 0
                    # Save the primary image
                    if image_b64:
                        img_bytes = base64.b64decode(image_b64)
                        mid = blog_media_store.add_media(img_bytes, f"blog_photo_{int(time.time())}.jpg", chat_id, caption=user_input)
                        saved_count += 1
                    # Save additional images (from media group)
                    if additional_images:
                        for idx, b64 in enumerate(additional_images):
                            img_bytes = base64.b64decode(b64)
                            mid = blog_media_store.add_media(img_bytes, f"blog_photo_{int(time.time())}_{idx}.jpg", chat_id, caption=user_input)
                            saved_count += 1
                    
                    total = blog_media_store.get_media_count(chat_id)
                    if saved_count > 0:
                        await context.bot.send_message(chat_id=chat_id, text=f"📎 已保存 {saved_count} 张图片作为博客素材（当前共 {total} 张待用）")
                        execution_log.append(f"[System] Saved {saved_count} blog media images (total: {total})")
                    else:
                        await context.bot.send_message(chat_id=chat_id, text="⚠️ 没有检测到图片，请在发送图片时附上'博客素材'等说明。")
                        execution_log.append("[System] blog_media_save triggered but no images found")

            # --- Memory Save ---
            elif task_type == "memory_save":
                content = task_payload.get("content")
                if memory_store and content:
                    await asyncio.to_thread(memory_store.add_memory, content, {"source": "user_chat", "user_id": update.effective_user.id})
                    execution_log.append(f"[System] Saved memory: {content}")
            
            # --- Download ---
            elif task_type == "download":
                url = task_payload.get("url")
                if metube_client and url:
                    await context.bot.send_message(chat_id=chat_id, text=f"📥 正在添加到 MeTube 下载队列: {url}")
                    d_success = await asyncio.to_thread(metube_client.add_download, url)
                    if d_success:
                        execution_log.append(f"[System] Successfully added download for: {url}")
                        if task_store: task_store.add_download_request(chat_id, url=url, batch_id=batch_id)
                    else:
                        success = False
                        error_msg = "MeTube connection failed"
                        execution_log.append(f"[System] Failed to add download: {url}")
            
            # --- Reminder ---
            elif task_type == "reminder":
                content = task_payload.get("content")
                time_str = task_payload.get("target_timestamp") # Qwen gives target_time, store uses target_timestamp
                if not time_str: time_str = task_payload.get("target_time")
                target_user = task_payload.get("target_user")
                
                if content and time_str:
                    # Logic is already in task_store.add_task called in Phase 1.5
                    # We just need to log it here for the execution log
                    await context.bot.send_message(chat_id=chat_id, text=f"⏰ 已设定提醒: {time_str} -> {target_user if target_user else 'me'}: {content}")
                    execution_log.append(f"[System] Reminder set for {target_user} at {time_str}: {content}")
                else:
                    success = False
                    error_msg = "Missing content or time for reminder"
    
            # --- Web Search ---
            elif task_type == "web_search":
                query = task_payload.get("query")
                is_news = task_payload.get("is_news", False)
                if query:
                    # await context.bot.send_message(chat_id=chat_id, text=f"🔍 正在搜索: {query}...") # Handled by Agenda
                    search_res = await asyncio.to_thread(search_web, query, 'd' if is_news else None)
                    execution_log.append(f"[System] Search Results for '{query}':\n{search_res}")
                else:
                    success = False
                    error_msg = "No search query provided"
            
            # --- Image Generation ---
            elif task_type == "image_generation":
                prompt = task_payload.get("prompt")
                neg_prompt = task_payload.get("negative_prompt")
                count = task_payload.get("count", 1)
                action = task_payload.get("action", "draw")
                
                if prompt:
                     try:
                         # Edit Check
                         images = []
                         if action == "edit":
                             input_image_bytes = context.user_data.get('last_image_bytes')
                             if not input_image_bytes:
                                 await context.bot.send_message(chat_id=chat_id, text="⚠️ 无法编辑: 没找到上一张图.")
                                 execution_log.append("[System] Image Edit Failed: No input image.")
                                 success = False
                                 error_msg = "No source image for edit"
                                 continue
                             images = await asyncio.to_thread(generate_image_edit, prompt, input_image_bytes, neg_prompt, count)
                         else:
                             # Draw
                             images = await asyncio.to_thread(generate_image_native, prompt, neg_prompt, count)
                         
                         # Send Images
                         if images:
                             if len(images) > 1:
                                 from telegram import InputMediaPhoto
                                 media_group = [InputMediaPhoto(img_data, caption=f"✨ {prompt[:50]}..." if i == 0 else None) for i, img_data in enumerate(images)]
                                 await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                             else:
                                 await context.bot.send_photo(chat_id=chat_id, photo=images[0], caption=f"✨ {prompt[:100]}...")
                             
                             execution_log.append(f"[System] Successfully generated {len(images)} images for prompt '{prompt}'.")
                         else:
                             success = False
                             error_msg = "No images returned from SDK"
                         
                     except Exception as e:
                         logger.error(f"Image Gen Failed: {e}")
                         await context.bot.send_message(chat_id=chat_id, text=f"❌ 图片生成失败: {e}")
                         execution_log.append(f"[System] Image generation failed: {e}")
                         success = False
                         error_msg = str(e)
    
            # --- Translation ---
            elif task_type == "translation":
                try:
                    source_url = task_payload.get("source_url", "")
                    target_language = task_payload.get("target_language", "中文")
                    t_instructions = task_payload.get("instructions", "")
                    
                    # PRIORITY 1: Fetch full article content directly from URL
                    source_material = ""
                    if source_url:
                        await context.bot.send_message(chat_id=chat_id, text=f"📄 正在获取原文内容: {source_url}")
                        fetched = await asyncio.to_thread(fetch_url_content, source_url)
                        if fetched and not fetched.startswith("Error"):
                            source_material = fetched
                            logger.info(f"Successfully fetched full article: {len(source_material)} chars")
                    
                    # PRIORITY 2: If URL fetch failed, try to find URL from user message or search results
                    if not source_material:
                        # Check if there's a URL in the execution log from web_search
                        for entry in execution_log:
                            if "Search Results" in entry:
                                # Extract URLs from search results
                                import re as re_mod
                                urls_found = re_mod.findall(r'Link:\s*(https?://\S+)', entry)
                                if urls_found:
                                    await context.bot.send_message(chat_id=chat_id, text=f"📄 从搜索结果获取原文...")
                                    fetched = await asyncio.to_thread(fetch_url_content, urls_found[0])
                                    if fetched and not fetched.startswith("Error"):
                                        source_material = fetched
                                        break
                    
                    # PRIORITY 3: Last resort - use search snippets (low quality)
                    if not source_material:
                        for entry in execution_log:
                            if "Search Results" in entry:
                                source_material += entry + "\n"
                        if source_material:
                            logger.warning("Using search snippets as translation source (lower quality)")
                    
                    if source_material:
                        await context.bot.send_message(chat_id=chat_id, text=f"📝 正在翻译全文为{target_language}（共{len(source_material)}字符）...")
                        
                        translation_prompt = (
                            f"Translate the following article content into {target_language}.\n"
                            f"Instructions: {t_instructions}\n"
                            f"CRITICAL RULES:\n"
                            f"1. Produce a FAITHFUL, HIGH-QUALITY translation of the COMPLETE source article.\n"
                            f"2. Do NOT summarize, condense, or rewrite. Translate EVERY paragraph.\n"
                            f"3. Preserve the original article's structure, quotes, data points, and details.\n"
                            f"4. Keep proper nouns, researcher names, institution names in their original form.\n\n"
                            f"=== SOURCE ARTICLE START ===\n{source_material}\n=== SOURCE ARTICLE END ==="
                        )
                        
                        trans_response = genai_client.models.generate_content(
                            model=GEMINI_MODEL_NAME,
                            contents=[translation_prompt],
                            config=types.GenerateContentConfig(temperature=0.2)
                        )
                        
                        translated_text = trans_response.text
                        if translated_text:
                            execution_log.append(f"[Translation Result]\n{translated_text}")
                            logger.info(f"Translation completed: {len(translated_text)} chars")
                        else:
                            raise Exception("Translation returned empty result")
                    else:
                        success = False
                        error_msg = "No source material found for translation"
                        
                except Exception as e:
                    logger.error(f"Translation Failed: {e}")
                    success = False
                    error_msg = str(e)
                    execution_log.append(f"[System] Translation failed: {e}")

            # --- WordPress Post ---
            elif task_type == "wordpress_post":
                try:
                    topic = task_payload.get("topic", "AI Update")
                    instructions = task_payload.get("instructions", "")
                    image_prompt = task_payload.get("image_prompt", f"A banner image about {topic}")
                    source_content = task_payload.get("source_content", "")
                    use_uploaded_media = task_payload.get("use_uploaded_media", False)
                    
                    # --- CRITICAL FIX: Default image_count based on use_uploaded_media ---
                    # When using uploaded media, default to 1 (just a featured/thumbnail image)
                    # When Qwen explicitly sets image_count, use that value
                    default_image_count = 1 if use_uploaded_media else 3
                    image_count = task_payload.get("image_count", default_image_count)
                    
                    # === CONTENT PIPELINE ===
                    prior_content = ""
                    user_writing_instructions = ""
                    
                    if source_content == "prior_tasks":
                        # Collect translated content and search results from execution_log
                        for entry in execution_log:
                            if entry.startswith("[Translation Result]"):
                                prior_content += entry.replace("[Translation Result]", "").strip() + "\n\n"
                            elif "Search Results" in entry:
                                prior_content += entry + "\n\n"
                        
                        if prior_content:
                            logger.info(f"Using prior task content for WordPress post ({len(prior_content)} chars)")
                            image_prompt = f"Professional blog illustration related to: {prior_content[:200]}"
                        else:
                            logger.warning("source_content='prior_tasks' but no prior content found in execution_log. Falling back to generation.")
                    
                    elif source_content == "user_instructions":
                        # User provided their own writing instructions (e.g. "写一篇关于AI摄影的博客")
                        user_writing_instructions = instructions
                        logger.info(f"Using user_instructions for blog content: {user_writing_instructions[:100]}...")
                    
                    # 1. Prepare Images
                    image_urls = []
                    media_ids = []
                    task_subdir = os.path.join("workspace", "task_assets", f"wp_{int(time.time())}")
                    os.makedirs(task_subdir, exist_ok=True)
                    
                    wp_user = os.getenv("WP_USER")
                    wp_password = os.getenv("WP_PASSWORD")
                    wp_url = os.getenv("WP_BASE_URL", "")
                    wp = WordPressClient(wp_url, wp_user, wp_password)

                    # --- 1a. Upload user's pre-saved blog media ---
                    uploaded_user_media = False
                    user_media_captions = []  # Collect captions for content generation
                    if use_uploaded_media and blog_media_store:
                        pending_media = blog_media_store.get_pending_media(chat_id)
                        if pending_media:
                            await context.bot.send_message(chat_id=chat_id, text=f"\ud83d\udce4 \u6b63\u5728\u4e0a\u4f20 {len(pending_media)} \u5f20\u7528\u6237\u7d20\u6750\u5230\u535a\u5ba2...")
                            for idx, media_entry in enumerate(pending_media):
                                try:
                                    img_bytes = blog_media_store.get_media_bytes(media_entry["id"])
                                    if img_bytes:
                                        fname = media_entry.get("original_filename", f"user_media_{idx}.jpg")
                                        upload_id = await asyncio.to_thread(wp.upload_media, img_bytes, fname)
                                        media_info = requests.get(f"{wp_url}/media/{upload_id}", auth=wp.auth).json()
                                        img_url = media_info.get("source_url")
                                        if img_url:
                                            image_urls.append(img_url)
                                            media_ids.append(upload_id)
                                            # Track caption for content generation
                                            cap = media_entry.get("caption", "")
                                            if cap:
                                                user_media_captions.append(f"Image {idx+1}: {cap}")
                                            logger.info(f"Uploaded user blog media {idx+1}: {img_url}")
                                except Exception as e:
                                    logger.error(f"Failed to upload user media {media_entry['id']}: {e}")
                            
                            uploaded_user_media = len(image_urls) > 0
                            if uploaded_user_media:
                                logger.info(f"User media uploaded: {len(image_urls)} images. AI image_count remains: {image_count}")
                        else:
                            logger.info("use_uploaded_media=True but no pending media found.")

                    # --- 1b. Generate AI images (if still needed) ---
                    for i in range(image_count):
                        logger.info(f"Generating image {i+1}/{image_count} for blog topic: {topic}")
                        try:
                            # 1.5 Rate Limit Optimization: Add a small sleep between sequential calls
                            if i > 0 or uploaded_user_media:
                                sleep_time = 5 # 5 seconds delay is safe for 20 RPM
                                logger.info(f"Rate limit pacing: Sleeping for {sleep_time}s before next request...")
                                await asyncio.sleep(sleep_time)

                            # Slightly vary prompt to ensure model gives different scenes
                            varied_prompt = f"{image_prompt} (Scene {i+1}: highly detailed, professional blog illustration)"
                            gen_images = await asyncio.to_thread(generate_image_native, varied_prompt, count=1)
                            
                            if gen_images:
                                img_data = gen_images[0]
                                filename = f"blog_img_{i}_{int(time.time())}.png"
                                local_path = os.path.join(task_subdir, filename)
                                
                                with open(local_path, "wb") as f:
                                    f.write(img_data)
                                
                                # VERIFICATION: Send to Telegram so user sees what is being uploaded
                                await context.bot.send_photo(chat_id=chat_id, photo=img_data, caption=f"🖼️ 为博客生成的第 {i+1} 张图片")
                                
                                # Upload ONLY the bytes that were just saved to workspace
                                upload_id = await asyncio.to_thread(wp.upload_media, img_data, filename)
                                # Fetch public URL
                                media_info = requests.get(f"{wp_url}/media/{upload_id}", auth=wp.auth).json()
                                img_url = media_info.get("source_url")
                                
                                if img_url:
                                    image_urls.append(img_url)
                                    media_ids.append(upload_id)
                                    logger.info(f"Successfully uploaded and retrieved URL for AI Image {i+1}: {img_url}")
                            else:
                                logger.warning(f"Failed to generate image {i+1}: No bytes returned.")
                        except Exception as e:
                            logger.error(f"Error during generation/upload of Image {i+1}: {e}")
                            # We continue to the next image instead of failing the whole task

                    if not image_urls:
                        raise Exception("Failed to generate or upload any images for the blog post.")

                    # 2. Generate Content — USE PRIOR CONTENT if available, else generate from scratch
                    urls_list_str = "\n".join([f"- IMAGE_URL_{i+1}: {url}" for i, url in enumerate(image_urls)])
                    
                    gutenberg_image_instruction = (
                        "For images, use Gutenberg block format:\n"
                        "<!-- wp:image {\"sizeSlug\":\"large\"} -->\n"
                        "<figure class=\"wp-block-image size-large\"><img src=\"URL\" alt=\"description\"/>"
                        "<figcaption>caption</figcaption></figure>\n"
                        "<!-- /wp:image -->\n"
                    )
                    gutenberg_format_instruction = (
                        "CRITICAL FORMAT RULES:\n"
                        "1. Output the 'content' field in WordPress Gutenberg BLOCK format, NOT raw HTML.\n"
                        "2. Wrap each paragraph in: <!-- wp:paragraph --><p>text</p><!-- /wp:paragraph -->\n"
                        "3. Wrap each heading in: <!-- wp:heading --><h2>text</h2><!-- /wp:heading -->\n"
                        f"4. {gutenberg_image_instruction}"
                        "5. You MUST embed ALL provided image URLs at logical break points.\n"
                        "6. STRICT: Only use the provided IMAGE_URL_X links. Do NOT invent URLs.\n"
                    )
                    tags_instruction = (
                        "Also generate 5-8 relevant tags for SEO. Include both Chinese and English tags if appropriate.\n"
                    )
                    
                    if prior_content:
                        # === USE PRIOR CONTENT (translation / search results) ===
                        blog_system_prompt = (
                            "You are an expert blog formatter. "
                            "Output exclusively in JSON format: {\"title\": \"...\", \"content\": \"Gutenberg block content\", \"tags\": [\"tag1\", \"tag2\", ...]}. "
                            "COMMAND: Take the provided translated article content and format it as a WordPress Gutenberg block blog post. "
                            "DO NOT rewrite, summarize, or change the meaning. Keep the translation faithful. "
                            + gutenberg_format_instruction + tags_instruction
                        )
                        blog_user_prompt = (
                            f"Here is the translated article content to format as a blog post:\n\n"
                            f"{prior_content}\n\n"
                            f"Available Images (Embed ALL of these in order):\n{urls_list_str}\n\n"
                            f"Format this content as a Gutenberg block blog post. Keep the translation intact. Use ONLY the URLs above for images."
                        )
                    elif user_writing_instructions:
                        # === USE USER'S OWN INSTRUCTIONS as the basis for blog ===
                        # This is used when user uploads photos and says what to write about.
                        # The blog content should be based on user's instructions, NOT generic AI-generated stuff.
                        media_context = ""
                        if user_media_captions:
                            media_context = f"\n\nThe user uploaded {len(image_urls)} photos. Their descriptions/context: " + "; ".join(user_media_captions)
                        
                        blog_system_prompt = (
                            "You are an expert blogger who writes based on the user's specific instructions and their uploaded photos. "
                            "Output exclusively in JSON format: {\"title\": \"...\", \"content\": \"Gutenberg block content\", \"tags\": [\"tag1\", \"tag2\", ...]}. "
                            "CRITICAL: Write the blog content BASED ON the user's instructions. The user has uploaded their own photos, "
                            "so the text should naturally reference and discuss those photos as if the author took them. "
                            "Write in the voice and perspective the user described. Do NOT make up generic content about the topic - "
                            "follow the user's writing direction closely. "
                            + gutenberg_format_instruction + tags_instruction
                        )
                        blog_user_prompt = (
                            f"Topic: {topic}\n"
                            f"Writing Instructions from user: {user_writing_instructions}\n"
                            f"{media_context}\n\n"
                            f"Available Images (Embed ALL of these at logical points in the article):\n{urls_list_str}\n\n"
                            f"IMPORTANT: Use ONLY the URLs above for images. Write the blog following the user's instructions. "
                            f"Refer to the uploaded photos naturally in the text (e.g. '\u5982\u56fe\u6240\u793a', '\u8fd9\u5f20\u7167\u7247\u4e2d', etc.)."
                        )
                    else:
                        # === FALLBACK: Generate from scratch ===
                        blog_system_prompt = (
                            "You are an expert tech blogger. "
                            "Output exclusively in JSON format: {\"title\": \"...\", \"content\": \"Gutenberg block content\", \"tags\": [\"tag1\", \"tag2\", ...]}. "
                            "The 'content' must be high-quality WordPress Gutenberg block format. "
                            + gutenberg_format_instruction + tags_instruction
                        )
                        blog_user_prompt = (
                            f"Topic: {topic}\n"
                            f"Instructions: {instructions}\n\n"
                            f"Available Images (Embed ALL of these in order):\n{urls_list_str}\n\n"
                            f"IMPORTANT: Use ONLY the URLs above. Write a comprehensive Gutenberg block blog post."
                        )
    
                    blog_response = genai_client.models.generate_content(
                        model=GEMINI_MODEL_NAME,
                        contents=[blog_user_prompt],
                        config=types.GenerateContentConfig(system_instruction=blog_system_prompt, response_mime_type='application/json')
                    )
                    
                    blog_data = json.loads(blog_response.text)
                    title = blog_data.get("title", topic)
                    content = blog_data.get("content", "")
                    auto_tags = blog_data.get("tags", [])

    
                    # 3. Resolve Tags and Categories to WordPress IDs
                    tag_ids = []
                    if auto_tags and isinstance(auto_tags, list):
                        await context.bot.send_message(chat_id=chat_id, text=f"🏷️ 正在创建标签: {', '.join(auto_tags[:8])}")
                        for tag_name in auto_tags[:8]:
                            tag_id = await asyncio.to_thread(wp.get_or_create_tag, str(tag_name))
                            if tag_id:
                                tag_ids.append(tag_id)
                    
                    category_ids = []
                    user_category = task_payload.get("category", "")
                    if user_category:
                        cat_id = await asyncio.to_thread(wp.get_or_create_category, user_category)
                        if cat_id:
                            category_ids.append(cat_id)

                    # 4. Create the Post
                    featured_id = media_ids[0] if media_ids else None
                    post_data = await asyncio.to_thread(
                        wp.create_post, title, content, 
                        status='publish', 
                        categories=category_ids if category_ids else None,
                        tags=tag_ids if tag_ids else None,
                        featured_media_id=featured_id
                    )
                    
                    link = post_data.get('link')
                    tag_info = f"，标签: {', '.join(auto_tags[:5])}" if auto_tags else ""
                    cat_info = f"，分类: {user_category}" if user_category else ""
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 博客发布成功（包含 {len(image_urls)} 张图片{tag_info}{cat_info}）！\n🔗 {link}")
                    execution_log.append(f"[System] Published multimedia blog post with {len(image_urls)} images: {link}")

                    import shutil
                    shutil.rmtree(task_subdir)
                    logger.info(f"Cleaned up temporary assets: {task_subdir}")

                    # --- Mark uploaded media as published & ask about cleanup ---
                    if uploaded_user_media and blog_media_store:
                        published_count = blog_media_store.mark_published(chat_id)
                        if published_count > 0:
                            context.user_data['pending_media_cleanup'] = True
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f"📁 博客已成功发布，本地暂存的 {published_count} 个素材文件是否可以删除？\n回复'可以'删除，或'保留'暂不删除。"
                            )

                except Exception as e:
                    logger.error(f"WP Task Failed: {e}")
                    success = False
                    error_msg = str(e)
                    execution_log.append(f"[System] Blog post failed: {e}")


        except Exception as outer_e:
            logger.error(f"Sequential Execution Error: {outer_e}")
            success = False
            error_msg = str(outer_e)

        if task_store:
            final_status = "completed" if success else "failed"
            task_store.update_task_status(task_id, final_status, error=error_msg)
            await update_agenda_msg(context, chat_id, agenda_msg_id, batch_id)

    # --- Phase 3: Gemini Final Response ---
    try:
        MAX_CONTEXT_MESSAGES = 10
        m_ctx = memory_context  # Use the variable computed in Phase 2 (NOT analysis dict)
        final_system_context = str(m_ctx) + "\n\n[RECENT ACTIONS LOG]:\n" + "\n".join(execution_log)
        sys_instruct = get_system_prompt(final_system_context)
        
        if 'history' not in context.user_data: context.user_data['history'] = []
        gemini_history = []
        for msg in context.user_data['history'][-MAX_CONTEXT_MESSAGES:]:
            # Convert context.user_data history to Gemini SDK format
            role_map = {'user': 'user', 'assistant': 'model'}
            gemini_history.append(types.Content(role=role_map.get(msg['role'], 'user'), parts=[types.Part.from_text(text=msg['content'])]))

        chat = genai_client.chats.create(
            model=GEMINI_MODEL_NAME,
            history=gemini_history,
            config=types.GenerateContentConfig(temperature=0.7, system_instruction=sys_instruct)
        )
        
        prompt_parts = [user_input]
        if image_b64:
            prompt_parts.append(types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type="image/jpeg"))
        if additional_images:
            for b64 in additional_images:
                prompt_parts.append(types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/jpeg"))

        response = await asyncio.to_thread(chat.send_message, prompt_parts)
        msg_content = response.text
        logger.info(f"Gemini Response: {msg_content}")

        if msg_content:
            await context.bot.send_message(chat_id=chat_id, text=msg_content)
            context.user_data['history'].append({"role": "user", "content": user_input})
            context.user_data['history'].append({"role": "assistant", "content": msg_content})

            # --- Self-Correction Logic for "Agentic" JSON Output ---
            if msg_content.strip().startswith('{') and "action" in msg_content:
                try:
                    data = json.loads(msg_content)
                    if data.get("action") in ["generate_image", "draw", "edit"]:
                        action_input = data.get("action_input")
                        prompt = ""
                        if isinstance(action_input, str): prompt = action_input
                        elif isinstance(action_input, dict): prompt = action_input.get("prompt", "")
                        
                        if prompt:
                            logger.info(f"Intercepted JSON Tool Call. Extracted prompt: {prompt}")
                            # Recursive call to handle drawing if model output JSON
                            # (Optional: for now just log it as a success/failure)
                except: pass

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"抱歉，发生了错误: {e}")

    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Gemini Error.")

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
        print("Initializing Task Store...")
        task_store = TaskStore()
        print("Initializing Blog Media Store...")
        blog_media_store = BlogMediaStore()
        print("Initializing MeTube Client...")
        metube_client = MeTubeClient()
        print("Initializing File Watcher...")
        # SMB Path provided by user
        smb_path = r"\\192.168.1.28\LaCie\Projects\metube\downloads"
        file_watcher = FileWatcher(watch_dir=smb_path)
    except Exception as e:
        print(f"Failed to init components: {e}")
        sys.exit(1)

    # Define post_init to start FileWatcher
    async def post_init(app):
        
        async def file_callback(filepath):
            filename = os.path.basename(filepath)
            
            # Determine target chat using Smart Matching
            target_chat_id = None
            pending_task = None
            
            if task_store:
                all_pending = task_store.get_all_pending_download_requests()
                
                # 1. Smart Match: Check if Video ID or URL snippet is in filename
                # Filenames often contain [VideoID] or match title. 
                # Simplest check: if task['url'] contains ID, and filename contains ID.
                # Or just if filename contains part of URL?
                # YouTube URLs: v=VIDEO_ID
                
                for task in all_pending:
                    url = task.get('url', "")
                    if not url: continue
                    
                    video_id = None
                    # Basic extraction for YT
                    if "youtube.com" in url or "youtu.be" in url:
                        import re
                        # Try to find exactly 11 chars? or just alphanumeric?
                        # Standard YT ID is 11 chars.
                        # Pattern: v=([a-zA-Z0-9_-]{11})
                        match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
                        if match:
                            video_id = match.group(1)
                    
                    if video_id and video_id in filename:
                        logger.info(f"Smart Match! Filename '{filename}' matches Task {task['id']} (VideoID: {video_id})")
                        pending_task = task
                        target_chat_id = task["chat_id"]
                        break
                
                # 2. Fallback: FIFO (Oldest) if no smart match found
                if not pending_task and all_pending:
                     # Just take the first one?
                     # Risk: If file is unrelated, we might send it to wrong person.
                     # But current behavior IS this.
                     # Let's verify if filename looks like a temp file? FileWatcher handles that.
                     # Let's assume FIFO is better than nothing, but log it.
                     pending_task = all_pending[0]
                     target_chat_id = pending_task["chat_id"]
                     logger.info(f"Fallback FIFO Match: Assigning '{filename}' to Task {task['id']}")

            if target_chat_id:
                try:
                    await app.bot.send_message(chat_id=target_chat_id, text=f"🎥 下载完成: {filename}\n正在发送...")
                    # Send as document
                    with open(filepath, 'rb') as f:
                        await app.bot.send_document(chat_id=target_chat_id, document=f, filename=filename)
                    
                    # Mark task as complete ONLY after successful send
                    if pending_task and task_store:
                        task_store.complete_task(pending_task["id"])
                        
                except Exception as e:
                    logger.error(f"Failed to send file {filename}: {e}")
                    await app.bot.send_message(chat_id=target_chat_id, text=f"❌ 发送文件失败: {filename}\n{e}\n(任务已从队列中移除)")
                    
                    # IMPORTANT: Mark task as failed/completed so it doesn't block the queue!
                    if pending_task and task_store:
                        # We mark as 'completed' (or could add 'failed' status) to remove it from 'pending' list
                        task_store.complete_task(pending_task["id"])

        if file_watcher:
            asyncio.create_task(file_watcher.start(file_callback))
            print("File Watcher Background Task Started.")
        
        # Start Periodic Task Checker
        if app.job_queue:
             app.job_queue.run_repeating(check_tasks, interval=10, first=1)
             print("Periodic Task Checker started.")

    # Build App
    try:
        builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)
        builder.post_init(post_init)
        application = builder.build()
        
        application.add_handler(CommandHandler('start', start))
        
        # Explicit Handlers
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        
        print("Agent is running with Explicit Vision Handlers! (Ctrl+C to stop)")
        application.run_polling()
    except KeyboardInterrupt:
        print("\nBot stopped by user. Goodbye!")
    except Exception as e:
        logger.fatal(f"Critical Error in Main Loop: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        # Consider saving a panic log file
        with open("panic.log", "w") as f:
            f.write(str(e))
        sys.exit(1)