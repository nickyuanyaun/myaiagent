import logging
import requests
import json

logger = logging.getLogger(__name__)

class MeTubeClient:
    def __init__(self, base_url="http://192.168.1.28:8081"):
        self.base_url = base_url.rstrip('/')

    def add_download(self, url: str, quality: str = "best"):
        """
        Adds a video URL to the MeTube download queue.
        Endpoint: /add
        Payload: {"url": "...", "quality": "best", "format": "mp4"}
        """
        endpoint = f"{self.base_url}/add"
        payload = {
            "url": url,
            "quality": quality,
            "format": "mp4"  # Explicitly request MP4
        }
        
        logger.info(f"MeTube: Adding download for {url} to {endpoint}")
        try:
            # According to docs, /add accepts POST with JSON
            response = requests.post(endpoint, json=payload, timeout=30)
            
            if response.status_code == 200:
                logger.info("MeTube: Successfully added.")
                return True
            else:
                logger.error(f"MeTube: Failed to add. Status: {response.status_code}, Body: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"MeTube Connection Error: {e}")
            return False

if __name__ == "__main__":
    # Simple test
    client = MeTubeClient()
    # client.add_download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
