import os
import logging
from dotenv import load_dotenv
from wordpress_client import WordPressClient

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ReproductionScript")

def verify_wordpress():
    load_dotenv()
    
    wp_url = os.getenv("WP_BASE_URL")
    wp_user = os.getenv("WP_USER")
    wp_password = os.getenv("WP_PASSWORD")
    
    if not all([wp_url, wp_user, wp_password]):
        print("[FAIL] Missing environment variables: WP_BASE_URL, WP_USER, WP_PASSWORD")
        return

    print(f"Testing WordPress Connection to: {wp_url} as {wp_user}")
    
    try:
        client = WordPressClient(wp_url, wp_user, wp_password)
        
        # 1. Test Image Upload
        print("1. Uploading Test Image...")
        # Small 1x1 transparent PNG
        png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        
        media_id = client.upload_media(png_data, "repro_test.png", "image/png")
        print(f"[OK] Image Uploaded! ID: {media_id}")
        
        # 2. Test Post Creation
        print("2. Creating Test Post...")
        post = client.create_post(
            title="Reproduction Test Post",
            content="<!-- wp:paragraph --><p>This is a test post to verify the publishing workflow.</p><!-- /wp:paragraph -->",
            status="draft",
            featured_media_id=media_id
        )
        print(f"[OK] Post Created! ID: {post.get('id')} Link: {post.get('link')}")
        
    except Exception as e:
        print(f"[FAIL] Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_wordpress()
