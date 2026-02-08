import os
import asyncio
import logging
from file_watcher import FileWatcher

logging.basicConfig(level=logging.INFO)

async def test_file_watcher():
    # Setup test dir
    test_dir = "data/test_watch"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
        
    # Initialize
    fw = FileWatcher(watch_dir=test_dir, processed_file="data/test_processed.json", check_interval=2)
    
    # Callback
    async def on_new_file(path):
        print(f"[OK] Callback Triggered for: {path}")
        fw.stop() # Stop after one detection
        
    # Start Watcher in background
    task = asyncio.create_task(fw.start(on_new_file))
    
    # Create a dummy file
    print("Creating dummy file...")
    dummy_path = os.path.join(test_dir, "video.mp4")
    with open(dummy_path, "wb") as f:
        f.write(b"content")
    
    # Wait
    print("Waiting for detection...")
    await asyncio.sleep(15)
    
    # Cleanup
    task.cancel()
    # verify processed
    assert os.path.basename(dummy_path) in fw._load_processed()
    print("✅ Test Complete")

if __name__ == "__main__":
    asyncio.run(test_file_watcher())
