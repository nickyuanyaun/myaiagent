
from qwen_brain import QwenBrain
import json

def test():
    brain = QwenBrain()
    
    # The exact query from user
    url = "https://youtu.be/MuWTmEIne1g?si=Taod7kx4Dv9jIMKE"
    text = f"{url} 这个视频讲了什么？"
    
    print(f"--- Testing Query: {text} ---")
    result = brain.analyze_message(text)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Check if correct
    if result.get("summarize_needed") and not result.get("download_needed"):
        print("✅ SUCCESS: Detected basic SUMMARIZE (Download=False)")
    elif result.get("summarize_needed") and result.get("download_needed"):
         print("⚠ WARNING: Detected SUMMARIZE but also DOWNLOAD=True (Might trigger unwanted download)")
    else:
        print("❌ FAILURE: Intent missed")

if __name__ == "__main__":
    test()
