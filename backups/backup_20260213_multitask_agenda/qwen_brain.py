
import ollama
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QwenBrain:
    def __init__(self, model_name="deepseek-r1:14b"):
        self.model_name = model_name
        # Use explicit client with 127.0.0.1 to avoid localhost resolution issues on Windows
        self.client = ollama.Client(host='http://127.0.0.1:11434')

    def analyze_message(self, user_text: str, current_time: str = None):
        """
        Ask Qwen (now DeepSeek-R1) to analyze the message and return a LIST of tasks.
        """
        if not current_time:
             current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        system_prompt = f"""
        You are the 'Subconscious Mind' of an AI Agent.
        Current Reference Time: {current_time}
        
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
                    "type": "wordpress_post",
                    "topic": "The future of AI Agents",
                    "instructions": "Write a professional article...",
                    "image_prompt": "A futuristic robot working on a laptop",
                    "username": "User_Provided_Name",
                    "password": "User_Provided_Password"
                }},
                {{
                    "type": "reminder",
                    "content": "Check wallet",
                    "target_time": "YYYY-MM-DD HH:MM:SS",
                    "target_user": "me"
                }},
                {{
                    "type": "download",
                    "url": "https://youtube.com/..."
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
           - 'action': "draw" or "edit".
           - 'count': Number of images to generate (default 1). If user says "3 images", set count to 3.
           - 'prompt': Detailed positive prompt.
           - 'negative_prompt': Optional.
           
        4. **reminder**:
           - Schedule a reminder or message.
           - 'target_time': MUST be absolute YYYY-MM-DD HH:MM:SS. Calculate from "in 10 mins" etc.
           - 'target_user': "me", "dad", "mom", "son", etc. default "me".
           
        5. **download**:
           - If user provides a video URL to save/download.
        
        **CRITICAL INSTRUCTION**: 
        - Return ONLY valid JSON.
        - Sort tasks logically (e.g. search before reminding).
        - If no specific task is needed (just chat), return empty list: {{"tasks": []}}.
        """
        
        try:
            # 1. Broad Try/Except for Ollama connection
            try:
                response = self.client.chat(model=self.model_name, messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_text},
                ], format='json')
            except Exception as conn_err:
                logger.error(f"Ollama Connection Error: {conn_err}")
                raise conn_err # Re-raise to be caught by outer block or handled

            content = response['message']['content']
            
            # --- DeepSeek-R1 Specific Cleanup ---
            # Remove <think>...</think> blocks
            import re
            content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
            
            # Sanitize content: remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            logger.info(f"Raw DeepSeek Output (Cleaned): {content}") # Debug log
            
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Fallback: sometimes it adds extra text. Try to find the first { and last }
                start = content.find('{')
                end = content.rfind('}')
                if start != -1 and end != -1:
                    content = content[start:end+1]
                    parsed = json.loads(content)
                else:
                    logger.error("Failed to parse JSON even after cleanup.")
                    raise
            
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
            logger.error(f"Qwen analysis failed: {e}")
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
        Ask Qwen to select which memories are relevant to the user's text.
        Returns a subset of candidate_memories.
        """
        if not candidate_memories:
            return []
            
        candidates_str = "\n".join([f"{i}. {m}" for i, m in enumerate(candidate_memories)])
        
        system_prompt = f"""
        You are a relevance filter. 
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
             response = self.client.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': system_prompt}
            ], format='json')
             
             content = response['message']['content']
             # Cleanup
             import re
             content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
             if content.startswith("```json"): content = content[7:]
             if content.endswith("```"): content = content[:-3]
             
             logger.info(f"DeepSeek Filter Output (Indices): {content}")
             indices = json.loads(content.strip())
             
             if isinstance(indices, list):
                 selected = []
                 for i in indices:
                     if isinstance(i, int) and 0 <= i < len(candidate_memories):
                         selected.append(candidate_memories[i])
                 
                 if not selected:
                      logger.warning("DeepSeek Filter returned empty list.")
                 return selected
             return []
             
        except Exception as e:
            logger.error(f"Memory filtering failed: {e}")
            return candidate_memories # Fallback to all if filter fails

if __name__ == "__main__":
    brain = QwenBrain()
    print(brain.analyze_message("My birthday is on January 1st."))
