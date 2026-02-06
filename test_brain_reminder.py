
from qwen_brain import QwenBrain
import json

def test_brain():
    brain = QwenBrain()
    
    test_inputs = [
        "提醒我10秒后喝水",
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
