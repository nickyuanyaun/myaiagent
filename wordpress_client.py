import requests
from requests.auth import HTTPBasicAuth
import os
import logging
import base64

logger = logging.getLogger(__name__)

class WordPressClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password.replace(" ", "") # Remove spaces from app password if present

    def upload_media(self, file_bytes: bytes, filename: str, mime_type: str = "image/jpeg"):
        """
        Uploads an image to the WordPress Media Library.
        Returns the media ID on success, or raises an exception.
        """
        media_url = f"{self.base_url}/media"
        
        headers = {
            "Content-Type": mime_type,
            "Content-Disposition": f"attachment; filename={filename}"
        }

        logger.info(f"WP: Uploading media {filename} to {media_url}...")
        
        try:
            response = requests.post(
                media_url,
                auth=HTTPBasicAuth(self.username, self.password),
                data=file_bytes,
                headers=headers,
                timeout=60
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"WP: Media uploaded successfully. ID: {data['id']}")
                return data['id']
            else:
                logger.error(f"WP Upload Failed: {response.status_code} {response.text}")
                raise Exception(f"Media upload failed: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"WP Upload Error: {e}")
            raise e

    def create_post(self, title, content, status='draft', categories=None, featured_media_id=None):
        """
        Creates a new post in WordPress.
        
        Args:
            title (str): Post title.
            content (str): HTML content of the post.
            status (str): 'draft' or 'publish'.
            categories (list): List of category IDs (e.g., [20] for AI).
            featured_media_id (int): ID of the uploaded image to use as feature.
        """
        posts_url = f"{self.base_url}/posts"
        
        payload = {
            "title": title,
            "content": content,
            "status": status
        }
        
        if categories:
            payload['categories'] = categories
        
        if featured_media_id:
            payload['featured_media'] = featured_media_id

        logger.info(f"WP: Creating post '{title}' (Status: {status})...")
        
        try:
            response = requests.post(
                posts_url,
                auth=HTTPBasicAuth(self.username, self.password),
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"WP: Post created successfully. ID: {data['id']}")
                return data
            else:
                logger.error(f"WP Post Creation Failed: {response.status_code} {response.text}")
                raise Exception(f"Post creation failed: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"WP Post Creation Error: {e}")
            raise e

# Default Configuration (from user request)
# Can be overridden by env vars in main.py
DEFAULT_WP_CONFIG = {
    "url": "https://www.foxcsong.com/wp-json/wp/v2",
    "user": "Fox_agent",
    "password": "zUQA jKMO XBGq SJSB XQZQ DxYC"
}
