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

from telegram import Update, InputMediaPhoto as TGInputMediaPhoto
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
from plugin_manager import PluginManager

# 1. Configuration & Constants
load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS_STR = os.environ.get("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS_STR.split(",") if uid.strip().isdigit()]
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
METUBE_URL = os.environ.get("METUBE_URL", "http://localhost:8081")
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash")
MAX_CONTEXT_MESSAGES = 20

# Initialize Google GenAI Client
genai_client = genai.Client(api_key=GOOGLE_API_KEY, http_options={'api_version': 'v1beta'})

# Global Store Instances (Initialized in main)
memory_store = None
qwen_brain = None
task_store = None
metube_client = None
plugin_manager = None
file_watcher = None
blog_media_store = None

# 2. Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Agent Error Logger (For Antigravity/Self-Diagnosis) ---
agent_error_logger = logging.getLogger("AgentErrors")
agent_error_logger.setLevel(logging.ERROR)
# Write errors to a dedicated file in the current directory
error_file_handler = logging.FileHandler("agent_errors.log", encoding='utf-8')
error_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
error_file_handler.setFormatter(error_formatter)
agent_error_logger.addHandler(error_file_handler)

def log_agent_error(error_msg: str, exception: Exception = None):
    """Helper to consistently log AI-driven execution errors."""
    import traceback
    full_err = error_msg
    if exception:
        full_err += f"\nException: {str(exception)}\nTraceback: {traceback.format_exc()}"
    agent_error_logger.error(full_err)
    return full_err

# --- Environment & API Keys ---

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

def generate_image_composition(prompt: str, images: list[bytes], negative_prompt: str | None = None, count: int = 1) -> list[bytes]:
    """
    Bio-inspired Image Composition (Image-to-Image / Blend) using Nano Banana Pro.
    Returns list of bytes.
    """
    full_prompt = f"Compose a new image based on these input images. {prompt}"
    if negative_prompt:
        full_prompt += f"\nNegative Prompt: {negative_prompt}"
    
    if count > 1:
        full_prompt += f"\n(Please generate {count} distinct variations)"
        
    logger.info(f"Composing Image via Nano Banana Pro with {len(images)} images and prompt: {full_prompt}")
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            from PIL import Image
            
            # Prepare contents: [img1, img2, ..., prompt]
            contents = []
            for img_bytes in images:
                contents.append(Image.open(io.BytesIO(img_bytes)))
            contents.append(full_prompt)
            
            config = types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )

            response = genai_client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=contents,
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
                raise Exception("No composed images found in response.")

        except Exception as e:
            error_msg = str(e)
            if ("503" in error_msg or "UNAVAILABLE" in error_msg) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Gemini Composition 503 | Retry {attempt+1}/{max_retries} in {delay}s... Error: {error_msg}")
                time.sleep(delay)
                continue
                
            logger.error(f"Generate Content Composition Error: {e}")
            raise e

def generate_image_edit(prompt: str, image_bytes: bytes, negative_prompt: str | None = None, count: int = 1) -> list[bytes]:
    """
    Bio-inspired Image Editing (Image-to-Image) using Nano Banana Pro.
    Returns list of bytes.
    """
    return generate_image_composition(prompt, [image_bytes], negative_prompt, count)


# 3. Global Instances
# In a robust app these would be in a Context object, but for a script globals are fine.
memory_store = None
qwen_brain = None
task_store = None
metube_client = None
file_watcher = None
blog_media_store = None
plugin_manager = None

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

from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
import os as os_lib

class ImageExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            attrs_dict = dict(attrs)
            src = attrs_dict.get('src')
            if src:
                # Ensure it's a full URL
                absolute_url = urljoin(self.base_url, src)
                self.images.append(absolute_url)

def download_scraped_images(chat_id, image_urls, limit=5, store=None):
    if not store: return 0
    downloaded_count = 0
    headers = {'User-Agent': 'Mozilla/5.0'}
    for img_url in image_urls[:limit*3]: # buffer in case some fail
        if downloaded_count >= limit: break
        try:
            img_resp = requests.get(img_url, headers=headers, timeout=10)
            if img_resp.status_code == 200 and 'image' in img_resp.headers.get('Content-Type', ''):
                logger.info(f"Downloaded scraped image: {img_url}")
                store.add_media(chat_id, img_resp.content)
                downloaded_count += 1
        except Exception as dl_e:
            logger.warning(f"Failed to download image {img_url}: {dl_e}")
    return downloaded_count

def fetch_url_content(url, extract_images=False):
    """Fetch and extract the main text content from a URL. Optionally returns tuple of (text, [img_urls])."""
    logger.info(f"Fetching full article content from: {url}")
    try:
        # 1. Try markdown.download API to bypass JS-checks/Cloudflare and get clean markdown
        try:
            api_url = f"https://markdown.download/?url={url}"
            md_resp = requests.get(api_url, timeout=30)
            if md_resp.status_code == 200 and len(md_resp.text) > 200 and "Please enable JS" not in md_resp.text and "Cloudflare" not in md_resp.text:
                text = md_resp.text
                image_urls = []
                if extract_images:
                    import re
                    # markdown format: ![alt](url)
                    img_markdown = re.findall(r'!\[.*?\]\((.*?)\)', text)
                    valid_urls = []
                    for img_url in img_markdown:
                        if img_url.startswith('http') and not img_url.lower().endswith('.svg'):
                            valid_urls.append(img_url)
                    # Remove duplicates
                    seen = set()
                    image_urls = [x for x in valid_urls if not (x in seen or seen.add(x))]
                
                if len(text) > 50000:
                    text = text[:50000] + "\n\n[... article truncated ...]"
                
                logger.info(f"Fetched {len(text)} chars from {url} via markdown.download")
                if extract_images:
                    return text, image_urls
                return text
        except Exception as md_e:
            logger.warning(f"markdown.download api failed: {md_e}")

        # 2. Fallback to direct fetch
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        html = response.text
        
        image_urls = []
        if extract_images:
            parser = ImageExtractor(url)
            parser.feed(html)
            valid_urls = []
            for img_url in parser.images:
                parsed = urlparse(img_url)
                ext = os_lib.path.splitext(parsed.path)[1].lower()
                # Accept basic image extensions, skip icons/SVGs
                if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    valid_urls.append(img_url)
            # Remove duplicates preserving order
            seen = set()
            image_urls = [x for x in valid_urls if not (x in seen or seen.add(x))]
        
        # Basic HTML to text extraction
        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
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
        
        # Limit to reasonable length (first ~50000 chars to stay within model context for parsing)
        if len(text) > 50000:
            text = text[:50000] + "\n\n[... article truncated ...]"
        
        logger.info(f"Fetched {len(text)} chars of article content from {url}")
        if extract_images:
            return text, image_urls
        return text
        
    except Exception as e:
        logger.error(f"Failed to fetch URL content: {e}")
        if extract_images: return f"Error fetching URL: {e}", []
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
                content = task['content']
                target_user = task.get('target_user', 'me')
                is_actionable = task.get('is_actionable', False)
                action_prompt = task.get('action_prompt', '')
                
                if is_actionable and action_prompt:
                    # Execute the workflow instead of just sending text
                    await context.bot.send_message(chat_id=chat_id, text=f"⚙️ 正在执行定时任务: {content}\n指令: {action_prompt}")
                    asyncio.create_task(process_agent_logic(action_prompt, chat_id, context))
                else:
                    if target_user and target_user.lower() != 'me':
                        other_chat_ids = [uid for uid in ALLOWED_USER_IDS if uid != chat_id]
                        if other_chat_ids:
                            target_chat_id = other_chat_ids[0]
                            # Optional: Identify sender
                            sender_name = "Nick" if chat_id == 8526935699 else "Fox" if chat_id == 1660122746 else str(chat_id)
                            
                            target_content = f"📩 收到来自 {sender_name} 的留言提醒:\n{content}"
                            await context.bot.send_message(chat_id=target_chat_id, text=target_content)
                            
                            # Notify sender success
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ 已成功将消息发送给另一位用户。")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 无法找到其他接收者来发送你的消息。")
                    else:
                        msg_content = f"⏰ 提醒: {content}"
                        await context.bot.send_message(chat_id=chat_id, text=msg_content)
                    
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
    """Handle incoming text messages."""
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USER_IDS:
        logger.warning(f"Unauthorized access attempt from user: {user_id}")
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # 1. Check for Pending Safety Confirmations
    if 'pending_action' in context.user_data and context.user_data['pending_action']:
        pending = context.user_data['pending_action']
        if user_text.strip().lower() in ["确认", "confirm"]:
            # User confirmed the dangerous action
            await context.bot.send_message(chat_id=chat_id, text=f"🔐 收到确认指令。正在恢复执行被暂停的操作...")
            
            # Execute the stored create_plugin logic explicitly here
            if pending.get("type") == "create_plugin":
                plugin_name = pending.get("plugin_name")
                code = pending.get("code")
                await context.bot.send_message(chat_id=chat_id, text=f"⚙️ 正在为您编写并挂载高危插件: `{plugin_name}.py`...")
                saved = await asyncio.to_thread(plugin_manager.write_plugin, plugin_name, code)
                if saved:
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 插件 `{plugin_name}` 已强行加载并就绪！")
                    log_entry = f"[System] Dangerous plugin {plugin_name} created after user confirmation."
                    if 'history' in context.user_data:
                        context.user_data['history'].append({"role": "system", "content": log_entry})
                else:
                    error_str = log_agent_error(f"Failed to write dangerous plugin '{plugin_name}' to disk.")
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ 插件 `{plugin_name}` 保存失败。")
            
            # Clear pending state
            context.user_data['pending_action'] = None
            return # Don't process this "确认" as a new AI prompt
            
        else:
            # User sent something else while an action is pending
            await context.bot.send_message(chat_id=chat_id, text=f"🛑 操作已取消。之前的插件挂载请求已被丢弃。")
            context.user_data['pending_action'] = None
            # Fall through to process the new text normally.

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

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Document (File) messages."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if user.id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized.")
        return

    document = update.message.document
    if not document: return
    
    file_name = document.file_name.lower()
    if not (file_name.endswith('.txt') or file_name.endswith('.md')):
        await context.bot.send_message(chat_id=chat_id, text="⚠️ 我目前只支持读取 .txt 和 .md 格式的文本文件。")
        return

    logger.info(f"DOCUMENT Received from {user.first_name}: {file_name}")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # Download the file to memory
        doc_file = await context.bot.get_file(document.file_id)
        file_buffer = io.BytesIO()
        await doc_file.download_to_memory(file_buffer)
        
        # Decode text content
        file_content = file_buffer.getvalue().decode('utf-8')
        
        caption = update.message.caption if update.message.caption else "Please read this file."
        user_input = f"[User sent a file named '{file_name}']\n\nContent:\n{file_content}\n\nUser Message: {caption}"
        
        # Acquire Lock (Enter Queue)
        if processing_lock.locked():
             await context.bot.send_message(chat_id=chat_id, text="⏳ 前一名用户正在处理中，请稍候...")

        async with processing_lock:
            await process_agent_logic(context, chat_id, user_input, image_b64=None, update=update)
            
    except Exception as e:
        logger.error(f"Document processing error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"文件处理失败: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Voice messages (Telegram native audio)."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if user.id not in ALLOWED_USER_IDS:
        await context.bot.send_message(chat_id=chat_id, text="Sorry, you are not authorized.")
        return

    voice = update.message.voice
    if not voice: return

    logger.info(f"VOICE Received from {user.first_name}. Duration: {voice.duration}s")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    
    try:
        # 1. Download the .ogg file to memory
        voice_file = await context.bot.get_file(voice.file_id)
        file_buffer = io.BytesIO()
        await voice_file.download_to_memory(file_buffer)
        audio_bytes = file_buffer.getvalue()
        
        # 2. Transcribe using Google GenAI (Native Audio parsing)
        await context.bot.send_message(chat_id=chat_id, text="🎙️ 正在识别语音...")
        
        # We use the standard configured model which supports multi-modal audio inputs
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        transcription_prompt = "Please accurately transcribe the following audio message into text. Only return the transcribed text, nothing else. If it's Chinese, transcribe in Chinese. If it's English, in English."
        
        response = await asyncio.to_thread(
            genai_client.models.generate_content,
            model=GEMINI_MODEL_NAME,
            contents=[audio_part, transcription_prompt],
        )
        user_input = response.text.strip()
        
        if not user_input:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ 抱歉，我没有听清您说什么。")
            return
            
        # Send back the transcription so the user knows what was heard
        await context.bot.send_message(chat_id=chat_id, text=f"🗣️ 您说：{user_input}")
        
        # 3. Pass to exactly the same logic flow as text
        if processing_lock.locked():
             await context.bot.send_message(chat_id=chat_id, text="⏳ 前一名用户正在处理中，请稍候...")

        async with processing_lock:
            await process_agent_logic(context, chat_id, user_input, image_b64=None, update=update)
            
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"语音处理失败: {e}")

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
    batch_context = {}  # Fix: Initialize batch context for multi-step data sharing
    
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

    # --- Inject pending blog media context for QwenBrain ---
    qwen_input = user_input
    if blog_media_store:
        pending_count = blog_media_store.get_media_count(chat_id)
        if pending_count > 0:
            qwen_input = (
                f"[SYSTEM CONTEXT: The user has {pending_count} blog media images saved and waiting to be used. "
                f"If user says to publish/post a blog, set use_uploaded_media=true and source_content='user_instructions'. "
                f"Do NOT create image_generation tasks.]\n\n"
                f"{user_input}"
            )
            logger.info(f"Injected blog media context: {pending_count} pending images")

    if qwen_brain:
        logger.info("Starting DeepSeek Analysis (Tasks)...")
        try:
            analysis = await asyncio.wait_for(
                asyncio.to_thread(qwen_brain.analyze_message, qwen_input, current_time_str),
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

            # --- Blog Media Clear ---
            elif task_type == "blog_media_clear":
                if blog_media_store:
                    pending_count = blog_media_store.get_media_count(chat_id)
                    if pending_count > 0:
                        cleared = blog_media_store.clear_pending(chat_id)
                        await context.bot.send_message(chat_id=chat_id, text=f"已清空 {cleared} 张暂存博客素材。")
                        execution_log.append(f"[System] Cleared {cleared} pending blog media images")
                    else:
                        await context.bot.send_message(chat_id=chat_id, text="当前没有暂存的博客素材。")
                        execution_log.append("[System] No pending blog media to clear")

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
                # Reminders store this data at the task root, not in the payload
                content = task.get("content")
                time_str = task.get("target_timestamp") 
                if not time_str: time_str = task.get("target_time")
                target_user = task.get("target_user")
                
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
                # Check if we already scraped original images into media store during this batch
                if blog_media_store and blog_media_store.get_media_count(chat_id) > 0:
                    logger.info("Skipping image_generation task because original scraped/uploaded images already exist.")
                    execution_log.append("[System] Skipped generative image task because original media was already extracted or provided.")
                    # Mark successful and skip generator
                    success = True
                    continue
                    
                prompt = task_payload.get("prompt")
                neg_prompt = task_payload.get("negative_prompt")
                count = task_payload.get("count", 1)
                action = task_payload.get("action", "draw")
                
                if prompt:
                    try:
                        generated_images = []
                        
                        # A. Composition / Blend
                        if action == "blend" or action == "compose":
                            # Gather all images
                            composition_images = []
                            if image_b64:
                                composition_images.append(base64.b64decode(image_b64))
                            if additional_images:
                                for b64 in additional_images:
                                    composition_images.append(base64.b64decode(b64))
                            
                            if not composition_images and context.user_data.get('last_image_bytes'):
                                # Fallback to last seen image if none in current message
                                composition_images.append(context.user_data['last_image_bytes'])
                                
                            if composition_images:
                                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                                generated_images = await asyncio.to_thread(
                                    generate_image_composition, prompt, composition_images, neg_prompt, count
                                )
                            else:
                                success = False
                                error_msg = "No images provided for composition."
                                await context.bot.send_message(chat_id=chat_id, text="⚠️ 需要提供图片才能进行融合/合成。")

                        # B. Edit
                        elif action == "edit":
                            # Use current image or last cached image
                            target_image_bytes = None
                            if image_b64:
                                target_image_bytes = base64.b64decode(image_b64)
                            elif context.user_data.get('last_image_bytes'):
                                target_image_bytes = context.user_data['last_image_bytes']
                                
                            if target_image_bytes:
                                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                                generated_images = await asyncio.to_thread(
                                    generate_image_edit, prompt, target_image_bytes, neg_prompt, count
                                )
                            else:
                                success = False
                                error_msg = "No image found to edit."
                                await context.bot.send_message(chat_id=chat_id, text="⚠️ 请上传图片或引用上一张图片进行编辑。")
                        
                        # C. Draw (Native)
                        else:
                            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                            generated_images = await asyncio.to_thread(
                                generate_image_native, prompt, neg_prompt, count
                            )

                        # Handle Results
                        if generated_images:
                            # 1. If we are in a Blog Draft flow, save to batch context
                            if "blog_draft" in batch_context:
                                if "blog_images" not in batch_context:
                                    batch_context["blog_images"] = []
                                batch_context["blog_images"].extend(generated_images)
                                await context.bot.send_message(chat_id=chat_id, text=f"🎨 配图已生成 ({len(generated_images)} 张)，准备发布...")
                                execution_log.append(f"[System] Generated {len(generated_images)} images for blog draft.")
                            
                            # 2. Otherwise/Also send to chat
                            else:
                                media_group = []
                                for img_bytes in generated_images:
                                    # Update cache for future edits
                                    context.user_data['last_image_bytes'] = img_bytes
                                    media_group.append(TGInputMediaPhoto(io.BytesIO(img_bytes)))
                                
                                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                                execution_log.append(f"[System] Generated/Edited {len(generated_images)} images.")
                                
                    except Exception as e:
                        success = False
                        error_msg = str(e)
                        logger.error(f"Image Gen Error: {e}")
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ 图片生成失败: {e}")
                else:
                    success = False
                    error_msg = "No prompt provided"

            # --- Blog Write Draft ---
            elif task_type == "blog_write_draft":
                topic = task_payload.get("topic")
                instructions = task_payload.get("instructions", "")
                category = task_payload.get("category", "Uncategorized")
                source_content = task_payload.get("source_content", "")
                
                await context.bot.send_message(chat_id=chat_id, text=f"✍️ 正在撰写博客草稿: {topic}...")
                
                # Use Qwen to write the content
                try:
                    # --- CRITICAL FIX: Proactively fetch Translation/Search context from execution_log ---
                    prior_content = ""
                    for entry in execution_log:
                        if entry.startswith("[Translation Result]"):
                            prior_content += entry.replace("[Translation Result]", "").strip() + "\n\n"
                    if not prior_content:
                        for entry in execution_log:
                            if "Search Results" in entry:
                                prior_content += entry + "\n\n"
                    # Also include file read contents if we didn't find search or translation
                    if not prior_content:
                        for entry in execution_log:
                            if "[System] Read file" in entry:
                                prior_content += entry + "\n\n"
                    
                    # Force prior_tasks mode if we have pipelined data
                    if prior_content and source_content != "user_provided_content":
                        source_content = "prior_tasks"

                    # Construct prompt for the writer
                    writer_prompt = f"撰写一篇高质量的WordPress博客文章，主题: {topic}.\n\n"
                    writer_prompt += "重要: 默认使用中文撰写，除非用户在指令中明确指定了其他语言。\n\n"
                    if source_content == "user_provided_content":
                        writer_prompt += f"需要排版的内容:\n{instructions}\n\n任务: 严格将以上内容排版为博客文章，保留原文核心意思。仅返回有效JSON: {{'title': '标题', 'content': '正文内容'}}"
                    elif source_content == "prior_tasks" and prior_content:
                         writer_prompt = f"这是一项极端严格的排版任务。绝对不要自己无中生有编造博客或者缩减任何文字！\n这是一篇由前置工具（智能翻译或网络抓取）获取的准确文章全文:\n\n{prior_content[:50000]}\n\n"
                         writer_prompt += f"附加指令: {instructions}\n\n指令优先级极高: 你现在的身份是一个『无情的打字复读机』。你只需要为以上文本想一个【吸睛标题】(title)，并【原封不动】地返回全文字字句句作为正文(content)！绝对不允许总结、缩减、或者重写任何一段文字！必须保留原文所有的字数和细节。仅返回有效JSON: {{'title': '吸睛标题', 'content': '全文一字不落的照抄'}}"
                    else:
                        writer_prompt += f"写作指令:\n{instructions}\n\n任务: 撰写一篇有创意、有深度的文章。仅返回有效JSON: {{'title': '标题', 'content': '正文内容'}}"

                    # Call Qwen (simplified for now, using memory_store Qwen instance if available or just raw text gen)
                    # Actually we have qwen_brain. let's use a simple generation method if exposed, or fallback to direct client.
                    # QwenBrain doesn't expose raw chat easily. Let's add a helper or use the genai_client for text too? 
                    # Let's use genai_client (Gemini) for writing as it's better at long form, or Qwen via ollama directly.
                    # Let's use Gemini for the writing part since it replaces the 'Nano Banana Pro' persona well.
                    
                    # 1. Grab images to provide vision context
                    vision_parts = []
                    if blog_media_store and blog_media_store.get_media_count(chat_id) > 0:
                        stored_media = blog_media_store.get_media(chat_id)
                        for item in stored_media:
                            if 'data' in item:
                                vision_parts.append(
                                    types.Part.from_bytes(
                                        data=item['data'],
                                        mime_type="image/jpeg"
                                    )
                                )
                    
                    # Also include images directly from this request if not already captured
                    if image_b64:
                        vision_parts.append(types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type="image/jpeg"))
                    if additional_images:
                        for b64_img in additional_images:
                            vision_parts.append(types.Part.from_bytes(data=base64.b64decode(b64_img), mime_type="image/jpeg"))

                    # 2. Append recent chat context so the writer knows what the user actually wants
                    history_context = ""
                    if 'history' in context.user_data:
                        history_context = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in context.user_data['history'][-10:]])
                    
                    if history_context:
                        writer_prompt += f"\n\n--- 最近对话上下文 ---\n{history_context}\n----------------------\n请确保你的文章内容紧密贴合用户的最新要求和提供的上下文（尤其是紧密结合提供的图片内容进行分析）。"

                    # 3. Combine text and vision parts
                    contents_list = [writer_prompt]
                    if vision_parts:
                        contents_list.extend(vision_parts)
                        logger.info(f"Injecting {len(vision_parts)} images into blog_write_draft context")

                    draft_resp = genai_client.models.generate_content(
                        model=GEMINI_MODEL_NAME, # Use the selected multimodal model
                        contents=contents_list,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    
                    if draft_resp.text:
                         draft_data = json.loads(draft_resp.text)
                         title = draft_data.get("title", topic)
                         content_body = draft_data.get("content", "")
                         
                         batch_context["blog_draft"] = {
                             "title": title,
                             "content": content_body,
                             "category": category,
                             "status": "draft"
                         }
                         execution_log.append(f"[System] Blog draft written: {title}")
                         await context.bot.send_message(chat_id=chat_id, text=f"✅ 草稿已完成: {title}")
                    else:
                        raise Exception("Empty response from Writer AI")

                except Exception as e:
                    success = False
                    error_msg = f"Draft writing failed: {e}"
                    logger.error(error_msg)

            # --- Blog Publish Draft ---
            elif task_type == "blog_publish_draft":
                draft = batch_context.get("blog_draft")
                if not draft:
                    success = False
                    error_msg = "No blog draft found in context to publish."
                    await context.bot.send_message(chat_id=chat_id, text="❌ 无法发布: 未找到草稿。")
                else:
                    await context.bot.send_message(chat_id=chat_id, text=f"🚀 正在发布: {draft['title']}...")
                    try:
                        # Collect Images
                        # 1. Generated in this batch
                        batch_images = batch_context.get("blog_images", []) # list of bytes
                        
                        # 2. Uploaded/Saved in Store (if requested)
                        # We need to know if we SHOULD use them. 
                        # Ideally `blog_write_draft` or `qwen` told us. 
                        # Let's check `blog_media_store` count.
                        media_store_images = []
                        if blog_media_store and blog_media_store.get_media_count(chat_id) > 0:
                             # If we have them, let's use them.
                             media_store_images = blog_media_store.get_media(chat_id)
                        
                        # Client call — read credentials from env vars
                        wp_user = os.getenv("WP_USER")
                        wp_password = os.getenv("WP_PASSWORD")
                        wp_url = os.getenv("WP_BASE_URL", "")
                        client = WordPressClient(wp_url, wp_user, wp_password)
                        
                        # Extract captions from stored media for AI formatting context 
                        captions = [item.get("caption", "") for item in media_store_images] if media_store_images else None
                        
                        await context.bot.send_message(chat_id=chat_id, text="📐 正在使用AI排版博客内容...")
                        
                        post_url = client.create_post_unified(
                            title=draft.get('title', 'AI Update'),
                            content=draft.get('content', ''),
                            category_names=[draft.get('category')] if draft.get('category') else None,
                            generated_images=batch_images,
                            stored_media_images=media_store_images,
                            genai_client=genai_client,
                            stored_media_captions=captions
                        )
                        
                        if post_url:
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ 发布成功! \n{post_url}")
                            execution_log.append(f"[System] Published blog: {post_url}")
                            execution_log.append(
                                "[System] IMPORTANT: The blog post has been SUCCESSFULLY PUBLISHED to WordPress. "
                                "DO NOT regenerate, rewrite, or output blog content in your response. "
                                "DO NOT output DRAW_ADVANCED or image generation prompts. "
                                "Simply confirm the publication was successful and mention the link. "
                                "Keep your response brief and conversational."
                            )
                            # Cleanup media store
                            if blog_media_store and media_store_images:
                                blog_media_store.mark_published(chat_id)
                                blog_media_store.delete_published(chat_id)
                        else:
                            raise Exception("WordPress client returned None")

                    except Exception as e:
                        success = False
                        error_msg = f"Publish failed: {e}"
                        logger.error(error_msg)
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ 发布失败: {e}")

            # --- WordPress Post (Legacy/Unified) ---
            elif task_type == "wordpress_post":
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
                            media_group = [TGInputMediaPhoto(io.BytesIO(img_data), caption=f"✨ {prompt[:50]}..." if i == 0 else None) for i, img_data in enumerate(images)]
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
                    image_urls = []
                    if source_url:
                        await context.bot.send_message(chat_id=chat_id, text=f"📄 正在获取原文内容和图片: {source_url}")
                        fetched_res = await asyncio.to_thread(fetch_url_content, source_url, extract_images=True)
                        if isinstance(fetched_res, tuple):
                            fetched, image_urls = fetched_res
                        else:
                            fetched = fetched_res
                        
                        if fetched and not fetched.startswith("Error"):
                            source_material = fetched
                            logger.info(f"Successfully fetched full article: {len(source_material)} chars")
                    
                    # PRIORITY 2: If URL fetch failed, try to find URL from search results
                    if not source_material:
                        # Check if there's a URL in the execution log from web_search
                        for entry in execution_log:
                            if "Search Results" in entry:
                                # Extract URLs from search results
                                import re as re_mod
                                urls_found = re_mod.findall(r'Link:\s*(https?://\S+)', entry)
                                if urls_found:
                                    await context.bot.send_message(chat_id=chat_id, text=f"📄 从搜索结果获取原文和图片...")
                                    fetched_res = await asyncio.to_thread(fetch_url_content, urls_found[0], extract_images=True)
                                    if isinstance(fetched_res, tuple):
                                        fetched, image_urls = fetched_res
                                    else:
                                        fetched = fetched_res
                                        
                                    if fetched and not fetched.startswith("Error"):
                                        source_material = fetched
                                        break
                                        
                    # Scrape and Download Translation Context Images
                    if image_urls and blog_media_store:
                        downloaded_count = await asyncio.to_thread(download_scraped_images, chat_id, image_urls, limit=5, store=blog_media_store)
                        if downloaded_count > 0:
                            execution_log.append(f"[System] Scraped and saved {downloaded_count} original images from source URL")
                            await context.bot.send_message(chat_id=chat_id, text=f"✅ 成功提取了 {downloaded_count} 张原网页内插图！将自动配入博客。")
                    
                    
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
                            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=8192)
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

            # --- File Write ---
            elif task_type == "file_write":
                file_path = task_payload.get("file_path")
                content = task_payload.get("content", "")
                instructions = task_payload.get("instructions", "")
                
                # 0. Core File Protection
                core_files = ["main.py", "qwen_brain.py", "plugin_manager.py"]
                if any(file_path.endswith(core) for core in core_files):
                    error_str = log_agent_error(f"Security Alert: Attempted to overwrite core system file '{file_path}'. Operation blocked.")
                    execution_log.append(f"[System Error] {error_str}")
                    success = False
                    error_msg = f"Cannot modify core file {file_path}. This is strictly prohibited to prevent the agent from breaking itself."
                    await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {error_msg}")
                    continue

                if file_path:
                    try:
                        # 1. Generate content if instructions are provided
                        if instructions and content != "prior_tasks":
                            await context.bot.send_message(chat_id=chat_id, text=f"✍️ 正在生成文件内容: {file_path}...")
                            
                            history_context = ""
                            if 'history' in context.user_data:
                                history_context = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in context.user_data['history'][-10:]])
                                
                            write_prompt = (
                                f"Please write the complete content for a file named {file_path}.\n\n"
                                f"Instructions: {instructions}\n\n"
                                f"--- Recent Conversation Context ---\n{history_context}\n"
                                f"User's newest message: {user_input}\n"
                                f"-----------------------------------\n\n"
                                f"IMPORTANT: Generate the content based on the instructions while aligning perfectly with the provided conversation context (such as specific themes or characters discussed). "
                                f"Return ONLY the exact, complete file content. "
                                f"Do not include markdown code block wrappers (like ```md) around the entire output."
                            )
                            
                            write_resp = await asyncio.to_thread(
                                genai_client.models.generate_content,
                                model=GEMINI_MODEL_NAME,
                                contents=[write_prompt]
                            )
                            content = write_resp.text
                            
                            # Clean up potential markdown wrappers
                            if content.startswith("```"):
                                import re
                                content = re.sub(r'^```[a-zA-Z0-9]*\n', '', content)
                                content = re.sub(r'\n```$', '', content)
                                content = content.strip()
                                
                        elif content == "prior_tasks":
                            # Pull from translation or search
                            extracted_content = ""
                            for entry in execution_log:
                                if entry.startswith("[Translation Result]"):
                                    extracted_content += entry.replace("[Translation Result]", "", 1).strip() + "\n\n"
                                elif "Search Results" in entry:
                                    extracted_content += entry + "\n\n"
                                elif "[System] Read file" in entry:
                                    extracted_content += entry + "\n\n"
                                    
                            if not extracted_content:
                                content = "Error: No prior translation, file read, or search tasks found to write."
                            else:
                                content = extracted_content.strip()

                        # Handle absolute paths natively
                        if os.path.isabs(filename):
                            file_path = filename
                            os.makedirs(os.path.dirname(file_path), exist_ok=True)
                            safe_display_name = filename
                        else:
                            workspace_dir = "workspace"
                            os.makedirs(workspace_dir, exist_ok=True)
                            safe_name = os.path.basename(filename)
                            file_path = os.path.join(workspace_dir, safe_name)
                            safe_display_name = safe_name
                        
                        await context.bot.send_message(chat_id=chat_id, text=f"📝 正在写入文件: {safe_display_name}...")
                        
                        # Async file write
                        def write_file():
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                        await asyncio.to_thread(write_file)
                        
                        execution_log.append(f"[System] Wrote {len(content)} chars to {safe_display_name}.")
                        await context.bot.send_message(chat_id=chat_id, text=f"✅ 文件已保存: {safe_display_name} (共 {len(content)} 字符)")
                    except Exception as e:
                        logger.error(f"File Write Failed: {e}")
                        success = False
                        error_msg = str(e)
                        execution_log.append(f"[System] Failed to write file {filename}: {e}")
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ 文件写入失败: {e}")
                else:
                    success = False
                    error_msg = "No filename provided for file_write."

            # --- Send File ---
            elif task_type == "send_file":
                filename = task_payload.get("filename")
                if filename:
                    try:
                        workspace_dir = "workspace"
                        safe_filename = os.path.basename(filename)
                        file_path = os.path.join(workspace_dir, safe_filename)
                        
                        if os.path.exists(file_path):
                            await context.bot.send_message(chat_id=chat_id, text=f"📤 正在发送文件: {safe_filename}...")
                            with open(file_path, 'rb') as f:
                                await context.bot.send_document(chat_id=chat_id, document=f, filename=safe_filename)
                            execution_log.append(f"[System] Sent file {safe_filename} to user.")
                        else:
                            success = False
                            error_msg = f"File {safe_filename} not found in workspace."
                            execution_log.append(f"[System] Tried to send {safe_filename} but it doesn't exist.")
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 找不到文件: {safe_filename}")
                    except Exception as e:
                        logger.error(f"Send File Failed: {e}")
                        success = False
                        error_msg = str(e)
                        execution_log.append(f"[System] Failed to send file {filename}: {e}")
                else:
                    success = False
                    error_msg = "No filename provided for send_file."

            # --- File Read ---
            elif task_type == "file_read":
                filename = task_payload.get("filename")
                if filename:
                    try:
                        workspace_dir = "workspace"
                        safe_filename = os.path.basename(filename)
                        file_path = os.path.join(workspace_dir, safe_filename)
                        
                        if os.path.exists(file_path):
                            await context.bot.send_message(chat_id=chat_id, text=f"📖 正在读取文件: {safe_filename}...")
                            
                            def read_file():
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    return f.read()
                            
                            content = await asyncio.to_thread(read_file)
                            
                            # Truncate if too long to avoid token explosion, though Gemini can handle a lot (upgraded to 50000 for full articles)
                            preview = content[:50000] + ("\n...(truncated)" if len(content) > 50000 else "")
                            
                            execution_log.append(f"[System] Read file {safe_filename}. Content:\n{preview}")
                            logger.info(f"Read {len(content)} chars from {safe_filename}")
                        else:
                            success = False
                            error_msg = f"File {safe_filename} not found in workspace."
                            execution_log.append(f"[System] Tried to read {safe_filename} but it doesn't exist.")
                            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 找不到文件: {safe_filename}")
                    except Exception as e:
                        logger.error(f"Read File Failed: {e}")
                        success = False
                        error_msg = str(e)
                        execution_log.append(f"[System] Failed to read file {filename}: {e}")
                else:
                    success = False
                    error_msg = "No filename provided for file_read."

            # --- Run Command ---
            elif task_type == "run_command":
                command = task_payload.get("command")
                timeout_seconds = int(task_payload.get("timeout", 30))
                
                if command:
                    await context.bot.send_message(chat_id=chat_id, text=f"⚡ 正在执行命令:\n`{command}`", parse_mode='MarkdownV2')
                    try:
                        # Ensure we execute in the workspace directory for safety/context, or root if preferred. 
                        # We'll execute in the current working directory but log it.
                        logger.info(f"Executing command: {command} with timeout {timeout_seconds}s")
                        
                        process = await asyncio.create_subprocess_shell(
                            command,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        
                        try:
                            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
                            
                            def safe_decode(b_data):
                                try:
                                    return b_data.decode('utf-8').strip()
                                except UnicodeDecodeError:
                                    return b_data.decode('gbk', errors='replace').strip()
                                    
                            stdout_str = safe_decode(stdout)
                            stderr_str = safe_decode(stderr)
                            exit_code = process.returncode
                            
                            output_msg = f"**执行完成 (Exit: {exit_code})**\n"
                            if stdout_str:
                                output_msg += f"**STDOUT**:\n```text\n{stdout_str[:2000]}\n```\n"
                            if stderr_str:
                                output_msg += f"**STDERR**:\n```text\n{stderr_str[:1000]}\n```\n"
                                
                            if len(stdout_str) > 2000 or len(stderr_str) > 1000:
                                output_msg += "\n*(Output truncated)*"
                                
                            if not stdout_str and not stderr_str:
                                output_msg += "*(No output)*"
                                
                            execution_log.append(f"[System] Command executed: `{command}`. Exit Code: {exit_code}\nStdout: {stdout_str[:1000]}\nStderr: {stderr_str[:500]}")
                            await context.bot.send_message(chat_id=chat_id, text=output_msg, parse_mode='Markdown')
                            
                        except asyncio.TimeoutError:
                            process.kill()
                            await process.communicate() # collect garbage
                            error_msg = f"Command timed out after {timeout_seconds} seconds."
                            logger.error(error_msg)
                            execution_log.append(f"[System] Command `{command}` timed out.")
                            await context.bot.send_message(chat_id=chat_id, text=f"❌ 命令执行超时 ({timeout_seconds}s): `{command}`", parse_mode='Markdown')
                            success = False
                            
                    except Exception as e:
                        logger.error(f"Command Execution Failed: {e}")
                        success = False
                        error_msg = str(e)
                        execution_log.append(f"[System] Failed to execute `{command}`: {e}")
                else:
                    success = False
                    error_msg = "No command string provided for run_command."

            # --- Dynamic Plugins ---
            elif task_type == "create_plugin":
                plugin_name = task_payload.get("plugin_name", "")
                code = task_payload.get("code", "")
                dependencies = task_payload.get("dependencies", [])
                
                if plugin_name and code and plugin_manager:
                    # 1. Dependency Auto-Installation
                    if dependencies and isinstance(dependencies, list):
                        dep_list = " ".join(dependencies)
                        await context.bot.send_message(chat_id=chat_id, text=f"📦 正在安装插件依赖库: `{dep_list}`...")
                        try:
                            # Use current python executable to pip install
                            pip_proc = await asyncio.create_subprocess_exec(
                                sys.executable, "-m", "pip", "install", *dependencies,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            stdout, stderr = await pip_proc.communicate()
                            if pip_proc.returncode == 0:
                                await context.bot.send_message(chat_id=chat_id, text=f"✅ 依赖库安装完成。")
                                logger.info(f"Successfully installed dependencies for {plugin_name}: {dependencies}")
                            else:
                                logger.error(f"Pip install failed: {stderr.decode()}")
                                await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 依赖库安装可能存在问题: {stderr.decode()[:200]}")
                        except Exception as dep_e:
                            logger.error(f"Dependency install error: {dep_e}")

                    # 2. Safety Check (Heuristic)
                    dangerous_keywords = ["rm -rf", "shutil.rmtree('/')", "os.remove", "format C:", "del /s"]
                    if any(kw in code for kw in dangerous_keywords):
                        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ **安全警告**: 发现该插件包含潜在高危操作代码 (如删除文件)。\n为防止意外，系统已暂停执行。请您仔细检查您的指令。\n\n如确认无误允许挂载，请直接回复：“**确认**” 或 “**confirm**”。")
                        logger.warning(f"DANGEROUS CODE DETECTED in plugin {plugin_name} (Paused for confirmation): {code[:200]}")
                        
                        # Store the pending action in context
                        context.user_data['pending_action'] = {
                            "type": "create_plugin",
                            "plugin_name": plugin_name,
                            "code": code,
                            "dependencies": dependencies
                        }
                        
                        # Stop processing further tasks in this batch
                        success = False
                        error_msg = f"Plugin '{plugin_name}' execution paused for user safety confirmation."
                        execution_log.append(f"[System] {error_msg}")
                        break # Exit the task loop

                    # 3. Normal Plugin Writing and Execution
                    await context.bot.send_message(chat_id=chat_id, text=f"⚙️ 正在为您编写并挂载新插件: `{plugin_name}.py`...")
                    saved = await asyncio.to_thread(plugin_manager.write_plugin, plugin_name, code)
                    if saved:
                        await context.bot.send_message(chat_id=chat_id, text=f"✅ 插件 `{plugin_name}` 已成功加载，我可以立即使用它了！")
                        execution_log.append(f"[System] Plugin {plugin_name} created with dependencies {dependencies} and hot-reloaded.")
                    else:
                        error_str = log_agent_error(f"Failed to write plugin '{plugin_name}' to disk.")
                        execution_log.append(f"[System Error] {error_str}")
                        success = False
                        error_msg = "Failed to write plugin code to disk."
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ 插件 `{plugin_name}` 保存失败。")
                else:
                    error_str = log_agent_error("Missing plugin name, code, or PluginManager not initialized for create_plugin task.")
                    execution_log.append(f"[System Error] {error_str}")
                    success = False
                    error_msg = "Missing plugin name, code, or PluginManager not initialized."

            elif task_type == "use_plugin":
                plugin_name = task_payload.get("plugin_name", "")
                args = task_payload.get("args", {})
                
                if plugin_name and plugin_manager:
                    await context.bot.send_message(chat_id=chat_id, text=f"⚡ 正在执行插件 `{plugin_name}`...")
                    logger.info(f"Executing plugin {plugin_name} with args {args}")
                    try:
                        result = await asyncio.to_thread(plugin_manager.execute_plugin, plugin_name, **args)
                        
                        # Loop the result back into the execution log
                        execution_log.append(f"[Plugin Result ({plugin_name})]\n{result}")
                        logger.info(f"Plugin result: {str(result)[:500]}")
                        
                        # Send raw result briefly
                        result_str = str(result)
                        if len(result_str) > 1000:
                            await context.bot.send_message(chat_id=chat_id, text=f"🧩 插件执行完毕，输出较长已折叠，正在总结...")
                        else:
                            await context.bot.send_message(chat_id=chat_id, text=f"🧩 插件返回结果:\n`{result_str}`", parse_mode='Markdown')
                            
                    except Exception as e:
                        success = False
                        error_msg = str(e)
                        logger.error(f"Plugin execution failed: {e}")
                        execution_log.append(f"[System] Plugin {plugin_name} execution failed: {e}")
                        await context.bot.send_message(chat_id=chat_id, text=f"❌ 插件执行失败: {e}")
                else:
                    success = False
                    error_msg = "Missing plugin name or PluginManager not initialized."

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
                    user_verbatim_content = ""  # NEW: For user-provided full blog text
                    
                    if source_content == "user_provided_content":
                        # User provided the ACTUAL COMPLETE blog text — use verbatim
                        user_verbatim_content = instructions
                        logger.info(f"Using user_provided_content for verbatim blog ({len(user_verbatim_content)} chars)")
                    
                    # ALWAYS forcefully check execution_log for prior translation or search tasks first
                    # This prevents hallucinations if Qwen forgot to set source_content="prior_tasks"
                    for entry in execution_log:
                        if entry.startswith("[Translation Result]"):
                            prior_content += entry.replace("[Translation Result]", "").strip() + "\n\n"
                            
                    if not prior_content and source_content == "prior_tasks":
                        for entry in execution_log:
                            if "Search Results" in entry:
                                prior_content += entry + "\n\n"
                    
                    if prior_content:
                        logger.info(f"Using prior task content for WordPress post ({len(prior_content)} chars)")
                        image_prompt = f"Professional blog illustration related to: {prior_content[:200]}"
                    elif source_content == "prior_tasks":
                        logger.warning("source_content='prior_tasks' but no prior content found in execution_log. Falling back to generation.")
                        
                    
                    elif source_content == "user_instructions":
                        # User provided their own writing instructions (e.g. "写一篇关于AI摄影的博客")
                        user_writing_instructions = instructions
                        logger.info(f"Using user_instructions for blog content: {user_writing_instructions[:100]}...")
                    
                    # --- PRIORITY 0: Detect user-provided FULL blog content from conversation history ---
                    # If Qwen didn't set user_provided_content but user actually provided full text,
                    # detect it here by looking for long formatted content in recent messages.
                    if not user_verbatim_content and not prior_content:
                        history = context.user_data.get('history', [])
                        for msg in reversed(history[-10:]):
                            if msg.get('role') == 'user':
                                user_text = msg.get('content', '')
                                # Detect full blog content: >200 chars, has heading markers or structured sections
                                has_headings = any(marker in user_text for marker in ['# ', '## ', '### ', '**'])
                                has_sections = user_text.count('\n') > 5
                                is_long = len(user_text) > 200
                                has_blog_keyword = any(kw in user_text for kw in ['博客', '发博客', '写博客', 'blog', '博文', '发布', '发博'])
                                
                                if is_long and has_headings and has_sections:
                                    # This looks like full blog content, not just instructions
                                    # Extract the actual blog text (strip any meta-instruction prefix)
                                    content_text = user_text
                                    # If the message has a separator like ---, use content after it
                                    if '---' in content_text:
                                        parts = content_text.split('---', 1)
                                        if len(parts) > 1 and len(parts[1].strip()) > 100:
                                            content_text = parts[1].strip()
                                    
                                    user_verbatim_content = content_text
                                    logger.info(f"[PRIORITY 0] Auto-detected user's full blog content ({len(content_text)} chars)")
                                    break
                    
                    # --- PRIORITY 1: Find user's ORIGINAL blog instructions from conversation history ---
                    # Only used when NO verbatim content was found.
                    if not user_verbatim_content and (not user_writing_instructions or len(user_writing_instructions) < 20):
                        history = context.user_data.get('history', [])
                        for msg in reversed(history[-10:]):
                            if msg.get('role') == 'user':
                                user_text = msg.get('content', '')
                                # User's previous detailed instructions (>50 chars, mentions blog keywords)
                                if len(user_text) > 50 and any(kw in user_text for kw in ['博客', '发博客', '写博客', 'blog', '博文', '发布']):
                                    user_writing_instructions = user_text
                                    logger.info(f"[PRIORITY 1] Found user's original blog instructions ({len(user_text)} chars)")
                                    break
                    
                    # --- PRIORITY 2: Fall back to assistant's prior blog draft ---
                    # Only used when NO user instructions were found at all.
                    if not user_verbatim_content and not user_writing_instructions and not prior_content:
                        history = context.user_data.get('history', [])
                        for msg in reversed(history[-6:]):
                            if msg.get('role') == 'assistant':
                                content_text = msg.get('content', '')
                                if len(content_text) > 200 and ('###' in content_text or '**' in content_text or '博客' in content_text):
                                    # Clean out any DRAW_ADVANCED prompts and meta-text
                                    clean_lines = []
                                    skip_draw = False
                                    for line in content_text.split('\n'):
                                        if 'DRAW_ADVANCED' in line or 'NEGATIVE:' in line:
                                            skip_draw = True
                                            continue
                                        if skip_draw and line.strip() == '':
                                            skip_draw = False
                                            continue
                                        if not skip_draw:
                                            clean_lines.append(line)
                                    cleaned = '\n'.join(clean_lines).strip()
                                    if len(cleaned) > 150:
                                        prior_content = cleaned
                                        logger.info(f"[PRIORITY 2] Using assistant blog draft as fallback ({len(prior_content)} chars, cleaned from {len(content_text)})")
                                        break
                    
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
                    
                    # AUTO-DETECT: If there are pending blog media, use them even if Qwen didn't set use_uploaded_media
                    effective_use_uploaded = use_uploaded_media
                    if not effective_use_uploaded and blog_media_store:
                        auto_pending = blog_media_store.get_pending_media(chat_id)
                        if auto_pending:
                            effective_use_uploaded = True
                            logger.info(f"Auto-detected {len(auto_pending)} pending blog media. Overriding use_uploaded_media to True.")
                            # Also reduce AI image count since user has their own
                            image_count = min(image_count, 1)
                    
                    if effective_use_uploaded and blog_media_store:
                        pending_media = blog_media_store.get_pending_media(chat_id)
                        if pending_media:
                            await context.bot.send_message(chat_id=chat_id, text=f"[Upload] 正在上传 {len(pending_media)} 张用户素材到博客...")
                            for idx, media_entry in enumerate(pending_media):
                                try:
                                    img_bytes = blog_media_store.get_media_bytes(media_entry["id"])
                                    if img_bytes:
                                        fname = media_entry.get("original_filename", f"user_media_{idx}.jpg")
                                        upload_result = await asyncio.to_thread(wp.upload_media, img_bytes, fname)
                                        img_url = upload_result.get("source_url", "") if isinstance(upload_result, dict) else ""
                                        upload_id = upload_result["id"] if isinstance(upload_result, dict) else upload_result
                                        if not img_url:
                                            # Fallback: fetch URL from API
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
                                upload_result = await asyncio.to_thread(wp.upload_media, img_data, filename)
                                img_url = upload_result.get("source_url", "") if isinstance(upload_result, dict) else ""
                                upload_id = upload_result["id"] if isinstance(upload_result, dict) else upload_result
                                if not img_url:
                                    # Fallback: fetch URL from API
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
                        # Graceful fallback: Proceed without images if the uploads/generations failed.
                        logger.warning("No images available or generation failed. Proceeding with a text-only blog post.")
                        await context.bot.send_message(chat_id=chat_id, text="⚠️ 图片处理失败或超时，将发布纯文本博客。")

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
                    
                    if user_verbatim_content:
                        # === USER PROVIDED FULL BLOG TEXT — FORMAT ONLY, NO REWRITING ===
                        blog_system_prompt = (
                            "You are a WordPress Gutenberg block formatter. "
                            "Output exclusively in JSON format: {\"title\": \"...\", \"content\": \"Gutenberg block content\", \"tags\": [\"tag1\", \"tag2\", ...]}. "
                            "ABSOLUTE RULES — VIOLATION IS UNACCEPTABLE:\n"
                            "1. You MUST use the user's provided text VERBATIM. Do NOT rewrite, rephrase, summarize, expand, or change ANY wording.\n"
                            "2. Your ONLY job is to convert the Markdown/plain text into WordPress Gutenberg block format.\n"
                            "3. Extract the title from the first heading (# line). If no # heading, use the first line as title.\n"
                            "4. Convert each paragraph to <!-- wp:paragraph --><p>text</p><!-- /wp:paragraph -->\n"
                            "5. Convert headings to <!-- wp:heading --><h2>text</h2><!-- /wp:heading --> (or h3, h4 as appropriate)\n"
                            "6. Convert numbered/bulleted lists to <!-- wp:list --> blocks\n"
                            "7. Preserve ALL original text, emoji, formatting (bold with <strong>, etc.)\n"
                            "8. Insert provided images at logical section breaks using Gutenberg image blocks.\n"
                            "9. Generate 5-8 SEO tags based on the content.\n"
                            "10. REPEAT: DO NOT ADD, REMOVE, OR MODIFY ANY OF THE USER'S WORDS."
                        )
                        blog_user_prompt = (
                            f"Convert the following blog text to Gutenberg blocks. DO NOT change any wording:\n\n"
                            f"{user_verbatim_content}\n\n"
                            f"Available Images (Insert at logical section breaks):\n{urls_list_str}\n\n"
                            f"REMINDER: Preserve the user's original text word-for-word. Only convert format to Gutenberg blocks."
                        )
                    elif prior_content:
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
                            f"Refer to the uploaded photos naturally in the text (e.g. '如图所示', '这张照片中', etc.)."
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
                    
                    # Robust JSON parsing with fallback
                    raw_text = blog_response.text
                    try:
                        blog_data = json.loads(raw_text)
                    except json.JSONDecodeError:
                        # Try extracting JSON from markdown code blocks
                        logger.warning("Direct JSON parse failed, trying code block extraction...")
                        import re
                        json_match = re.search(r'```(?:json)?\s*\n?(\{.*?\})\s*```', raw_text, re.DOTALL)
                        if json_match:
                            blog_data = json.loads(json_match.group(1))
                        else:
                            # Last resort: find first { to last }
                            start = raw_text.find('{')
                            end = raw_text.rfind('}')
                            if start != -1 and end != -1:
                                blog_data = json.loads(raw_text[start:end+1])
                            else:
                                raise Exception(f"Blog content generation returned invalid JSON: {raw_text[:200]}")
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
                    
                    post_id = post_data.get('id')
                    # Use ?p=ID shortlink — slug-based permalinks break with Chinese/emoji titles
                    site_base = wp_url.split('/wp-json')[0] if '/wp-json' in wp_url else wp_url
                    link = f"{site_base}/?p={post_id}" if post_id else post_data.get('link', 'N/A')
                    tag_info = f"，标签: {', '.join(auto_tags[:5])}" if auto_tags else ""
                    cat_info = f"，分类: {user_category}" if user_category else ""
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ 博客发布成功（包含 {len(image_urls)} 张图片{tag_info}{cat_info}）！\n🔗 {link}")
                    execution_log.append(f"[System] Published multimedia blog post with {len(image_urls)} images: {link}")
                    execution_log.append(
                        "[System] IMPORTANT: The blog post has been SUCCESSFULLY PUBLISHED to WordPress. "
                        "DO NOT regenerate, rewrite, or output blog content in your response. "
                        "DO NOT output DRAW_ADVANCED or image generation prompts. "
                        "Simply confirm the publication was successful and mention the link. "
                        "Keep your response brief and conversational."
                    )

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
        print("Initializing Plugin Manager...")
        plugin_manager = PluginManager()
        
        print("Initializing Memory Store...")
        memory_store = MemoryStore()
        
        print("Initializing Qwen Brain...")
        qwen_brain = QwenBrain(genai_client, plugin_manager=plugin_manager)  # Uses Gemini API
        
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
        # Global Error Handler
        async def global_error_handler(update, context):
            # Log the error and avoid crash
            logger.error(f"Exception while handling an update: {context.error}")

        application.add_error_handler(global_error_handler)

        # Explicit Handlers
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        
        print("Agent is running with Explicit Vision, Voice, and File Handlers! (Ctrl+C to stop)")
        application.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("\nBot stopped by user. Goodbye!")
    except Exception as e:
        logger.fatal(f"Critical Error in Main Loop: {e}", exc_info=True)
        print(f"CRITICAL ERROR: {e}")
        # Consider saving a panic log file
        with open("panic.log", "w") as f:
            f.write(str(e))
        sys.exit(1)