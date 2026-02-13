import unittest
from qwen_brain import QwenBrain

class TestIntent(unittest.TestCase):
    def setUp(self):
        self.brain = QwenBrain()

    def test_summary_intent_chinese(self):
        # User query from screenshot
        url = "https://youtu.be/MuWTmEIne1g?si=Taod7kx4Dv9jIMKE"
        user_text = f"{url} 这个视频讲了什么？"
        
        print(f"Testing: {user_text}")
        result = self.brain.analyze_message(user_text)
        print(f"Result: {result}")
        
        # We expect download_needed to range, but specifically we want to know if it triggered SUMMARIZE
        # Wait, the current logic in main.py looks for `SUMMARIZE_VIDEO:` string in the output of `analyze_message`?
        # NO. `analyze_message` returns a JSON object.
        # Let's check `main.py` again. `main.py` calls `brain.analyze_message`? 
        # Actually `main.py` line 487 calls `qwen_brain.analyze_message(user_input)`.
        # BUT `main.py` expects `analysis` to be a string?
        
        # Let's check main.py again.
        pass

if __name__ == "__main__":
    unittest.main()
