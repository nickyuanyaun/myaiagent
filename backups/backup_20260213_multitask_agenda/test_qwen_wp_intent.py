
import asyncio
from qwen_brain import QwenBrain
import logging

logging.basicConfig(level=logging.INFO)

async def test_qwen():
    brain = QwenBrain()
    
    # Test 1: Simple WP intent
    text1 = "Post a blog about AI agents on my wordpress site."
    print(f"Testing: {text1}")
    res1 = await asyncio.to_thread(brain.analyze_message, text1)
    print(f"Result 1: WP Needed: {res1.get('wordpress_needed')}, Topic: {res1.get('wp_topic')}")
    
    # Test 2: Ambiguous
    text2 = "Write a story about cats."
    print(f"Testing: {text2}")
    res2 = await asyncio.to_thread(brain.analyze_message, text2)
    print(f"Result 2: WP Needed: {res2.get('wordpress_needed')}")
    
    # Test 3: Chinese
    text3 = "帮我生成一篇关于深度学习的文章并发布到博客"
    print(f"Testing: {text3}")
    res3 = await asyncio.to_thread(brain.analyze_message, text3)
    print(f"Result 3: WP Needed: {res3.get('wordpress_needed')}, Topic: {res3.get('wp_topic')}")


if __name__ == "__main__":
    asyncio.run(test_qwen())
