import os
from unittest.mock import MagicMock, patch

# Mock dependencies
class MockMemoryStore:
    def search_memory(self, query, n_results=5):
        print(f"[MockMemory] Searching for: {query}")
        if "password" in query.lower():
            # Return a mock memory formatted like a user turned fact
            return [
                {"text": "My WordPress username is Nick_Agent", "metadata": {}},
                {"text": "My WordPress password is Nick1111!@", "metadata": {}}
            ]
        return []

# We want to test the logic that was added to main.py
# Since main.py is complex to import due to globals, we will extract the logic snippet 
# or just mock the environment where it runs.
# Actually, the best way is to duplicate the logic function here for unit testing 
# since we can't easily run main.py in a test harness without side effects.

def resolve_wp_credentials(task, memory_store):
    print(f"--- Resolving Credentials for Task: {task} ---")
    
    wp_user = task.get("username")
    wp_password = task.get("password")
    
    # Check Memory if not provided
    if not wp_user or not wp_password:
        if memory_store:
            # Simple keyword search
            mem_creds = memory_store.search_memory("WordPress password", n_results=5)
            # In the real code, we just passed. But here let's see if we can "simulate" the extraction
            # Real Qwen needs to extract it.
            # But wait, the current main.py implementation I wrote just does `pass` inside the memory block!
            # I need to actually parse the memory results if I want it to work from memory WITHOUT Qwen.
            # BUT, the plan was: "Qwen should have extracted them... For now, we trust Qwen".
            # So if Qwen didn't extract them into the task, my code in main.py currently does NOTHING with the memory results.
            
            # Let's re-read the code I wrote in main.py:
            # if not wp_user or not wp_password:
            #    if memory_store:
            #        mem_creds = search...
            #        pass 
            
            # AHA! I missed the parsing logic in the implementation step. I wrote "pass" in the comment thinking I'd come back or Qwen would handle it.
            # But the user scenario is: "I gave it my username... but it used the default".
            # If Qwen didn't pick it up in "wordpress_post" task, then `task.get('username')` is None.
            # So I MUST implement the fallback parsing in main.py or force Qwen to re-analyze.
            
            # Let's simulate a simple parser here that I should add to main.py
            print(f"[Logic] Memory found: {len(mem_creds)} items")
            # Match main.py logic (with debugs)
            for mem in mem_creds:
                text = mem.get('text', '')
                print(f"[Logic] Processing memory: '{text}'")
                
                if not wp_user and ("username" in text.lower() or "用户" in text):
                    if ":" in text:
                        parts = text.split(":")
                        if len(parts) > 1: wp_user = parts[1].strip()
                    elif " is " in text:
                        wp_user = text.split(" is ")[1].strip()
                    print(f"[Logic] Extracted User: {wp_user}")
                 
                if not wp_password and ("password" in text.lower() or "密码" in text):
                    if ":" in text:
                        parts = text.split(":")
                        if len(parts) > 1: wp_password = parts[1].strip()
                    elif " is " in text:
                        wp_password = text.split(" is ")[1].strip()
                    print(f"[Logic] Extracted Password: {wp_password}")
                
                if wp_user and wp_password: break

    # Fallback to defaults
    if not wp_user: wp_user = "DEFAULT_USER"
    if not wp_password: wp_password = "DEFAULT_PASSWORD"
    
    return wp_user, wp_password

def test_logic():
    ms = MockMemoryStore()
    
    # Case 1: Credentials in Task (Qwen successful)
    print("\nTest 1: Credentials in Task")
    t1 = {"username": "TaskUser", "password": "TaskPassword"}
    u, p = resolve_wp_credentials(t1, ms)
    print(f"Result: {u}, {p}")
    assert u == "TaskUser"
    assert p == "TaskPassword"

    # Case 2: Credentials Missing, but in Memory
    print("\nTest 2: Credentials in Memory")
    t2 = {} # Empty
    u, p = resolve_wp_credentials(t2, ms)
    print(f"Result: {u}, {p}")
    # Note: My mock memory has "Nick_Agent" and "Nick1111!@"
    # Only if I implement the parsing logic!
    if u == "Nick_Agent" and p == "Nick1111!@":
        print("[SUCCESS] Memory fallback worked")
    else:
        print("[FAIL] Memory fallback failed (did you implement parsing?)")

if __name__ == "__main__":
    test_logic()
