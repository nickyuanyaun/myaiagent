from wordpress_client import WordPressClient, DEFAULT_WP_CONFIG
import os
import logging

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestWP")

def test_real_wp():
    print("Testing WordPress Connection...")
    
    # Use defaults
    wp = WordPressClient(
        DEFAULT_WP_CONFIG['url'],
        DEFAULT_WP_CONFIG['user'],
        DEFAULT_WP_CONFIG['password']
    )
    
    # 1. Create a dummy image
    img_data = b"fake_image_bytes_for_testing" * 10
    filename = "test_agent_upload.txt" # WP might reject .txt for media? Let's try .png header?
    # Actually, let's make a tiny real png or just text file if allowed. 
    # WP Media library usually accepts images.
    # Let's use a simple 1x1 transparent PNG structure
    png_header = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    
    try:
        print("1. Uploading Image...")
        media_id = wp.upload_media(png_header, "agent_test_1x1.png", "image/png")
        print(f"[OK] Image Uploaded! ID: {media_id}")
        
        print("2. Creating Draft Post...")
        post = wp.create_post(
            title="Agent Integration Test",
            content="<p>This is a test post from the AI Agent verification script.</p>",
            status="draft",
            featured_media_id=media_id,
            categories=[1] # Uncategorized
        )
        print(f"[OK] Post Created! ID: {post['id']}")
        print(f"Link: {post['link']}")
        
    except Exception as e:
        print(f"[FAIL] Test Failed: {e}")

if __name__ == "__main__":
    test_real_wp()
