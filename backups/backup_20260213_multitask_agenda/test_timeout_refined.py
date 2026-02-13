import logging
import uuid
from datetime import datetime, timedelta
import re

# Mock Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

# Mock TaskStore Logic (Copied from actual implementation plan)
class MockTaskStore:
    def __init__(self):
        self.tasks = []

    def add_task(self, type, chat_id, created_at=None):
        if not created_at:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        task = {
            "id": str(uuid.uuid4()),
            "type": type,
            "chat_id": chat_id,
            "status": "pending",
            "created_at": created_at
        }
        self.tasks.append(task)
        return task

    def cleanup_stale_tasks(self, hours=0.17):
        now = datetime.now()
        failed_tasks = []
        for task in self.tasks:
            if task["status"] == "pending":
                try:
                    # Skip Reminders
                    if task.get("type") in ["reminder", "reminder_task"]:
                        continue

                    created_at = datetime.strptime(task["created_at"], "%Y-%m-%d %H:%M:%S")
                    diff = (now - created_at).total_seconds()
                    if diff > hours * 3600:
                        task["status"] = "failed"
                        failed_tasks.append(task)
                except ValueError: pass
        return failed_tasks

def test_timeout_logic():
    store = MockTaskStore()
    print("\n--- Test Timeout Logic ---")
    
    old_time = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Old Download -> Should Timeout
    store.add_task(type="download_req", chat_id=1, created_at=old_time)
    
    # 2. Old Reminder -> Should NOT Timeout
    store.add_task(type="reminder", chat_id=2, created_at=old_time)
    
    # 3. New Generic Task -> Should NOT Timeout
    store.add_task(type="other_task", chat_id=3) # fresh
    
    # 4. Old Generic Task -> Should Timeout
    store.add_task(type="other_task", chat_id=4, created_at=old_time)
    
    failed = store.cleanup_stale_tasks(hours=0.17) # 10 mins
    
    failed_ids = [t['chat_id'] for t in failed]
    
    if 1 in failed_ids and 4 in failed_ids:
        print("[OK] Old Download and Old Other Task timed out.")
    else:
        print(f"[FAIL] Expected 1 and 4 to timeout. Got: {failed_ids}")
        
    if 2 not in failed_ids:
        print("[OK] Old Reminder did NOT timeout.")
    else:
        print("[FAIL] Reminder timed out!")

if __name__ == "__main__":
    test_timeout_logic()
