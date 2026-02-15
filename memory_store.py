
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

    def search_memory(self, query: str, user_id=None, n_results=10):
        """
        Search memories with improved Chinese support and cross-user access.
        Same-user memories get a score boost, but all memories are searchable.
        Always includes recent memories for broader context.
        """
        if not self.memories:
            return []
        
        # Detect Chinese text
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)
        
        scored = []
        current_uid_str = str(user_id) if user_id else None
        
        for mem in self.memories:
            if not isinstance(mem, dict): continue
            text_val = mem.get('text', '')
            if not isinstance(text_val, str) or not text_val: continue
            content = text_val.lower()
            query_lower = query.lower()
            score = 0
            
            # --- Keyword Matching ---
            if is_chinese:
                # Direct substring match (most important for Chinese)
                if query_lower in content:
                    score += 20
                
                # Bigram matching for Chinese characters
                q_chars = [c for c in query if '\u4e00' <= c <= '\u9fff']
                c_chars_set = set(content)
                
                # Single char overlap
                char_overlap = sum(1 for c in q_chars if c in c_chars_set)
                if char_overlap > 0:
                    score += char_overlap * 2
                
                # Bigram matching (pairs of adjacent chars)
                if len(q_chars) >= 2:
                    q_bigrams = set(q_chars[i] + q_chars[i+1] for i in range(len(q_chars)-1))
                    c_text = ''.join(c for c in content if '\u4e00' <= c <= '\u9fff')
                    c_bigrams = set(c_text[i] + c_text[i+1] for i in range(len(c_text)-1)) if len(c_text) >= 2 else set()
                    bigram_overlap = len(q_bigrams.intersection(c_bigrams))
                    score += bigram_overlap * 3
            else:
                # English word matching
                keywords = query_lower.split()
                for kw in keywords:
                    if len(kw) > 2 and kw in content:
                        score += 5
            
            # --- Identity Bonus ---
            identity_keywords = ["谁", "名字", "who", "name", "我是", "你是", "叫什么", "记得", "记忆", "宠物", "狗"]
            if any(k in query_lower for k in identity_keywords):
                identity_content_keys = ["name is", "名字是", "我是", "昵称", "叫做", "宠物", "pet", "dog", "狗", "金毛", "马尔泰"]
                if any(k in content for k in identity_content_keys):
                    score += 15
            
            # --- Same-User Boost (not filter) ---
            if current_uid_str:
                meta = mem.get('metadata', {})
                if isinstance(meta, dict):
                    stored_uid = meta.get('user_id')
                    if stored_uid is not None and str(stored_uid) == current_uid_str:
                        score += 3  # Boost, not required
            
            if score > 0:
                scored.append((score, text_val))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Get top scored results
        results = [s[1] for s in scored[:n_results]]
        
        # Always include recent memories for broader context
        recent = [m.get('text', '') for m in reversed(self.memories) if isinstance(m, dict)]
        for r in recent:
            if r and r not in results:
                results.append(r)
            if len(results) >= 20:
                break
        
        logger.info(f"SEARCH: query='{query}' | scored={len(scored)} | returning={len(results)}")
        return results

if __name__ == "__main__":
    ms = MemoryStore("data/test_mem.json")
    ms.add_memory("I like apples")
    print(ms.search_memory("Do I like apples?"))
