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

def generate_image_native(prompt: str) -> bytes:
    """
    Generates an image using Google GenAI SDK (Nano Banana Pro / gemini-3-pro-image-preview).
    """
    logger.info(f"Generating Image via Nano Banana Pro for: {prompt}")
    try:
        # Create chat session with Nano Banana Pro
        chat = genai_client.chats.create(
            model="gemini-3-pro-image-preview",
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                tools=[{"google_search": {}}]
            )
        )
        
        response = chat.send_message(prompt)
        
        # DEBUG: Log the full response details
        logger.info(f"Raw Response: {response}")
        try:
             # Attempt to inspect candidates if available (structure varies by SDK version)
             if hasattr(response, 'candidates'):
                  for i, cand in enumerate(response.candidates):
                       logger.info(f"Candidate {i} Finish Reason: {cand.finish_reason}")
                       logger.info(f"Candidate {i} Content: {cand.content}")
        except Exception as e_debug:
             logger.warning(f"Failed to inspect candidates: {e_debug}")

        found_bytes = None
        
        if response.parts:
            for part in response.parts:
                if part.text:
                    logger.info(f"Image Gen Text Response: {part.text}")
                
                # Check for executable code (sometimes it returns code to generate image?)
                if hasattr(part, 'executable_code') and part.executable_code:
                     logger.info(f"Executable Code found: {part.executable_code}")

                # Try to extract image
                # Priority 1: Direct bytes from inline_data (Most robust)
                if hasattr(part, 'inline_data') and part.inline_data:
                    logger.info("Found inline_data blob.")
                    if part.inline_data.data:
                         found_bytes = part.inline_data.data
                         logger.info(f"Image bytes extracted directly: {len(found_bytes)} bytes. MIME: {getattr(part.inline_data, 'mime_type', 'unknown')}")
                         break
                
                # Priority 2: Use SDK helper if available (Fallback)
                try: 
                    img = part.as_image()
                    if img and not found_bytes:
                        # Save to memory buffer
                        buf = io.BytesIO()
                        # Some custom Image classes don't support format arg, try without if it fails? 
                        # Or just skip if we didn't get bytes above.
                        # Given the error seen ("unexpected keyword argument 'format'"), 
                        # this helper likely returns a simple wrapper that only supports save(path).
                        # We will skip it if we haven't found bytes yet, or try a different approach if needed.
                        logger.warning("part.as_image() returned object, but inline_data was preferred. If you see this, inline_data failed?")
                except Exception as e_parse:
                     pass

        if found_bytes:
            return found_bytes
        else:
            raise Exception("No image found in response parts. Check logs for details.")

    except Exception as e:
        logger.error(f"Nano Banana Pro Error: {e}")
        raise e

def generate_image_edit(prompt: str, image_bytes: bytes) -> bytes:
    """
    Bio-inspired Image Editing (Image-to-Image) using Nano Banana Pro.
    """
    logger.info(f"Editing Image via Nano Banana Pro with prompt: {prompt}")
    try:
        from PIL import Image
        
        # Load the input image
        input_img = Image.open(io.BytesIO(image_bytes))
        
        # Create chat session
        chat = genai_client.chats.create(
            model="gemini-3-pro-image-preview",
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                tools=[{"google_search": {}}]
            )
        )
        
        # Send Prompt + Image
        # Note: 'google.genai' SDK usually accepts PIL Image objects directly in the message list
        response = chat.send_message([prompt, input_img])
        
        # Extract Result (Reuse same logic as native gen)
        found_bytes = None
        if response.parts:
            for part in response.parts:
                if part.text:
                    logger.info(f"Edit Text Response: {part.text}")
                
                # Priority 1: Inline Data
                if hasattr(part, 'inline_data') and part.inline_data:
                    if part.inline_data.data:
                         found_bytes = part.inline_data.data
                         break
                
                # Priority 2: as_image()
                try: 
                    img = part.as_image()
                    if img and not found_bytes:
                        buf = io.BytesIO()
                        # Try to save as PNG (Edit might return different format?)
                        try: img.save(buf, format="PNG")
                        except: img.save(buf) # Fallback
                        found_bytes = buf.getvalue()
                        break
                except: pass

        if found_bytes:
            return found_bytes
        else:
            raise Exception("No edited image found in response.")

    except Exception as e:
        logger.error(f"Nano Banana Pro Edit Error: {e}")
        raise e

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

3. **SEARCH**: If the user asks about weather, news, stocks, or real-time info:
   - For general queries, respond with: SEARCH: <English Keywords>
   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>

   - For **Breaking News / Price / Today's** info, respond with: SEARCH_NEWS: <English Keywords>
   
4. **IMAGE GENERATION / EDITING (Nano Banana Pro)**:
   - If user asks to DRAW/GENERATE an image:
     - Respond: `DRAW: <Detailed English Prompt>`
   - If user asks to EDIT/MODIFY the LAST uploaded image:
     - Respond: `EDIT: <Detailed English Prompt>`
   - **CRITICAL**: Do NOT return JSON. ONLY return the plain string starting with `DRAW:` or `EDIT:`.
   - Example 1: "画一只猫" -> `DRAW: A cute cat sitting on a windowsill`
   - Example 2: "把刚才的图改成赛博朋克风格" -> `EDIT: Make the scene cyberpunk style, neon lights`

5. If general chat, respond in Chinese.
6. If the retrieved memory is relevant, use it to personalize the answer.

7. **Reminders**: Your 'Subconscious Mind' (Qwen) handles reminders automatically. 
   - If you see a [SYSTEM ALERT] about a reminder being set, CONFIRM it to the user. 
   - If the user asks for a reminder, assume your Subconscious Mind handles it, and just say "好的，我会提醒你" (Okay, I will remind you). DO NOT say you cannot do it.

8. Do not make up facts. Do not output internal thought processes or JSON unless explicitly asked for code.
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

async def schedule_reminder(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, delay_seconds: int):
    """Schedule a job to send a reminder."""
    # Use the job queue
    try:
        if context.job_queue:
            # Pass text as 'data' and chat_id as context (chat_id kwarg sets job.chat_id)
            context.job_queue.run_once(reminder_callback, delay_seconds, chat_id=chat_id, data=text)
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
    """Shared Logic"""
    if additional_images is None: additional_images = []
    
    # --- Phase 1: Qwen Analysis (Parallel / Background) ---
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2. Retrieve Memory
    retrieved_docs = []
    if memory_store:
        retrieved_docs = memory_store.search_memory(user_input, user_id=update.effective_user.id, n_results=3)
    memory_context = ""
    if qwen_brain:
        memory_context = qwen_brain.synthesize_context(retrieved_docs)

    # 3. Analyze Message with Qwen
    analysis = {}
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if qwen_brain:
        logger.info("Starting DeepSeek Analysis (Timeout: 60s)...")
        try:
            # Run with timeout to prevent blocking the bot if Ollama hangs
            analysis = await asyncio.wait_for(
                asyncio.to_thread(qwen_brain.analyze_message, user_input, current_time_str),
                timeout=60.0
            )
            logger.info(f"Qwen Analysis: {analysis}")
        except asyncio.TimeoutError:
            logger.error("❌ Qwen Analysis Timed Out (Ollama too slow or stuck). Skipping.")
        except Exception as qwen_err:
            logger.error(f"Qwen Error: {qwen_err}")

    # Process Analysis result
    if analysis.get('save_memory') and analysis.get('extracted_knowledge'):
        knowledge = analysis['extracted_knowledge']
        if memory_store:
            await asyncio.to_thread(memory_store.add_memory, knowledge, {"source": "user_chat", "user_id": update.effective_user.id})

    # Reminder Logic
    is_reminder = analysis.get('reminder_needed')
    has_target = analysis.get('target_user') and analysis.get('target_user') != 'me'
    
    if (is_reminder or has_target) and analysis.get('reminder_content'):
        delay = 10
        content = analysis['reminder_content']
        time_str = str(analysis.get('reminder_time', '')).strip()
        
        # Debug feedback
        logger.info(f"Reminder detected: {content} at {time_str}")
        
        # Absolute Time Parsing
        parsed_delay = None
        try:
            target_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            diff = (target_dt - datetime.now()).total_seconds()
            parsed_delay = max(5, int(diff))
        except ValueError: pass

        if parsed_delay is not None:
            delay = parsed_delay
        else:
             # Relative Fallback (Enhanced)
             time_str_lower = time_str.lower()
             if "minute" in time_str_lower or "min" in time_str_lower or "分" in time_str_lower:
                  nums = re.findall(r'\d+', time_str_lower)
                  if nums: delay = int(nums[0]) * 60
             elif "second" in time_str_lower or "sec" in time_str_lower or "秒" in time_str_lower:
                  nums = re.findall(r'\d+', time_str_lower)
                  if nums: delay = int(nums[0])
        
        # Routing
        raw_target = analysis.get('target_user')
        target_role = raw_target if raw_target else 'me'
        target_chat_id = chat_id 
        
        FAMILY_DIRECTORY = {
             "dad": 1660122746, "father": 1660122746, "baba": 1660122746, "fox": 1660122746,
             "mom": 8295191474, "mother": 8295191474, "mama": 8295191474,
             "son": 8526935699, "nick": 8526935699, "me": chat_id
        }
        
        if target_role.lower() in FAMILY_DIRECTORY:
            chat_target = FAMILY_DIRECTORY[target_role.lower()]
            # Only switch if not 'me'
            if target_role.lower() != 'me':
                target_chat_id = chat_target
        elif target_role.lower() != 'me':
             await context.bot.send_message(chat_id=chat_id, text=f"⚠ 未知目标 '{target_role}'。将发给您自己。")
        
        final_content = content
        if target_chat_id != chat_id:
            sender_name = update.effective_user.first_name
            final_content = f"{sender_name} 让我告诉你：{content}"
            
        await schedule_reminder(context, target_chat_id, final_content, delay)
        
        # Explicit confirmation for debugging
        await context.bot.send_message(chat_id=chat_id, text=f"🧠 Qwen 已设定提醒: {delay}秒后 - {content}")

        if target_chat_id == chat_id:
             memory_context += f"\n[SYSTEM ALERT]: A reminder has been set for {delay} seconds from now about '{content}'."
        else:
             memory_context += f"\n[SYSTEM ALERT]: Message sent to {target_role} ({target_chat_id})."

    # --- Phase 2: Gemini Generation ---
    try:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        
        messages = [{"role": "system", "content": get_system_prompt(memory_context)}]
        
        if 'history' not in context.user_data: context.user_data['history'] = []
        for msg in context.user_data['history'][-10:]: messages.append(msg)
            
        # Add Current User Message
        # Combine single image_b64 and additional_images into one list
        all_images = []
        if image_b64: all_images.append(image_b64)
        if additional_images: all_images.extend(additional_images)
        
        if all_images:
            payload = [{"type": "text", "text": user_input}]
            for b64 in all_images:
                payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            messages.append({"role": "user", "content": payload})
        else:
            messages.append({"role": "user", "content": user_input})
        
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        response = await client.chat.completions.create(
            model=OPENAI_MODEL_NAME, temperature=0.6, messages=messages
        )
        ai_message = response.choices[0].message.content.strip()

        # --- Self-Correction Logic for "Agentic" JSON Output ---
        # Sometimes the model hallucinates a JSON tool format. We catch it here.
        draw_prompt = None
        if ai_message.strip().startswith('{') and "action" in ai_message:
            try:
                # Try to parse the hallucinated JSON
                data = json.loads(ai_message)
                if data.get("action") in ["dalle.text2im", "generate_image", "draw"]:
                    # Extract prompt from action_input
                    action_input = data.get("action_input")
                    if isinstance(action_input, str):
                        try:
                            # Sometimes action_input is a nested JSON string
                            input_data = json.loads(action_input)
                            draw_prompt = input_data.get("prompt")
                        except:
                            # Or just a string
                            draw_prompt = action_input
                    elif isinstance(action_input, dict):
                        draw_prompt = action_input.get("prompt")
                    
                    if draw_prompt:
                        logger.info(f"Intercepted JSON Tool Call. Extracted prompt: {draw_prompt}")
                        ai_message = f"DRAW: {draw_prompt}" # Rewrite message to trigger standard logic
            except Exception as e:
                logger.warning(f"Failed to parse JSON output: {e}")

        # Handle SEARCH and DRAW
        if ai_message.startswith("SEARCH:") or ai_message.startswith("SEARCH_NEWS:"):
            is_news = ai_message.startswith("SEARCH_NEWS:")
            query = ai_message.replace("SEARCH_NEWS:" if is_news else "SEARCH:", "").strip()
            
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            search_res = search_web(query, 'd' if is_news else None)
            
            messages.append({"role": "assistant", "content": ai_message})
            messages.append({"role": "user", "content": f"Verified Search Results:\n{search_res}\n\nAnswer the original question."})
            
            response_final = await client.chat.completions.create(model=OPENAI_MODEL_NAME, temperature=0.7, messages=messages)
            final_answer = response_final.choices[0].message.content
            await context.bot.send_message(chat_id=chat_id, text=final_answer)
            context.user_data['history'].append({"role": "user", "content": user_input})
            context.user_data['history'].append({"role": "assistant", "content": final_answer})

        if ai_message.startswith("DRAW:") or ai_message.startswith("EDIT:"):
             is_edit = ai_message.startswith("EDIT:")
             action_name = "EDIT" if is_edit else "DRAW"
             
             # Handle Image Generation / Editing
             prompt = ai_message.replace(f"{action_name}:", "").strip()
             
             # Check for cached image if Editing
             input_image_bytes = None
             if is_edit:
                 input_image_bytes = context.user_data.get('last_image_bytes')
                 if not input_image_bytes:
                     await context.bot.send_message(chat_id=chat_id, text="⚠️ 无法编辑：我没有找到您最近上传的图片。请先发一张图给我！")
                     return

             await context.bot.send_message(chat_id=chat_id, text=f"🎨 正在调用 Nano Banana Pro 为您{'修改' if is_edit else '生成'}: {prompt} ...")
             await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
             
             try:
                 # Run in thread to not block
                 if is_edit:
                     # For edit, we pass the image bytes
                     img_bytes = await asyncio.to_thread(generate_image_edit, prompt, input_image_bytes)
                 else:
                     img_bytes = await asyncio.to_thread(generate_image_native, prompt)
                 
                 await context.bot.send_photo(chat_id=chat_id, photo=img_bytes, caption=f"✨ Generated by Nano Banana Pro ({action_name})\nPrompt: {prompt}")
                 
                 # Add system confirmation to history so bot knows it succeeded
                 context.user_data['history'].append({"role": "user", "content": user_input})
                 context.user_data['history'].append({"role": "assistant", "content": ai_message}) 
                 context.user_data['history'].append({"role": "system", "content": f"[SYSTEM]: Image successfully {action_name.lower()}ed and sent."})

             except Exception as img_err:
                 logger.error(f"Image {action_name} Failed: {img_err}")
                 await context.bot.send_message(chat_id=chat_id, text=f"❌ {action_name}失败: {img_err}")

        else:
            await context.bot.send_message(chat_id=chat_id, text=ai_message)
            context.user_data['history'].append({"role": "user", "content": user_input})
            context.user_data['history'].append({"role": "assistant", "content": ai_message})

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
    except Exception as e:
        print(f"Failed to init components: {e}")
        sys.exit(1)

    # Build App
    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
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