
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
                 if not isinstance(mem, dict): continue
                 # Check if metadata exists and matches
                 meta = mem.get('metadata', {})
                 if not isinstance(meta, dict): continue
                 
                 # Comparison: handle both int and str in storage
                 stored_uid = meta.get('user_id')
                 if stored_uid is not None and str(stored_uid) == current_uid_str:
                      relevant_memories.append(mem)
             
             logger.info(f"SEARCH DEBUG: User {user_id} | Total Mem: {len(self.memories)} | Match: {len(relevant_memories)}")
        else:
             relevant_memories = [m for m in self.memories if isinstance(m, dict)]
             logger.warning("SEARCH DEBUG: No user_id provided! Searching ALL memories.")
        
        # Identity Heuristic: If query asks "who am I" etc, prioritize identity facts
        identity_keywords = ["谁", "名字", "who", "name", "identity", "记忆"]
        is_identity_query = any(k in query.lower() for k in identity_keywords)

        for mem in relevant_memories:
            score = 0
            text_val = mem.get('text', '')
            if not isinstance(text_val, str): continue
            content = text_val.lower()
            
            if is_chinese:
                q_chars = set(query)
                c_chars = set(content)
                overlap = len(q_chars.intersection(c_chars))
                if overlap > 0:
                    score = overlap
            else:
                keywords = query.lower().split()
                for kw in keywords:
                    if kw in content:
                        score += 5 # Higher weight for word match
            
            # Identity Bonus
            if is_identity_query:
                 if any(k in content for k in ["name is", "名字是", "我是", "昵称", "id是"]):
                      score += 10
            
            if score > 0:
                scored.append((score, text_val))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # If no keywords match, or for identity queries, return a broader window
        if not scored or is_identity_query:
             # Mix of Identity facts and Most Recent
             results = []
             if is_identity_query:
                  # Find memories that look like profile facts
                  for m in relevant_memories:
                       txt = m.get('text', '')
                       if any(k in txt.lower() for k in ["name is", "名字是", "我是", "昵称", "id是"]):
                            results.append(txt)
                  results = results[:5]
             
             # Fill/Add most recent
             recent = [m.get('text', '') for m in relevant_memories if isinstance(m, dict)]
             recent.reverse() # Newest first
             for r in recent:
                  if r and r not in results:
                       results.append(r)
                  if len(results) >= 20: break
             
             return results
        
        return [s[1] for s in scored[:n_results]]

if __name__ == "__main__":
    ms = MemoryStore("data/test_mem.json")
    ms.add_memory("I like apples")
    print(ms.search_memory("Do I like apples?"))
