import logging
import uuid
from datetime import datetime, timedelta
import re

# Mock Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

# Mock TaskStore Logic
class MockTaskStore:
    def __init__(self):
        self.tasks = []

    def add_download_request(self, chat_id, url=None, created_at=None):
        if not created_at:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        task = {
            "id": str(uuid.uuid4()),
            "type": "download_req",
            "chat_id": chat_id,
            "url": url,
            "status": "pending",
            "created_at": created_at
        }
        self.tasks.append(task)
        return task

    def get_all_pending_download_requests(self):
        pending = [t for t in self.tasks if t.get("type") == "download_req" and t["status"] == "pending"]
        pending.sort(key=lambda x: x["created_at"])
        return pending

    def cleanup_stale_tasks(self, hours=0.17):
        now = datetime.now()
        failed_tasks = []
        for task in self.tasks:
            if task["status"] == "pending":
                try:
                    created_at = datetime.strptime(task["created_at"], "%Y-%m-%d %H:%M:%S")
                    diff = (now - created_at).total_seconds()
                    if diff > hours * 3600:
                        task["status"] = "failed"
                        failed_tasks.append(task)
                except ValueError: pass
        return failed_tasks

def test_smart_matching():
    store = MockTaskStore()
    
    # 1. Add Old Request (User A) - Generic URL
    task_a = store.add_download_request(chat_id=111, url="https://youtube.com/watch?v=OLD_VIDEO_1")
    
    # 2. Add New Request (User B) - Specific URL
    task_b = store.add_download_request(chat_id=222, url="https://youtube.com/watch?v=NEW_VIDEO_2")
    
    # Simulating File Callback Logic
    def resolve_owner(filename, store):
        all_pending = store.get_all_pending_download_requests()
        pending_task = None
        
        # Smart Match
        for task in all_pending:
            url = task.get('url', "")
            if not url: continue
            
            video_id = None
            if "youtube.com" in url or "youtu.be" in url:
                match = re.search(r'(?:v=|\/)([a-zA-Z0-9_-]{11})', url)
                if match: video_id = match.group(1)
            
            if video_id and video_id in filename:
                print(f"MATCH: {filename} -> Task {task['id']} (User {task['chat_id']})")
                return task
        
        # Fallback
        if all_pending:
            print(f"FALLBACK: {filename} -> Task {all_pending[0]['id']} (User {all_pending[0]['chat_id']})")
            return all_pending[0]
            
        return None

    print("\n--- Test 1: Smart Match New Video ---")
    # File comes in for User B (NEW_VIDEO_2)
    filename = "My Cool Video [NEW_VIDEO_2].mp4"
    resolved = resolve_owner(filename, store)
    
    if resolved and resolved['chat_id'] == 222:
        print("✅ SUCCESS: Correctly identified User B despite generic queue order.")
    else:
        print(f"❌ FAILED: Assigned to {resolved['chat_id'] if resolved else 'None'}, expected 222.")

    print("\n--- Test 2: Fallback for Generic Name ---")
    # File comes in with no ID
    filename = "Random Video.mp4"
    resolved = resolve_owner(filename, store)
    
    if resolved and resolved['chat_id'] == 111:
        print("✅ SUCCESS: Fallback to User A (Oldest).")
    else:
        print(f"❌ FAILED: Assigned to {resolved['chat_id'] if resolved else 'None'}, expected 111.")

def test_timeout():
    store = MockTaskStore()
    print("\n--- Test 3: Timeout ---")
    
    # Add task created 20 mins ago
    old_time = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
    store.add_download_request(chat_id=999, url="http://slow.com", created_at=old_time)
    
    # Add fresh task
    store.add_download_request(chat_id=888, url="http://fast.com")
    
    failed = store.cleanup_stale_tasks(hours=0.17) # 10 mins
    
    if len(failed) == 1 and failed[0]['chat_id'] == 999:
        print("✅ SUCCESS: Correctly timed out the old task.")
    else:
         print(f"❌ FAILED: Timed out {len(failed)} tasks, expected 1.")

if __name__ == "__main__":
    test_smart_matching()
    test_timeout()
