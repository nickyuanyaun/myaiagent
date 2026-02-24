
import requests
from requests.auth import HTTPBasicAuth
import os
import logging
import base64
import time
import re
from urllib.parse import quote

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
        
        # Handle non-ASCII filenames (e.g. Chinese) using RFC 5987
        try:
            filename.encode('ascii')
            content_disp = f"attachment; filename={filename}"
        except UnicodeEncodeError:
            # Use RFC 5987 encoding for non-ASCII filenames
            ascii_fallback = f"upload_{int(time.time())}{os.path.splitext(filename)[1]}"
            encoded_filename = quote(filename)
            content_disp = f"attachment; filename={ascii_fallback}; filename*=UTF-8''{encoded_filename}"
        
        headers.update({
            "Content-Type": mime_type,
            "Content-Disposition": content_disp
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
                source_url = data.get('source_url', '')
                logger.info(f"Media uploaded successfully. ID: {data['id']}, URL: {source_url}")
                return {"id": data['id'], "source_url": source_url}
            else:
                logger.error(f"Media upload failed: {response.status_code} {response.text}")
                raise Exception(f"Media upload failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Media upload error: {e}")
            raise e

    def get_or_create_tag(self, tag_name):
        """Look up a tag by name, create it if it doesn't exist, return its ID."""
        if not tag_name:
            return None
        tag_name = str(tag_name).strip()
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
        if not cat_name:
            return None
        cat_name = str(cat_name).strip()
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

    @staticmethod
    def format_content_with_ai(raw_content, image_urls, genai_client, stored_media_captions=None):
        """
        Use Gemini to compose rich WordPress Gutenberg block HTML from raw draft text + image URLs.
        Returns formatted Gutenberg HTML string.
        """
        image_info_lines = []
        for i, url in enumerate(image_urls):
            image_info_lines.append(f"  IMAGE_{i+1}: {url}")
        image_list = "\n".join(image_info_lines) if image_info_lines else "  (No images available)"

        formatting_prompt = f"""You are a professional WordPress blog editor and designer.

Convert the raw blog content below into beautifully formatted WordPress Gutenberg block HTML.

CRITICAL LANGUAGE RULE: You MUST preserve the SAME language as the raw content. If the content is in Chinese, output Chinese. If in English, output English. Do NOT translate. Default language is Chinese (中文).
1. Structure with proper heading hierarchy:
   - Use <!-- wp:heading {{"level":2}} --> <h2>...</h2> <!-- /wp:heading --> for main section titles
   - Use <!-- wp:heading {{"level":3}} --> <h3>...</h3> <!-- /wp:heading --> for subsection titles
   - Use <!-- wp:heading {{"level":4}} --> <h4>...</h4> <!-- /wp:heading --> for sub-subsection titles

2. Wrap every paragraph in Gutenberg paragraph blocks:
   <!-- wp:paragraph -->
   <p>Text here. Use <strong>bold</strong> for key terms and <em>italic</em> for emphasis.</p>
   <!-- /wp:paragraph -->

3. Use blockquotes for impactful statements or key takeaways:
   <!-- wp:quote -->
   <blockquote class="wp-block-quote"><p>Impactful quote here</p></blockquote>
   <!-- /wp:quote -->

4. Use list blocks for enumerations:
   <!-- wp:list -->
   <ul><li>Item 1</li><li>Item 2</li></ul>
   <!-- /wp:list -->

5. Use separator blocks between major sections for visual breathing room:
   <!-- wp:separator {{"className":"is-style-wide"}} -->
   <hr class="wp-block-separator has-alpha-channel-opacity is-style-wide"/>
   <!-- /wp:separator -->

6. IMAGES: Place each image at the most contextually relevant position in the article.
   Do NOT stack them all together. Spread them throughout the content where they illustrate the text.
   For alt text and figcaption: write a SHORT descriptive phrase (max 10 words) based on what the image likely shows in context of the surrounding text. Do NOT copy the user's instructions or prompt text as caption.
   Use this exact format for each image:
   <!-- wp:image {{"sizeSlug":"large","linkDestination":"none"}} -->
   <figure class="wp-block-image size-large"><img src="IMAGE_URL" alt="简短描述"/><figcaption class="wp-element-caption">简短图片说明</figcaption></figure>
   <!-- /wp:image -->

7. Start the article with an engaging intro paragraph (no heading before it).
8. End with a conclusion or call-to-action section.
9. Output ONLY the Gutenberg block HTML. No explanation, no markdown, no JSON wrapping.

AVAILABLE IMAGES:
{image_list}

RAW CONTENT TO FORMAT:
{raw_content}"""

        try:
            from google.genai import types
            import os
            resp = genai_client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
                contents=[formatting_prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,  # Low temperature for consistent formatting
                    response_mime_type="application/json"
                )
            )
            if resp.text:
                formatted = resp.text.strip()
                # Clean up: remove markdown code fences if Gemini wrapped it
                if formatted.startswith("```html"):
                    formatted = formatted[7:]
                if formatted.startswith("```"):
                    formatted = formatted[3:]
                if formatted.endswith("```"):
                    formatted = formatted[:-3]
                formatted = formatted.strip()
                logger.info(f"AI formatting complete. Output length: {len(formatted)} chars")
                return formatted
        except Exception as e:
            logger.error(f"AI formatting failed: {e}")
        
        return None

    @staticmethod
    def _basic_gutenberg_format(raw_content, image_urls):
        """
        Fallback: convert raw text to basic Gutenberg blocks without AI.
        Splits on markdown-style headings and double newlines.
        """
        lines = raw_content.split('\n')
        blocks = []
        current_paragraph = []

        def flush_paragraph():
            if current_paragraph:
                text = ' '.join(current_paragraph).strip()
                if text:
                    blocks.append(
                        f'<!-- wp:paragraph -->\n<p>{text}</p>\n<!-- /wp:paragraph -->'
                    )
                current_paragraph.clear()

        for line in lines:
            line = line.strip()
            if not line:
                flush_paragraph()
                continue
            # Detect markdown headings
            if line.startswith('#### '):
                flush_paragraph()
                heading = line[5:].strip().lstrip('#').strip()
                blocks.append(f'<!-- wp:heading {{"level":4}} -->\n<h4>{heading}</h4>\n<!-- /wp:heading -->')
            elif line.startswith('### '):
                flush_paragraph()
                heading = line[4:].strip().lstrip('#').strip()
                blocks.append(f'<!-- wp:heading {{"level":3}} -->\n<h3>{heading}</h3>\n<!-- /wp:heading -->')
            elif line.startswith('## '):
                flush_paragraph()
                heading = line[3:].strip().lstrip('#').strip()
                blocks.append(f'<!-- wp:heading {{"level":2}} -->\n<h2>{heading}</h2>\n<!-- /wp:heading -->')
            elif line.startswith('# '):
                flush_paragraph()
                heading = line[2:].strip().lstrip('#').strip()
                blocks.append(f'<!-- wp:heading {{"level":2}} -->\n<h2>{heading}</h2>\n<!-- /wp:heading -->')
            elif line.startswith('* ') or line.startswith('- '):
                # Collect list items
                flush_paragraph()
                items = [line[2:].strip()]
                # Peek ahead handled by next iterations
                blocks.append(f'<!-- wp:list -->\n<ul><li>{items[0]}</li></ul>\n<!-- /wp:list -->')
            else:
                # Convert markdown bold/italic to HTML
                line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                line = re.sub(r'\*(.+?)\*', r'<em>\1</em>', line)
                current_paragraph.append(line)
        
        flush_paragraph()

        # Insert images at even intervals
        if image_urls and blocks:
            image_blocks = []
            for url in image_urls:
                image_blocks.append(
                    f'<!-- wp:image {{"sizeSlug":"large","linkDestination":"none"}} -->\n'
                    f'<figure class="wp-block-image size-large">'
                    f'<img src="{url}" alt=""/>'
                    f'</figure>\n'
                    f'<!-- /wp:image -->'
                )
            interval = max(1, len(blocks) // (len(image_blocks) + 1))
            for idx in range(len(image_blocks) - 1, -1, -1):
                pos = min(interval * (idx + 1), len(blocks))
                blocks.insert(pos, image_blocks[idx])

        return '\n\n'.join(blocks)

    def create_post_unified(self, title, content, category_names=None,
                            generated_images=None, stored_media_images=None,
                            genai_client=None, stored_media_captions=None):
        """
        Unified method to create a post with various media sources.
        Uses AI to format content into rich Gutenberg blocks with contextual image placement.
        """
        logger.info(f"Creating unified post: {title}")
        
        # 1. Resolve Category IDs
        category_ids = []
        if category_names:
            for cat_name in category_names:
                cid = self.get_or_create_category(cat_name)
                if cid: category_ids.append(cid)
        
        # 2. Upload Images & Collect results (id + source_url)
        uploaded_media = []  # List of {"id": int, "source_url": str}
        
        # A. Generated Images (Bytes)
        if generated_images:
            for i, img_bytes in enumerate(generated_images):
                filename = f"gen_img_{i}_{int(time.time())}.png"
                result = self.upload_media(img_bytes, filename, "image/png")
                if result: uploaded_media.append(result)
        
        # B. Stored Media (Dicts with 'data' bytes)
        if stored_media_images:
            for i, item in enumerate(stored_media_images):
                if 'data' in item:
                    filename = item.get('filename', f"stored_img_{i}.jpg")
                    result = self.upload_media(item['data'], filename)
                    if result: uploaded_media.append(result)

        # 3. Format Content with AI (or fallback to basic formatting)
        featured_media_id = None
        image_urls = [m["source_url"] for m in uploaded_media if m.get("source_url")]
        
        if uploaded_media:
            featured_media_id = uploaded_media[0]["id"]

        # Try AI formatting first
        formatted_content = None
        if genai_client:
            logger.info("Using AI to format blog content with rich Gutenberg blocks...")
            formatted_content = self.format_content_with_ai(
                content, image_urls, genai_client, stored_media_captions
            )
        
        if formatted_content:
            content = formatted_content
        else:
            # Fallback: basic formatting
            logger.info("Using basic Gutenberg formatting (no AI client available or AI failed)...")
            content = self._basic_gutenberg_format(content, image_urls)

        # 4. Create Post
        result = self.create_post(
            title=title,
            content=content,
            status='publish',
            categories=category_ids,
            featured_media_id=featured_media_id
        )
        
        if result:
            return result.get('link')
        return None
