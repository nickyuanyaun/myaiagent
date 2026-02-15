
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
        self.headers = {
            "User-Agent": "AIAgent/1.0 (WordPress Client)"
        }

    def upload_media(self, file_data, filename, mime_type=None):
        """
        Uploads an image to the WordPress Media Library.
        file_data: bytes
        filename: str
        """
        if not mime_type:
            if filename.lower().endswith(".png"): mime_type = "image/png"
            elif filename.lower().endswith(".gif"): mime_type = "image/gif"
            else: mime_type = "image/jpeg"

        media_url = f"{self.base_url}/media"
        
        headers = self.headers.copy()
        headers.update({
            "Content-Type": mime_type,
            "Content-Disposition": f"attachment; filename={filename}"
        })

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

    def get_or_create_tag(self, tag_name):
        """Look up a tag by name, create it if it doesn't exist, return its ID."""
        tag_name = tag_name.strip()
        if not tag_name:
            return None
        try:
            # Search for existing tag
            search_url = f"{self.base_url}/tags"
            resp = requests.get(search_url, auth=self.auth, params={"search": tag_name}, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                tags = resp.json()
                for t in tags:
                    if t.get("name", "").lower() == tag_name.lower():
                        logger.info(f"Found existing tag: {tag_name} (ID: {t['id']})")
                        return t["id"]
            
            # Create new tag
            resp = requests.post(search_url, auth=self.auth, json={"name": tag_name}, headers=self.headers, timeout=10)
            if resp.status_code == 201:
                tag_id = resp.json()["id"]
                logger.info(f"Created new tag: {tag_name} (ID: {tag_id})")
                return tag_id
            else:
                logger.error(f"Failed to create tag '{tag_name}': {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Tag lookup/create error for '{tag_name}': {e}")
            return None

    def get_or_create_category(self, cat_name):
        """Look up a category by name, create it if it doesn't exist, return its ID."""
        cat_name = cat_name.strip()
        if not cat_name:
            return None
        try:
            search_url = f"{self.base_url}/categories"
            resp = requests.get(search_url, auth=self.auth, params={"search": cat_name}, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                cats = resp.json()
                for c in cats:
                    if c.get("name", "").lower() == cat_name.lower():
                        logger.info(f"Found existing category: {cat_name} (ID: {c['id']})")
                        return c["id"]
            
            # Create new category
            resp = requests.post(search_url, auth=self.auth, json={"name": cat_name}, headers=self.headers, timeout=10)
            if resp.status_code == 201:
                cat_id = resp.json()["id"]
                logger.info(f"Created new category: {cat_name} (ID: {cat_id})")
                return cat_id
            else:
                logger.error(f"Failed to create category '{cat_name}': {resp.status_code} {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Category lookup/create error for '{cat_name}': {e}")
            return None

    def create_post(self, title, content, status='draft', categories=None, tags=None, featured_media_id=None):
        """
        Creates a new post in WordPress.
        categories: list of category IDs
        tags: list of tag IDs
        """
        posts_url = f"{self.base_url}/posts"
        
        payload = {
            "title": title,
            "content": content,
            "status": status
        }
        
        if categories:
            payload['categories'] = categories
        
        if tags:
            payload['tags'] = tags
        
        if featured_media_id:
            payload['featured_media'] = featured_media_id

        logger.info(f"Creating post: {title} (categories={categories}, tags={tags})")
        try:
            response = requests.post(
                posts_url,
                auth=self.auth,
                json=payload,
                headers=self.headers,
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

