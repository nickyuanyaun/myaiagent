import os
import json
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

class FileWatcher:
    def __init__(self, watch_dir, processed_file="data/processed_files.json", check_interval=30):
        self.watch_dir = watch_dir
        self.processed_file = processed_file
        self.check_interval = check_interval
        self._ensure_dir()
        self.processed_files = self._load_processed()
        self.running = False

    def _ensure_dir(self):
        directory = os.path.dirname(self.processed_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

    def _load_processed(self):
        if not os.path.exists(self.processed_file):
            return set()
        try:
            with open(self.processed_file, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            logger.error(f"Failed to load processed files: {e}")
            return set()

    def _save_processed(self):
        try:
            with open(self.processed_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.processed_files), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save processed files: {e}")

    async def start(self, callback):
        """
        Starts the watcher loop.
        callback: async function(filepath) to be called when a new file is ready.
        """
        self.running = True
        logger.info(f"FileWatcher started on: {self.watch_dir}")
        
        while self.running:
            try:
                # Run scan in thread to avoid blocking loop with I/O
                new_files = await asyncio.to_thread(self._scan)
                
                for filepath in new_files:
                    logger.info(f"New file detected: {filepath}")
                    # Check stability (file size not changing)
                    if await self._wait_for_stable(filepath):
                        try:
                            logger.info(f"File stable, triggering callback: {filepath}")
                            await callback(filepath)
                            self.processed_files.add(os.path.basename(filepath))
                            self._save_processed()
                        except Exception as cb_err:
                            logger.error(f"Callback failed for {filepath}: {cb_err}")
            
            except Exception as e:
                logger.error(f"FileWatcher Scan Error: {e}")
            
            await asyncio.sleep(self.check_interval)

    def _scan(self):
        """
        Scans directory for new files. 
        Returns list of absolute paths.
        """
        if not os.path.exists(self.watch_dir):
            logger.warning(f"Watch dir does not exist or inaccessible: {self.watch_dir}")
            return []

        found = []
        try:
            for filename in os.listdir(self.watch_dir):
                # Ignore hidden files or temp files
                if filename.startswith('.') or filename.endswith('.part') or filename.endswith('.ytdl'):
                    continue
                
                if filename not in self.processed_files:
                    full_path = os.path.join(self.watch_dir, filename)
                    if os.path.isfile(full_path):
                        found.append(full_path)
        except OSError as e:
            logger.error(f"OS Error scannng dir: {e}")
            
        return found

    async def _wait_for_stable(self, filepath, timeout=300):
        """
        Waits until file size is constant for 5 seconds.
        """
        last_size = -1
        stable_count = 0
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                size = os.path.getsize(filepath)
                if size == last_size:
                    stable_count += 1
                else:
                    stable_count = 0
                
                last_size = size
                
                if stable_count >= 5: # 5 seconds of stability
                    return True
                
                await asyncio.sleep(1)
            except OSError:
                return False
                
        logger.warning(f"File {filepath} timed out waiting for stability.")
        return False

    def stop(self):
        self.running = False
