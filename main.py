import os
import sys
import logging
import base64
import io
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import AsyncOpenAI
# New Google GenAI SDK
from google import genai
from google.genai import types
from PIL import Image

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
from qwen_brain import QwenBrain
from task_store import TaskStore
from metube_client import MeTubeClient
from wordpress_client import WordPressClient, DEFAULT_WP_CONFIG
from file_watcher import FileWatcher

# 1. Load Configuration
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(id_str.strip()) for id_str in os.getenv("ALLOWED_USER_IDS", "").split(",") if id_str.strip()]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gemini-2.0-flash-exp") 
MAX_CONTEXT_MESSAGES = 20

# Initialize Google GenAI Client (for Built-in Image Gen)
# Uses the same key as OpenAI-compatible endpoint usually, or needs GOOGLE_API_KEY.
# For Gemini API, they are often the same if using AI Studio.
genai_client = genai.Client(api_key=OPENAI_API_KEY, http_options={'api_version': 'v1beta'})

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
    try:
        # Create chat session with Nano Banana Pro
        # Note: 'candidate_count' might not be supported in 'chat.create' config directly for all models, 
        # but we can try to ask for it in the prompt or rely on the model generating multiple parts if configured?
        # For 'generate_images' wrapper it's easier, but here we use chat. 
        # We will assume the model generates 4 images by default or we can try to hint it.
        # Actually Nano Banana Pro (preview) often generates 4 images by default if not specified? 
        # Let's try to just capture all parts.
        
        config = types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            candidate_count=1 # Chat usually only supports 1 candidate with multiple parts? 
            # actually 'imagen' allows 'sampleCount', but this is 'gemini-3-pro'.
        )
        
        chat = genai_client.chats.create(
            model="gemini-3-pro-image-preview",
            config=config
        )
        
        # If user wants multiple, maybe we modify prompt?
        if count > 1:
            full_prompt += f"\n(Please generate {count} distinct variations)"

        response = chat.send_message(full_prompt)
        
        found_images = []
        
        if response.parts:
            for part in response.parts:
                # Priority 1: Direct bytes from inline_data
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                    logger.info(f"Found image part. Size: {len(part.inline_data.data)}")
                    found_images.append(part.inline_data.data)
                
                # Priority 2: Use SDK helper if available (Fallback)
                else:
                    try: 
                        img = part.as_image()
                        if img:
                            buf = io.BytesIO()
                            try: img.save(buf, format="PNG")
                            except: img.save(buf)
                            found_images.append(buf.getvalue())
                    except: pass

        if found_images:
            return found_images
        else:
            raise Exception("No images found in response parts.")

    except Exception as e:
        logger.error(f"Nano Banana Pro Error: {e}")
        raise e

def generate_image_edit(prompt: str, image_bytes: bytes, negative_prompt: str = None, count: int = 1) -> list[bytes]:
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
    try:
        from PIL import Image
        
        # Load the input image
        input_img = Image.open(io.BytesIO(image_bytes))
        
        # Create chat session
        # We try to use candidate_count if possible, or reliance on prompt
        config = types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            candidate_count=1 
        )
        
        chat = genai_client.chats.create(
            model="gemini-3-pro-image-preview",
            config=config
        )
        
        response = chat.send_message([full_prompt, input_img])
        
        found_images = []
        if response.parts:
            for part in response.parts:
                if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.data:
                     found_images.append(part.inline_data.data)
                else:
                    try: 
                        img = part.as_image()
                        if img:
                            buf = io.BytesIO()
                            try: img.save(buf, format="PNG")
                            except: img.save(buf)
                            found_images.append(buf.getvalue())
                    except: pass

        if found_images:
            return found_images
        else:
            raise Exception("No edited image found in response.")

    except Exception as e:
        logger.error(f"Nano Banana Pro Edit Error: {e}")
        raise e

# 3. Global Instances
# In a robust app these would be in a Context object, but for a script globals are fine.
memory_store = None
qwen_brain = None
task_store = None
metube_client = None
file_watcher = None

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

async def process_agent_logic(context, chat_id, user_input, image_b64, update, additional_images=None):
    """Shared Logic with Multi-Task Execution"""
    if additional_images is None: additional_images = []
    
    # --- Phase 1: Qwen Analysis (Parallel / Background) ---
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2. Retrieve Memory
    retrieved_docs = []
    if memory_store:
        candidates = memory_store.search_memory(user_input, user_id=update.effective_user.id, n_results=10)
        if qwen_brain and candidates:
            try:
                retrieved_docs = await asyncio.to_thread(qwen_brain.filter_memories, user_input, candidates)
            except Exception as e:
                retrieved_docs = candidates[:3]
        else:
            retrieved_docs = candidates[:3]

    memory_context = ""
    if qwen_brain:
        memory_context = qwen_brain.synthesize_context(retrieved_docs)

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
            
    # --- Phase 2: Sequential Task Execution ---
    
    tasks = analysis.get("tasks", [])
    execution_log = [] # To tell Gemini what we did
    
    # Pre-check for hallucinations
    if not isinstance(tasks, list): tasks = []

    for i, task in enumerate(tasks):
        task_type = task.get("type")
        
        # --- Memory Save ---
        if task_type == "memory_save":
            content = task.get("content")
            if memory_store and content:
                await asyncio.to_thread(memory_store.add_memory, content, {"source": "user_chat", "user_id": update.effective_user.id})
                execution_log.append(f"[System] Saved memory: {content}")
        
        # --- Download ---
        elif task_type == "download":
            url = task.get("url")
            if metube_client and url:
                await context.bot.send_message(chat_id=chat_id, text=f"📥 正在添加到 MeTube 下载队列: {url}")
                success = await asyncio.to_thread(metube_client.add_download, url)
                if success:
                    execution_log.append(f"[System] Successfully added download for: {url}")
                    if task_store: task_store.add_download_request(chat_id)
                else:
                    execution_log.append(f"[System] Failed to add download: {url}")
        
        # --- Reminder ---
        elif task_type == "reminder":
            content = task.get("content")
            time_str = task.get("target_time")
            target_user = task.get("target_user")
            
            if content and time_str:
                # Calculate delay
                delay = 5
                try:
                    target_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    diff = (target_dt - datetime.now()).total_seconds()
                    delay = max(2, int(diff))
                except: 
                    # Fallback relative logic if needed, but Qwen should give absolute
                     pass
                
                # Resolving Target
                target_chat_id = chat_id 
                FAMILY_DIRECTORY = {
                     "dad": 1660122746, "father": 1660122746, "baba": 1660122746, 
                     "mom": 8295191474, "mother": 8295191474, "mama": 8295191474,
                     "son": 8526935699, "nick": 8526935699, "me": chat_id
                }
                if target_user and target_user.lower() in FAMILY_DIRECTORY:
                    target_chat_id = FAMILY_DIRECTORY[target_user.lower()]
                
                final_content = content
                if target_chat_id != chat_id:
                     sender = update.effective_user.first_name
                     final_content = f"{sender} 让我告诉你：{content}"
                
                # Schedule
                if task_store:
                    task_store.add_task(final_content, time_str, target_chat_id, target_user)
                    
                await context.bot.send_message(chat_id=chat_id, text=f"⏰ 已设定提醒: {time_str} -> {target_user if target_user else 'me'}: {content}")
                execution_log.append(f"[System] Reminder set for {target_user} at {time_str}: {content}")

        # --- Web Search ---
        elif task_type == "web_search":
            query = task.get("query")
            is_news = task.get("is_news", False)
            if query:
                await context.bot.send_message(chat_id=chat_id, text=f"🔍 正在搜索: {query}...")
                search_res = search_web(query, 'd' if is_news else None)
                execution_log.append(f"[System] Search Results for '{query}':\n{search_res}")
        
        # --- Image Generation ---
        elif task_type == "image_generation":
            prompt = task.get("prompt")
            neg_prompt = task.get("negative_prompt")
            count = task.get("count", 1)
            action = task.get("action", "draw")
            
            if prompt:
                 msg_text = f"🎨 正在生成 {count} 张图片: {prompt[:20]}..."
                 if action == "edit": msg_text = f"🎨 正在编辑图片 ({count}张)..."
                 
                 await context.bot.send_message(chat_id=chat_id, text=msg_text)
                 await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                 
                 try:
                     # Edit Check
                     images = []
                     if action == "edit":
                         input_image_bytes = context.user_data.get('last_image_bytes')
                         if not input_image_bytes:
                             await context.bot.send_message(chat_id=chat_id, text="⚠️ 无法编辑: 没找到上一张图.")
                             execution_log.append("[System] Image Edit Failed: No input image.")
                             continue
                         images = await asyncio.to_thread(generate_image_edit, prompt, input_image_bytes, neg_prompt, count)
                     else:
                         # Draw
                         images = await asyncio.to_thread(generate_image_native, prompt, neg_prompt, count)
                     
                     # Send Images
                     if images:
                         # Telegram MediaGroup only supports up to 10 items.
                         if len(images) > 1:
                             from telegram import InputMediaPhoto
                             media_group = []
                             for idx, img_data in enumerate(images):
                                 caption = f"Image {idx+1}/{len(images)}\nPrompt: {prompt[:50]}..." if idx == 0 else None
                                 media_group.append(InputMediaPhoto(img_data, caption=caption))
                             await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                         else:
                             await context.bot.send_photo(chat_id=chat_id, photo=images[0], caption=f"✨ {prompt[:100]}...")
                         
                         execution_log.append(f"[System] Successfully generated {len(images)} images for prompt '{prompt}'.")
                     
                 except Exception as e:
                     logger.error(f"Image Gen Failed: {e}")
                     await context.bot.send_message(chat_id=chat_id, text=f"❌ 图片生成失败: {e}")
                     execution_log.append(f"[System] Image generation failed: {e}")

        # --- WordPress Post ---
        elif task_type == "wordpress_post":
            try:
                topic = task.get("topic", "AI Update")
                instructions = task.get("instructions", "")
                image_prompt = task.get("image_prompt", f"A banner image about {topic}")
                
                await context.bot.send_message(chat_id=chat_id, text=f"📝 正在为您撰写关于“{topic}”的博客文章...")
                
                # 1. Generate Content (Title + HTML)
                # We need a separate client instance here or reuse one if available. 
                # Since client is local to Phase 3, we create a temporary one.
                wp_gen_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
                
                blog_system_prompt = """
                You are a professional blog writer. 
                Output a JSON object with:
                - "title": A catchy headline.
                - "content": The blog post body in HTML format (use <h2>, <p>, <ul>, <li>). Do NOT use <html>/<body> tags.
                """
                blog_user_prompt = f"Topic: {topic}\nInstructions: {instructions}\nWrite the blog post now."

                # Attempt JSON mode if model supports, otherwise prompt engineering
                response = await wp_gen_client.chat.completions.create(
                    model=OPENAI_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": blog_system_prompt},
                        {"role": "user", "content": blog_user_prompt}
                    ],
                    response_format={"type": "json_object"} 
                )
                
                try:
                    blog_data = json.loads(response.choices[0].message.content)
                    title = blog_data.get("title", topic)
                    content = blog_data.get("content", "")
                except Exception as json_err:
                    logger.warning(f"Failed to parse Blog JSON: {json_err}. Using raw text.")
                    title = topic
                    content = response.choices[0].message.content

                # 2. Generate Image
                await context.bot.send_message(chat_id=chat_id, text=f"🎨 正在生成博客配图: {image_prompt}...")
                # Note: generate_image_native returns list[bytes]
                images = await asyncio.to_thread(generate_image_native, image_prompt)
                
                if not images:
                    raise Exception("Image generation returned no results.")
                
                image_bytes = images[0] # Usage first image
                
                # 3. Init WP Client
                # Priority: Task Payload > Memory > Env Vars/Defaults
                
                wp_user = task.get("username")
                wp_password = task.get("password")
                
                # Check Memory if not provided
                if not wp_user or not wp_password:
                    if memory_store:
                        # Simple keyword search
                        mem_creds = memory_store.search_memory("WordPress password", n_results=5)
                        # We hope to find a memory like "Username: Nick_Agent" or "Password: ..."
                        # For now, let's just log potential candidates. 
                        # Ideally, Qwen should have extracted them into the task if they were in context.
                        # If they are from DEEP memory (previous sessions), we might need to parse.
                        # Simple heuristic parsing
                        for mem in mem_creds:
                            text = mem.get("text", "")
                            # Look for "Username: ..." or "Password: ..."
                            if not wp_user and ("username" in text.lower() or "用户" in text):
                                if ":" in text:
                                    parts = text.split(":")
                                    if len(parts) > 1: wp_user = parts[1].strip()
                                elif " is " in text:
                                    wp_user = text.split(" is ")[1].strip()
                            
                            if not wp_password and ("password" in text.lower() or "密码" in text):
                                if ":" in text:
                                    parts = text.split(":")
                                    if len(parts) > 1: wp_password = parts[1].strip()
                                elif " is " in text:
                                    wp_password = text.split(" is ")[1].strip()
                            
                            if wp_user and wp_password: break

                # Fallback to defaults
                if not wp_user: wp_user = os.getenv("WP_USER", DEFAULT_WP_CONFIG['user'])
                if not wp_password: wp_password = os.getenv("WP_PASSWORD", DEFAULT_WP_CONFIG['password'])
                
                wp_url = os.getenv("WP_BASE_URL", DEFAULT_WP_CONFIG['url'])
                
                logger.info(f"WP Client Init with User: {wp_user}")
                wp = WordPressClient(wp_url, wp_user, wp_password)
                
                # 4. Upload Image
                filename = f"wp_gen_{int(datetime.now().timestamp())}.png"
                media_id = await asyncio.to_thread(wp.upload_media, image_bytes, filename)
                
                # 5. Create Post
                await context.bot.send_message(chat_id=chat_id, text=f"🚀 正在发布文章...")
                post_data = await asyncio.to_thread(wp.create_post, title, content, status='publish', featured_media_id=media_id)
                
                link = post_data.get('link')
                await context.bot.send_message(chat_id=chat_id, text=f"✅ 博客发布成功！\n🔗 {link}")
                execution_log.append(f"[System] Published blog post: {link}")
                
            except Exception as e:
                logger.error(f"WordPress Task Failed: {e}")
                await context.bot.send_message(chat_id=chat_id, text=f"❌ 博客发布失败: {e}")
                execution_log.append(f"[System] Blog post failed: {e}")

    # --- Phase 3: Gemini Final Response ---
    # Only if there are no tasks OR tasks were purely internal (like memory) and user expects a reply,
    # OR if we gathered info (Search) and need to summarize.
    
    # We always run Gemini to maintain conversation flow, passing the execution log.
    
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        
        # Append Execution Log to Memory Context or System Prompt
        final_system_context = memory_context + "\n\n[RECENT ACTIONS LOG]:\n" + "\n".join(execution_log)
        
        messages = [{"role": "system", "content": get_system_prompt(final_system_context)}]
        
        if 'history' not in context.user_data: context.user_data['history'] = []
        for msg in context.user_data['history'][-10:]: messages.append(msg)
            
        # Add Current User Message
        user_message_obj = {"role": "user", "content": user_input}
        
        # Add images if any
        all_images = []
        if image_b64: all_images.append(image_b64)
        if additional_images: all_images.extend(additional_images)
        
        if all_images:
            payload = [{"type": "text", "text": user_input}]
            for b64 in all_images:
                payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            user_message_obj = {"role": "user", "content": payload}
            
        messages.append(user_message_obj)
        
        # If tasks were executed, we might want to hint Gemini to just "Confirm" or "Summarize".
        if execution_log:
             messages.append({"role": "system", "content": f"The following actions have already been performed by the sub-agent:\n{json.dumps(execution_log)}\nPlease briefly summarize or confirm these actions to the user in a friendly tone. Do NOT repeat the actions as if you are going to do them, just confirm they are done."})

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_NAME, temperature=0.7, messages=messages
        )
        msg_content = response.choices[0].message.content
        
        # Filter out potential hallucinations of tool calls if Gemini tries to redo them
        # (Though our prompt instruction should prevent this, we can just send the text)
        
        if msg_content:
             await context.bot.send_message(chat_id=chat_id, text=msg_content)
             context.user_data['history'].append(user_message_obj)
             context.user_data['history'].append({"role": "assistant", "content": msg_content})

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
        print("Initializing Qwen Brain...")
        qwen_brain = QwenBrain() # Assumes Ollama is running
        print("Initializing Task Store...")
        task_store = TaskStore()
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