import logging
from qwen_brain import QwenBrain
import json

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_qwen_tasks():
    print("Initializing QwenBrain...")
    brain = QwenBrain()
    
    # Complex prompt
    user_input = "Search for the latest price of Bitcoin, then generate a cyberpunk style image of a bitcoin coin, and finally remind me to check my wallet in 5 minutes."
    
    print(f"\nTesting Input: {user_input}")
    print("-" * 50)
    
    try:
        result = brain.analyze_message(user_input)
        print("Result JSON:")
        print(json.dumps(result, indent=2))
        
        tasks = result.get("tasks", [])
        print(f"\nExtracted {len(tasks)} tasks.")
        
        # Validation
        has_search = any(t['type'] == 'web_search' for t in tasks)
        has_image = any(t['type'] == 'image_generation' for t in tasks)
        has_reminder = any(t['type'] == 'reminder' for t in tasks)
        
        if has_search and has_image and has_reminder:
            print("✅ SUCCESS: All 3 task types detected.")
        else:
            print("❌ FAILURE: Missing task types.")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_qwen_tasks()
