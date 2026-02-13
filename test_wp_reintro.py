
import os
from dotenv import load_dotenv
from wordpress_client import WordPressClient
import logging

logging.basicConfig(level=logging.INFO)

def test_wp():
    load_dotenv()
    wp_user = os.getenv("WP_USER")
    wp_pass = os.getenv("WP_PASSWORD")
    wp_url = os.getenv("WP_BASE_URL")
    
    print(f"Testing WP with User: {wp_user}, URL: {wp_url}")
    
    if not wp_user or not wp_pass:
        print("Skipping test: Credentials not found.")
        return

    client = WordPressClient(wp_url, wp_user, wp_pass)
    
    # Test Post Creation (Draft)
    try:
        post = client.create_post(
            title="Test Post from Agent Re-intro",
            content="<p>This is a test Draft.</p>",
            status="draft",
            categories=[1]
        )
        print(f"Success! Post ID: {post['id']}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_wp()
