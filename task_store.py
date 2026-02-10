import json
import os
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class TaskStore:
    def __init__(self, persistence_path="data/tasks.json"):
        self.persistence_path = persistence_path
        self._ensure_dir()
        self.tasks = self._load()

    def _ensure_dir(self):
        directory = os.path.dirname(self.persistence_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

    def _load(self):
        if not os.path.exists(self.persistence_path):
            return []
        try:
            with open(self.persistence_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            return []

    def _save(self):
        try:
            with open(self.persistence_path, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")

    def add_task(self, content: str, target_timestamp: str, chat_id: int, target_user: str = "me"):
        """
        Adds a new task.
        target_timestamp should be an ISO format string: YYYY-MM-DD HH:MM:SS
        """
        task = {
            "id": str(uuid.uuid4()),
            "type": "reminder",
            "content": content,
            "target_timestamp": target_timestamp,
            "chat_id": chat_id,
            "target_user": target_user,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.tasks.append(task)
        self._save()
        logger.info(f"Added task: {content} at {target_timestamp}")
        return task

    def get_pending_tasks(self):
        return [t for t in self.tasks if t["status"] == "pending"]

    def complete_task(self, task_id):
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = "completed"
                self._save()
                return True
        return False

    def delete_task(self, task_id):
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        self._save()

    # --- Download Queue Methods ---
    def add_download_request(self, chat_id: int):
        task = {
            "id": str(uuid.uuid4()),
            "type": "download_req",
            "chat_id": chat_id,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.tasks.append(task)
        self._save()
        logger.info(f"Added download request for chat_id: {chat_id}")
        return task

    def get_next_download_request(self):
        """
        Returns the oldest pending download request (FIFO).
        """
        pending = [t for t in self.tasks if t.get("type") == "download_req" and t["status"] == "pending"]
        # Sort by created_at just in case
        pending.sort(key=lambda x: x["created_at"])
        return pending[0] if pending else None

    def cleanup_stale_tasks(self, hours=2):
        """
        Mark tasks as failed if they have been pending for too long.
        """
        now = datetime.now()
        count = 0
        for task in self.tasks:
            if task["status"] == "pending":
                try:
                    created_at = datetime.strptime(task["created_at"], "%Y-%m-%d %H:%M:%S")
                    diff = (now - created_at).total_seconds()
                    if diff > hours * 3600:
                        task["status"] = "failed"
                        logger.warning(f"Task {task['id']} marked as failed due to timeout.")
                        count += 1
                except ValueError: 
                    pass # Ignore parse errors
        
        if count > 0:
            self._save()
            return count
        return 0
