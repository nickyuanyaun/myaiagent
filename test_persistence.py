import time
import os
from datetime import datetime, timedelta
from task_store import TaskStore

def test_persistence():
    print("Test 1: Persistence")
    # Setup
    test_path = "data/test_tasks.json"
    if os.path.exists(test_path):
        os.remove(test_path)
    
    # 1. Init and Add
    ts = TaskStore(test_path)
    now = datetime.now()
    target = now + timedelta(seconds=2)
    target_str = target.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"Adding task for {target_str}")
    ts.add_task("Test Reminder", target_str, 12345)
    
    # 2. Reload
    print("Reloading TaskStore...")
    ts2 = TaskStore(test_path)
    pending = ts2.get_pending_tasks()
    
    assert len(pending) == 1
    assert pending[0]['content'] == "Test Reminder"
    print("[OK] Persistence Verified.")
    
    # 3. Simulate Check
    print("Waiting 3 seconds...")
    time.sleep(3)
    
    print("Checking tasks...")
    # This logic mimics main.py's check_tasks
    pending = ts2.get_pending_tasks()
    current_now = datetime.now()
    
    processed = 0
    for task in pending:
        t_dt = datetime.strptime(task['target_timestamp'], "%Y-%m-%d %H:%M:%S")
        if current_now >= t_dt:
            print(f"Triggering task: {task['content']}")
            ts2.complete_task(task['id'])
            processed += 1
            
    assert processed == 1
    assert len(ts2.get_pending_tasks()) == 0
    print("[OK] Logic Verified.")

if __name__ == "__main__":
    test_persistence()
