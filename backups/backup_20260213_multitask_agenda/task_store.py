import json
import os
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any

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

    def add_task(self, content: str, target_timestamp: str, chat_id: int, target_user: str = "me", batch_id: Optional[str] = None):
        """
        Adds a new reminder task.
        target_timestamp should be an ISO format string: YYYY-MM-DD HH:MM:SS
        """
        task: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "type": "reminder",
            "batch_id": batch_id,
            "content": content,
            "target_timestamp": target_timestamp,
            "chat_id": chat_id,
            "target_user": target_user,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.tasks.append(task)
        self._save()
        logger.info(f"Added reminder: {content} at {target_timestamp}")
        return task

    def add_generic_task(self, task_type: str, payload: dict, chat_id: int, batch_id: Optional[str] = None):
        """
        Adds a generic task (search, image, wordpress, etc.) to the store.
        """
        task: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "type": task_type,
            "batch_id": batch_id,
            "payload": payload,
            "chat_id": chat_id,
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.tasks.append(task)
        self._save()
        logger.info(f"Added generic task: {task_type} in batch {batch_id}")
        return task

    def update_task_status(self, task_id: str, status: str, result: Any = None, error: Optional[str] = None):
        """
        Updates the status and optional result/error of a task.
        """
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = status
                if result is not None: task["result"] = result
                if error is not None: task["error"] = error
                task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save()
                return True
        return False

    def get_tasks_by_batch(self, batch_id: str):
        return [t for t in self.tasks if t.get("batch_id") == batch_id]

    def get_pending_tasks(self):
        return [t for t in self.tasks if t["status"] == "pending"]

    def complete_task(self, task_id):
        return self.update_task_status(task_id, "completed")

    def delete_task(self, task_id):
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        self._save()

    # --- Download Queue Methods ---
    def add_download_request(self, chat_id: int, url: Optional[str] = None, batch_id: Optional[str] = None):
        task: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "type": "download_req",
            "batch_id": batch_id,
            "chat_id": chat_id,
            "url": url,
            "status": "pending",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.tasks.append(task)
        self._save()
        logger.info(f"Added download request for chat_id: {chat_id}, batch: {batch_id}")
        return task



    def get_next_download_request(self):
        """
        Returns the oldest pending download request (FIFO).
        """
        pending = [t for t in self.tasks if t.get("type") == "download_req" and t["status"] == "pending"]
        # Sort by created_at just in case
        pending.sort(key=lambda x: x["created_at"])
        return pending[0] if pending else None

    def get_all_pending_download_requests(self):
        """
        Returns all pending download requests sorted by time.
        """
        pending = [t for t in self.tasks if t.get("type") == "download_req" and t["status"] == "pending"]
        pending.sort(key=lambda x: x["created_at"])
        return pending

    def cleanup_stale_tasks(self, hours=0.17): # Default ~10 mins (0.17 hours)
        """
        Mark tasks as failed if they have been pending for too long.
        Returns a list of failed tasks.
        """
        now = datetime.now()
        failed_tasks = []
        
        for task in self.tasks:
            if task["status"] == "pending":
                try:
                    # Skip Reminders (they are time-based, not duration-based)
                    if task.get("type") in ["reminder", "reminder_task"]:
                        continue

                    created_at = datetime.strptime(task["created_at"], "%Y-%m-%d %H:%M:%S")
                    diff = (now - created_at).total_seconds()
                    timeout_seconds = hours * 3600
                    
                    if diff > timeout_seconds:
                        task["status"] = "failed"
                        failed_tasks.append(task)
                        logger.warning(f"Task {task['id']} ({task.get('type')}) marked as failed due to timeout.")

                except ValueError: 
                    pass # Ignore parse errors
        
        if failed_tasks:
            self._save()
            
        return failed_tasks
