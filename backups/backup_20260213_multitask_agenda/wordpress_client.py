
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
        self.password = password
        self.auth = HTTPBasicAuth(self.username, self.password)

    def upload_media(self, file_data, filename, mime_type="image/jpeg"):
        """
        Uploads an image to the WordPress Media Library.
        file_data: bytes
        filename: str
        """
        media_url = f"{self.base_url}/media"
        
        headers = {
            "Content-Type": mime_type,
            "Content-Disposition": f"attachment; filename={filename}"
        }

        logger.info(f"Uploading media: {filename} to {media_url}")
        try:
            response = requests.post(
                media_url,
                auth=self.auth,
                data=file_data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"Media uploaded successfully. ID: {data['id']}")
                return data['id']
            else:
                logger.error(f"Media upload failed: {response.status_code} {response.text}")
                raise Exception(f"Media upload failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Media upload error: {e}")
            raise e

    def create_post(self, title, content, status='draft', categories=None, featured_media_id=None):
        """
        Creates a new post in WordPress.
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

        logger.info(f"Creating post: {title}")
        try:
            response = requests.post(
                posts_url,
                auth=self.auth,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            if response.status_code == 201:
                data = response.json()
                logger.info(f"Post created successfully. ID: {data['id']} Link: {data.get('link')}")
                return data
            else:
                logger.error(f"Post creation failed: {response.status_code} {response.text}")
                raise Exception(f"Post creation failed: {response.status_code} {response.text}")
                
        except Exception as e:
            logger.error(f"Post creation error: {e}")
            raise e
