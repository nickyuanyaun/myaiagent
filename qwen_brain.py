
import ollama
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class QwenBrain:
    def __init__(self, model_name="qwen2.5:14b"):
        self.model_name = model_name
        # Use explicit client with 127.0.0.1 to avoid localhost resolution issues on Windows
        self.client = ollama.Client(host='http://127.0.0.1:11434')

    def analyze_message(self, user_text: str, current_time: str = None):
        """
        Ask Qwen to analyze the message for:
        1. Knowledge to save (long-term memory).
        2. Reminders to schedule.
        Returns a dictionary.
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
             - If relative (e.g., "in 10 mins"), keep as is.
             - If absolute (e.g., "at 5pm", "tomorrow morning"), **CALCULATE the specific YYYY-MM-DD HH:MM:SS timestamp** based on the Reference Time. 
             - Example: If Ref is 2025-01-01 10:00:00 and user says "at 2pm", output "2025-01-01 14:00:00".
           - Extract 'reminder_content' (what to remind/say).
           - Extract 'target_user' (who to remind). Values: "me" (default), "dad", "mom", "son", "nick", "fox".
           - Example 1: "Remind me to drink water" -> target_user="me"
           - Example 2: "Tell Dad I'm coming home" -> target_user="dad"
        
        Output JSON ONLY. Format:
        {{
            "save_memory": boolean,
            "extracted_knowledge": string or null,
            "reminder_needed": boolean,
            "reminder_time": string or null,
            "reminder_content": string or null,
            "target_user": string or null
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
            
            # Sanitize content: remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            logger.info(f"Raw Qwen Output: {content}") # Debug log
            
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
                "target_user": None
            }

    def synthesize_context(self, retrieved_memories):
        """
        Optional: Summarize retrieved memories into a concise context block.
        """
        if not retrieved_memories:
            return ""
        
        return "\n".join([f"- {m}" for m in retrieved_memories])

if __name__ == "__main__":
    brain = QwenBrain()
    print(brain.analyze_message("My birthday is on January 1st."))
