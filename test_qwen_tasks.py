
import asyncio
from qwen_brain import QwenBrain
import logging
import json
import os
from google import genai
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

async def test_tasks():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    brain = QwenBrain(client)
    
    scenarios = [
        "Draw a cyberpunk cat and post it to my blog with title 'Cyber Cat'",
        "Remind me to buy milk in 10 mins and download this video: https://youtube.com/watch?v=123",
        "My name is Nick.",
        "Write a blog post about AI Agents.",
        "Hello, how are you?"
    ]
    
    for text in scenarios:
        print(f"\n--- Testing: {text} ---")
        try:
            res = await asyncio.to_thread(brain.analyze_message, text)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_tasks())
