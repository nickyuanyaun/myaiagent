from qwen_brain import QwenBrain
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_download_intent():
    brain = QwenBrain()
    
    test_inputs = [
        "Download this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "Please save this video https://bilibili.com/video/BV123456",
        "What is the weather today?",
        "Remind me to download the file later"
    ]
    
    print("Testing Qwen Brain Download Logic...")
    for text in test_inputs:
        print(f"\n--- Input: {text} ---")
        try:
            result = brain.analyze_message(text)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            if "Download" in text or "save" in text:
                 if result.get('download_needed'):
                     print("✅ Correctly identified download intent.")
                 else:
                     print("❌ Failed to identify download intent.")
            else:
                 if not result.get('download_needed'):
                     print("✅ Correctly ignored non-download intent.")
                 else:
                     print("❌ False positive on download intent.")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    test_download_intent()
