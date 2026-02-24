
from qwen_brain import QwenBrain
import json
import os
from google import genai
from dotenv import load_dotenv

def test_brain():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    brain = QwenBrain(client)
    
    test_inputs = [
        "提醒我10秒后喝水",
        "每天早上8点给我看天气",
        "Remind me to drink water in 10 seconds",
        "5分钟后叫我",
        "Tell Dad to call me in 1 hour"
    ]
    
    print("Testing Qwen Brain Reminder Logic...")
    for text in test_inputs:
        print(f"\n--- Input: {text} ---")
        try:
            result = brain.analyze_message(text)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_brain()
