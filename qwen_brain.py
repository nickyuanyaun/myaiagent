
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
        Ask Qwen (now DeepSeek-R1) to analyze the message.
        """
        if not current_time:
             current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        system_prompt = f"""
        You are the 'Subconscious Mind' of an AI Agent.
        Current Reference Time: {current_time}
        
        Your Task: Analyze the User's input and extract structured data.
        
        1. **MEMORY**: Does the user mention a fact about themselves, a preference, or a piece of specific info that should be remembered?
           - If yes, set 'save_memory' to True and extract the fact into 'extracted_knowledge'.
           - Ignore trivial greetings or questions (e.g., "Hi", "What is the weather?").
        
        2. **REMINDER/MESSAGE**: does the user ask to remind OR tell someone something?
           - If yes, set 'reminder_needed' to True.
           - **Extract 'reminder_time'**: 
             - **ALWAYS convert to text YYYY-MM-DD HH:MM:SS timestamp**.
             - If user says "in 10 mins", calculate Current Time + 10 mins.
             - If user says "tomorrow morning", set to tomorrow 09:00:00.
             - If user says "at 5pm", set to today 17:00:00 (or tomorrow if 5pm passed).
           - Extract 'reminder_content' (what to remind/say).
           - Extract 'target_user' (who to remind). Values: "me" (default), "dad", "mom", "son", "nick", "fox".

        3. **DOWNLOAD**: Does the user ask to download a video or provide a video link with intent to save?
           - If yes, set 'download_needed' to True.
           - Extract 'download_url'.
           - Example 1: "Download this video: https://youtube.com/..." -> download_needed=True, download_url="https://youtube.com/..."
           - Example 2: "https://bilibili.com/video/..." (just a link) -> Check context, if ambiguous set download_needed=True (better safe than sorry).
        
        **CRITICAL INSTRUCTION**: 
        - Please think deeply before answering.
        - After thinking, output ONLY formatted JSON. 
        - Do NOT include markdown code blocks (```json). 
        - Do NOT output any text other than the JSON object.
        
        Output JSON Format:
        {{
            "save_memory": boolean,
            "extracted_knowledge": string or null,
            "reminder_needed": boolean,
            "reminder_time": string or null,
            "reminder_content": string or null,
            "target_user": string or null,
            "download_needed": boolean,
            "download_url": string or null
        }}
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
            
            return parsed
            
        except Exception as e:
            logger.error(f"Qwen analysis failed: {e}")
            # If ollama lib is missing or fails, we return defaults
            return {
                "save_memory": False,
                "extracted_knowledge": None,
                "reminder_needed": False,
                "reminder_time": None,
                "reminder_content": None,
                "target_user": None,
                "download_needed": False,
                "download_url": None
            }

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
