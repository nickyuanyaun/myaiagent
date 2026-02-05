
import json
import os
import logging
import uuid
import math

# Pure python cosine similarity if needed, or just keyword search + LLM ranking
# Since we lack numpy/chromadb, we will use a hybrid approach:
# 1. Simple keyword filter
# 2. Or just pass recent/all memories to Qwen if count is low.

logger = logging.getLogger(__name__)

class MemoryStore:
    def __init__(self, persistence_path="data/memory.json"):
        self.persistence_path = persistence_path
        self._ensure_dir()
        self.memories = self._load()

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
            logger.error(f"Failed to load memory: {e}")
            return []

    def _save(self):
        try:
            with open(self.persistence_path, 'w', encoding='utf-8') as f:
                json.dump(self.memories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def add_memory(self, text: str, metadata: dict = None):
        if metadata is None:
            metadata = {}
        
        entry = {
            "id": str(uuid.uuid4()),
            "text": text,
            "metadata": metadata,
            "timestamp": str(uuid.uuid1())
        }
        self.memories.append(entry)
        self._save()
        logger.info(f"Saved memory: {text}")

    def search_memory(self, query: str, n_results=5):
        """
        Naive search: Returns all memories. 
        We rely on QwenBrain to filter them or we implement a simple keyword match here.
        """
        # Simple Keyword Match
        keywords = query.lower().split()
        scored = []
        for mem in self.memories:
            score = 0
            content = mem['text'].lower()
            for kw in keywords:
                if kw in content:
                    score += 1
            if score > 0:
                scored.append((score, mem['text']))
        
        # Sort by score desc
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # If no keywords match, maybe return most recent?
        if not scored:
             # Return last 3
             return [m['text'] for m in self.memories[-3:]]
        
        return [s[1] for s in scored[:n_results]]

if __name__ == "__main__":
    ms = MemoryStore("data/test_mem.json")
    ms.add_memory("I like apples")
    print(ms.search_memory("Do I like apples?"))
