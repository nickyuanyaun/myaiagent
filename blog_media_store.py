
import json
import os
import logging
import uuid
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class BlogMediaStore:
    """
    Manages temporary storage of user-uploaded media for blog posts.
    Supports accumulating images across multiple conversations/messages.
    """

    def __init__(self, media_dir="data/blog_media", metadata_path="data/blog_media.json"):
        self.media_dir = media_dir
        self.metadata_path = metadata_path
        self._ensure_dirs()
        self.entries: List[Dict[str, Any]] = self._load()

    def _ensure_dirs(self):
        os.makedirs(self.media_dir, exist_ok=True)
        meta_dir = os.path.dirname(self.metadata_path)
        if meta_dir and not os.path.exists(meta_dir):
            os.makedirs(meta_dir)

    def _load(self) -> list:
        if not os.path.exists(self.metadata_path):
            return []
        try:
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load blog media metadata: {e}")
            return []

    def _save(self):
        try:
            with open(self.metadata_path, 'w', encoding='utf-8') as f:
                json.dump(self.entries, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save blog media metadata: {e}")

    def add_media(self, image_bytes: bytes, filename: str, chat_id: int, caption: str = "") -> str:
        """
        Save an image to local storage for later blog use.
        Returns the media_id.
        """
        media_id = str(uuid.uuid4())
        # Ensure unique filename
        ext = os.path.splitext(filename)[1] if '.' in filename else '.jpg'
        safe_filename = f"{media_id}{ext}"
        filepath = os.path.join(self.media_dir, safe_filename)

        try:
            with open(filepath, 'wb') as f:
                f.write(image_bytes)
            
            entry = {
                "id": media_id,
                "filename": safe_filename,
                "original_filename": filename,
                "filepath": filepath,
                "chat_id": chat_id,
                "caption": caption,
                "status": "pending",  # pending -> published -> deleted
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "size_bytes": len(image_bytes)
            }
            self.entries.append(entry)
            self._save()
            logger.info(f"Blog media saved: {safe_filename} ({len(image_bytes)} bytes) for chat {chat_id}")
            return media_id

        except Exception as e:
            logger.error(f"Failed to save blog media: {e}")
            raise e

    def get_pending_media(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all pending (not yet published) media for a given chat_id."""
        return [e for e in self.entries if e["chat_id"] == chat_id and e["status"] == "pending"]
    
    def get_published_media(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all published (awaiting cleanup confirmation) media for a given chat_id."""
        return [e for e in self.entries if e["chat_id"] == chat_id and e["status"] == "published"]

    def get_media_count(self, chat_id: int) -> int:
        """Get count of pending media for a chat."""
        return len(self.get_pending_media(chat_id))

    def get_media_bytes(self, media_id: str) -> Optional[bytes]:
        """Read the binary data of a stored media file."""
        for entry in self.entries:
            if entry["id"] == media_id:
                try:
                    with open(entry["filepath"], 'rb') as f:
                        return f.read()
                except Exception as e:
                    logger.error(f"Failed to read media {media_id}: {e}")
                    return None
        return None

    def mark_published(self, chat_id: int):
        """Mark all pending media for a chat as published."""
        count = 0
        for entry in self.entries:
            if entry["chat_id"] == chat_id and entry["status"] == "pending":
                entry["status"] = "published"
                entry["published_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                count += 1
        if count > 0:
            self._save()
            logger.info(f"Marked {count} media items as published for chat {chat_id}")
        return count

    def delete_published(self, chat_id: int) -> int:
        """Delete all published media files and remove their metadata entries."""
        to_delete = [e for e in self.entries if e["chat_id"] == chat_id and e["status"] == "published"]
        deleted_count = 0

        for entry in to_delete:
            filepath = entry.get("filepath", "")
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    logger.info(f"Deleted media file: {filepath}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete media file {filepath}: {e}")

        # Remove entries from metadata
        self.entries = [e for e in self.entries if not (e["chat_id"] == chat_id and e["status"] == "published")]
        self._save()
        logger.info(f"Cleaned up {deleted_count} published media items for chat {chat_id}")
        return deleted_count


if __name__ == "__main__":
    # Quick manual test
    store = BlogMediaStore(media_dir="data/test_blog_media", metadata_path="data/test_blog_media.json")
    
    # Simulate adding media
    fake_img = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    mid = store.add_media(fake_img, "test_photo.png", chat_id=12345, caption="Test blog image")
    print(f"Added media: {mid}")
    print(f"Pending count: {store.get_media_count(12345)}")
    
    # Mark published
    store.mark_published(12345)
    print(f"Published media: {len(store.get_published_media(12345))}")
    
    # Delete
    deleted = store.delete_published(12345)
    print(f"Deleted: {deleted}")
    
    # Cleanup test data
    import shutil
    shutil.rmtree("data/test_blog_media", ignore_errors=True)
    if os.path.exists("data/test_blog_media.json"):
        os.remove("data/test_blog_media.json")
    print("Test cleanup done.")
