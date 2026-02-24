
import json
import logging
import re
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QwenBrain:
    def __init__(self, genai_client, plugin_manager=None, model_name="gemini-2.0-flash"):
        self.genai_client = genai_client
        self.plugin_manager = plugin_manager
        self.model_name = model_name

    def analyze_message(self, user_text: str, current_time: str = None):
        """
        Use Gemini to analyze the message and return a LIST of tasks.
        """
        if not current_time:
             current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        plugin_info = ""
        if self.plugin_manager:
            plugin_info = f"\n\n{self.plugin_manager.get_plugin_descriptions()}"
            
        system_prompt = f"""
        You are the 'Subconscious Mind' of an AI Agent.
        Current Reference Time: {current_time}
        {plugin_info}
        
        Your Task: Analyze the User's input and break it down into a list of executable tasks.
         Output JSON Format:
        {{
            "tasks": [
                {{
                    "type": "memory_save",
                    "content": "User likes blue"
                }},
                {{
                    "type": "web_search",
                    "query": "Bitcoin price",
                    "is_news": true
                }},
                {{
                    "type": "image_generation",
                    "prompt": "A cyberpunk cat",
                    "negative_prompt": "blurry, low quality",
                    "count": 1,
                    "action": "draw" 
                }},
                {{
                    "type": "translation",
                    "source_url": "https://example.com/article",
                    "target_language": "中文",
                    "instructions": "翻译这篇文章"
                }},
                {{
                    "type": "blog_media_save"
                }},
                {{
                    "type": "blog_write_draft",
                    "topic": "The future of AI Agents",
                    "instructions": "Write a professional article...",
                    "category": "科技"
                }},
                 {{
                    "type": "blog_publish_draft"
                }},
                {{
                    "type": "reminder",
                    "content": "Check wallet",
                    "target_time": "YYYY-MM-DD HH:MM:SS",
                    "target_user": "me",
                    "is_actionable": False
                }},
                {{
                    "type": "reminder",
                    "content": "每天9点给我推送10条科技新闻",
                    "cron_expression": "0 9 * * *",
                    "target_user": "me",
                    "is_actionable": True,
                    "action_prompt": "推送10条科技新闻"
                }},
                {{
                    "type": "download",
                    "url": "https://youtube.com/..."
                }},
                {{
                    "type": "file_write",
                    "filename": "notes.txt",
                    "instructions": "Write meeting notes about the new project..."
                }},
                {{
                    "type": "send_file",
                    "filename": "notes.txt"
                }},
                {{
                    "type": "file_read",
                    "filename": "notes.txt"
                }},
                {{
                    "type": "create_plugin",
                    "plugin_name": "get_crypto_price",
                    "description": "Fetches current cryptocurrency prices",
                    "code": "..."
                }},
                {{
                    "type": "use_plugin",
                    "plugin_name": "get_crypto_price",
                    "args": {{"symbol": "BTC"}}
                }}
            ]
        }}
        
        Supported Task Types & Rules:
        1. "memory_save": Use when user explicitly asks to remember something.
           - Extract facts about the user or preferences.
           - Ignore trivial greetings.
           
        2. "web_search": Use when user asks for information not in your knowledge or current events. 
           - If user asks for real-time info, news, weather, stock prices.
           - Set 'is_news': true for breaking news/prices.
           
        3. "image_generation": Use when user asks to generate/draw/create an image.
           - If user asks to DRAW or EDIT an image.
           - 'action': "draw", "edit", or "blend".
           - Use 'action': "blend" when user asks to "combine", "mix", "merge", or "compose" MULTIPLE images (e.g. "mix these").
           - 'count': Number of images to generate (default 1). If user says "3 images", set count to 3.
           - 'prompt': Detailed positive prompt.
           - 'negative_prompt': Optional.
           
        4. **reminder**:
           - Schedule a reminder or a scheduled automated action.
           - If it is a one-time reminder: use 'target_time', MUST be absolute YYYY-MM-DD HH:MM:SS. Calculate from "in 10 mins" etc.
           - If it is a repeating/recurring schedule (e.g. "every day at 9am", "每天9点"): Use 'cron_expression' instead of 'target_time'.
             - For 'cron_expression', use standard cron format (e.g. `0 9 * * *` for daily at 9am, `*/5 * * * *` for every 5 mins).
           - 'target_user': "me", "dad", "mom", "son", etc. default "me".
           - 'is_actionable': Set to True ONLY IF the user wants the bot to automatically DO something at that time (like "推送新闻", "搜股票", "画张猫"). If the user just wants a simple text reminder to themselves ("提醒我喝水"), set this to False.
           - 'action_prompt': If 'is_actionable' is True, provide the EXACT exact command you want the bot to run when the alarm triggers (e.g. "搜一下纳斯达克最新情况并总结"). If False, omit this field.
           
        5. **download**:
           - If user provides a video URL to save/download.

        6. **translation**:
           - Use when user asks to translate an external article or web page.
           - 'source_url': The URL of the article to translate. Use web_search first to fetch the content.
           - 'target_language': The target language (e.g. "中文", "English").
           - 'instructions': Any specific translation instructions.
           - IMPORTANT: If user wants to translate AND publish, create BOTH a web_search task (to fetch the article), a translation task, AND a blog_write_draft task with "source_content": "prior_tasks".

        7. **blog_write_draft**:
           - Use when user wants to WRITE or PREPARE a blog post.
           - 'topic': The blog topic.
           - 'instructions': Copy the user's FULL message content here verbatim.
           - 'category': Category name if user specifies one.
           - 'source_content': 
             - "user_provided_content": User provides full text.
             - "prior_tasks": ALWAYS use this if the blog is based on a translation or search you just outputted in this same JSON list. Do NOT invent new instructions!
             - "user_instructions": User gives instruction (e.g. "Write about X").
           - CRITICAL AND NEW: If user says "Write and Publish", you MUST generate a sequence:
             1. `blog_write_draft` (to generate text)
             2. `image_generation` (to generate 3 insert images for the blog: set 'count' to 3, unless user provided media)
             3. `blog_publish_draft` (to actually publish)

        8. **blog_publish_draft**:
           - Use when user wants to PUBLISH the currently drafted blog post.
           - CRITICAL RULE: This task CANNOT run alone if you haven't written the draft yet! 
           - If the user says "publish this text as a blog" or "发博客", you MUST precede this with a `blog_write_draft` task in the SAME list. NEVER output `blog_publish_draft` by itself unless the user explicitly says "publish the draft we just made".
           - No arguments needed.

        9. **blog_media_save**:
           - Use when user sends image(s) and explicitly says they are for a blog post, OR when user sends images AND asks to create a blog post using them in the same message.
           - Keywords: "博客用", "用于博客", "博客素材", "blog media", "for my blog", "博客图片", "发博客", "写博客"
           - Return: {{"type": "blog_media_save"}}
           - NOTE: This only marks intent. The photo handler saves the actual images.
           - MUST appear BEFORE blog_write_draft in the task list.

        10. **blog_media_clear**:
           - Use when user wants to clear/delete/reset all pending blog media images.
           - Keywords: "清空素材", "删除素材", "清空博客素材", "删除博客图片", "重置素材", "clear media", "reset blog media"
           - Return: {{"type": "blog_media_clear"}}
           
        11. **file_write**:
           - Use when user asks to create, save, or write a file (like .txt, .md, .py, .js, .json, etc.) directly to disk.
           - 'filename': The name of the file to save (e.g., "notes.md" or an absolute path like "Z:\\助理翻译\\notes.md"). It natively supports absolute paths and will create any missing folders automatically, so do NOT use `run_command` to move files.
           - 'instructions': Describe what content should be GENERATED. Leave EMPTY if you are just pipelining prior task data.
           - 'content': Set to "prior_tasks" if saving the output of a search or translation task. Otherwise, leave empty unless saving verbatim text.
           
        12. **send_file**:
           - Use when user asks you to send them a file from your disk.
           - 'filename': The name of the file to send.
           
        13. **file_read**:
           - Use when user asks you to read or check the contents of a local file on your disk.
           - 'filename': The name of the file to read.
           
        14. **run_command**:
           - Use when the user specifically asks you to execute a terminal, shell, or PowerShell command.
           - IMPORTANT FOR WINDOWS: Always use backslashes (`\\`) for folder paths, NOT forward slashes. ALWAYS wrap paths containing spaces or Chinese in double quotes (e.g. `"Z:\\我的文件夹\\file.txt"`). NEVER omit the backslash after a drive letter (use `"Z:\\"` NOT `"Z:"`).
           - 'command': The exact command string to execute.
           - 'timeout': (Optional) Maximum time in seconds to wait for the command to finish. Default is 30.

        15. **create_plugin**:
           - Use when the user explicitly asks you to WRITE A SCRIPT to ADD A NEW CAPABILITY/FEATURE to yourself.
           - 'plugin_name': Snake_case name of the plugin (e.g., "get_crypto_price").
           - 'description': Short description of what it does.
           - 'code': The raw Python code for the plugin.
             - MUST include a global dictionary `PLUGIN_METADATA = {{"description": "...", "args": {{"arg_name": "type"}}}}`.
             - MUST include a function `def execute(**kwargs):` that returns a string result.
             - E.g:
               ```python
               import requests
               PLUGIN_METADATA = {{"description": "Fetches crypto price", "args": {{"symbol": "str"}}}}
               def execute(symbol="BTC"): return "Price is 100k!"
               ```
               
        16. **use_plugin**:
           - Use when the user asks you to perform an action that matches one of your `AVAILABLE CUSTOM PLUGINS` listed above.
           - 'plugin_name': The exact name of the loaded plugin.
           - 'args': A JSON object containing the required arguments.
        
        **CRITICAL INSTRUCTION**: 
        - Return ONLY valid JSON.
        - Sort tasks logically: blog_media_save -> web_search -> translation -> blog_write_draft -> image_generation -> blog_publish_draft.
        - DATA PIPELINE: If user asks to translate/summarize and save/publish the result, NEVER invent instructions. Instead, ALWAYS set `"source_content": "prior_tasks"` in blog_write_draft and `"content": "prior_tasks"` in file_write to pipe the original data accurately without hallucination.
        - NEVER create an image_generation task when user says to use their uploaded images for the blog post.
        - If no specific task is needed (just chat), return empty list: {{"tasks": []}}.
        """
        
        try:
            from google.genai import types
            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=f"{system_prompt}\n\nUser message: {user_text}")])
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )

            content = response.text.strip()
            logger.info(f"Gemini Task Analysis Output: {content}")
            
            parsed = json.loads(content)
            
            # Ensure "tasks" key exists
            if "tasks" not in parsed:
                # Check if it returned a flat structure (legacy fallback)
                tasks = []
                if parsed.get("save_memory"):
                    tasks.append({"type": "memory_save", "content": parsed.get("extracted_knowledge")})
                if parsed.get("reminder_needed"):
                    tasks.append({
                        "type": "reminder", 
                        "content": parsed.get("reminder_content"),
                        "target_time": parsed.get("reminder_time"),
                        "target_user": parsed.get("target_user")
                    })
                if parsed.get("download_needed"):
                    tasks.append({"type": "download", "url": parsed.get("download_url")})
                
                parsed["tasks"] = tasks

            return parsed
            
        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            # Return empty task list on failure
            return {"tasks": []}

    def synthesize_context(self, retrieved_memories):
        """
        Optional: Summarize retrieved memories into a concise context block.
        """
        if not retrieved_memories:
            return ""
        
        return "\n".join([f"- {m}" for m in retrieved_memories])

    def filter_memories(self, user_text: str, candidate_memories: list) -> list:
        """
        Use Gemini to select which memories are relevant to the user's text.
        Returns a subset of candidate_memories.
        """
        if not candidate_memories:
            return []
            
        candidates_str = "\n".join([f"{i}. {m}" for i, m in enumerate(candidate_memories)])
        
        prompt = f"""You are a relevance filter. 
        User Message: "{user_text}"
        
        Candidate Memories:
        {candidates_str}
        
        Task: Identify which of the above memories are DIRECTLY useful for answering the user's message.
        - If a memory provides context for "it", "that", "he/she" in the user message, select it.
        - If a memory answers a question asked by the user, select it.
        - If the user is just saying hello or general chat, select NOTHING (return empty list).
        - If the memory is irrelevant to the current topic, do NOT select it.
        
        Output ONLY a JSON list of indices (integers) of the relevant memories. Example: [0, 2]. 
        If none are relevant, output [].
        """
        
        try:
            from google.genai import types
            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                )
            )
             
            content = response.text.strip()
            logger.info(f"Gemini Filter Output (Indices): {content}")
            indices = json.loads(content)
             
            if isinstance(indices, list):
                selected = []
                for i in indices:
                    if isinstance(i, int) and 0 <= i < len(candidate_memories):
                        selected.append(candidate_memories[i])
                 
                if not selected:
                     logger.warning("Gemini Filter returned empty list.")
                return selected
            return []
             
        except Exception as e:
            logger.error(f"Memory filtering failed: {e}")
            return candidate_memories  # Fallback to all if filter fails

if __name__ == "__main__":
    import os
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
    brain = QwenBrain(client)
    print(brain.analyze_message("My birthday is on January 1st."))
