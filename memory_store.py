
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

    def search_memory(self, query: str, user_id=None, n_results=5):
        """
        Naive search: Returns all memories for a specific user. 
        We rely on QwenBrain to filter them or we implement a simple keyword match here.
        """
        # Simple Keyword Match (Enhanced for Chinese)
        is_chinese = False
        if len(query) > 0 and ' ' not in query:
             # Heuristic: if no spaces, likely CJK or single word.
             # Check for CJK range (optional but simple check is okay)
             for char in query:
                 if '\u4e00' <= char <= '\u9fff':
                     is_chinese = True
                     break
        
        scored = []
        
        # Filter by user_id first
        relevant_memories = []
        if user_id:
             current_uid_str = str(user_id)
             for mem in self.memories:
                 # Check if metadata exists and matches
                 meta = mem.get('metadata', {})
                 stored_uid = str(meta.get('user_id', 'None'))
                 
                 # PARANOID DEBUGGING
                 # logger.info(f"Compare: Stored '{stored_uid}' vs Req '{current_uid_str}' -> {stored_uid == current_uid_str}")
                 
                 if stored_uid == current_uid_str:
                     relevant_memories.append(mem)
             
             logger.info(f"SEARCH DEBUG: User {user_id} | Total Mem: {len(self.memories)} | Match: {len(relevant_memories)}")
        else:
             # Fallback if no user_id provided (dev mode), search all
             relevant_memories = self.memories
             logger.warning("SEARCH DEBUG: No user_id provided! Searching ALL memories.")
        
        # Log the content of matches to ensure no contamination
        if relevant_memories:
            logger.info(f"SEARCH MATCHES: {[m['text'][:20] for m in relevant_memories]}")

        for mem in relevant_memories:
            score = 0
            content = mem['text'].lower()
            
            if is_chinese:
                # Char-level overlap for Chinese
                q_chars = set(query)
                c_chars = set(content)
                overlap = len(q_chars.intersection(c_chars))
                if overlap > 0:
                    score = overlap
            else:
                # Standard keyword match for space-delimited langs
                keywords = query.lower().split()
                for kw in keywords:
                    if kw in content:
                        score += 1
            
            if score > 0:
                scored.append((score, mem['text']))
        
        # Sort by score desc
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # If no keywords match, maybe return most recent?
        if not scored:
             # Return last 3 from RELEVANT filtered memories only
             return [m['text'] for m in relevant_memories[-3:]]
        
        return [s[1] for s in scored[:n_results]]

if __name__ == "__main__":
    ms = MemoryStore("data/test_mem.json")
    ms.add_memory("I like apples")
    print(ms.search_memory("Do I like apples?"))
