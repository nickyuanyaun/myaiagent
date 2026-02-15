"""
Test BlogMediaStore functionality.
Run: python test_blog_media_store.py
"""
import os
import sys
import shutil

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blog_media_store import BlogMediaStore

TEST_DIR = "data/_test_blog_media"
TEST_META = "data/_test_blog_media.json"

def cleanup():
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    if os.path.exists(TEST_META):
        os.remove(TEST_META)

def test_add_and_get():
    store = BlogMediaStore(media_dir=TEST_DIR, metadata_path=TEST_META)
    
    # Simulate two images
    img1 = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
    img2 = b'\x89PNG\r\n\x1a\n' + b'\xff' * 200
    
    mid1 = store.add_media(img1, "photo1.jpg", chat_id=12345, caption="博客素材")
    mid2 = store.add_media(img2, "photo2.png", chat_id=12345, caption="第二张")
    
    assert mid1 is not None, "add_media should return media_id"
    assert mid2 is not None
    
    # Count
    assert store.get_media_count(12345) == 2, f"Expected 2 pending, got {store.get_media_count(12345)}"
    
    # Other chat should have 0
    assert store.get_media_count(99999) == 0
    
    # Get pending
    pending = store.get_pending_media(12345)
    assert len(pending) == 2, f"Expected 2 pending entries, got {len(pending)}"
    
    # Read bytes
    data = store.get_media_bytes(mid1)
    assert data == img1, "Read bytes should match written bytes"
    
    print("✅ test_add_and_get PASSED")

def test_publish_and_delete():
    store = BlogMediaStore(media_dir=TEST_DIR, metadata_path=TEST_META)
    
    img = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
    mid = store.add_media(img, "blog_img.jpg", chat_id=55555)
    
    # Verify file exists
    entry = store.get_pending_media(55555)[0]
    assert os.path.exists(entry["filepath"]), "File should exist on disk"
    
    # Mark published
    count = store.mark_published(55555)
    assert count == 1, f"Expected 1 published, got {count}"
    
    # Pending should be 0 now
    assert store.get_media_count(55555) == 0
    
    # Published should be 1
    published = store.get_published_media(55555)
    assert len(published) == 1
    
    # Delete published
    deleted = store.delete_published(55555)
    assert deleted == 1, f"Expected 1 deleted, got {deleted}"
    
    # File should no longer exist
    assert not os.path.exists(entry["filepath"]), "File should be deleted from disk"
    
    # Published should be 0
    assert len(store.get_published_media(55555)) == 0
    
    print("✅ test_publish_and_delete PASSED")

def test_persistence():
    """Test that data survives reload."""
    store1 = BlogMediaStore(media_dir=TEST_DIR, metadata_path=TEST_META)
    img = b'\x89PNG' + b'\x42' * 80
    mid = store1.add_media(img, "persist.png", chat_id=77777)
    
    # Create new instance (simulates restart)
    store2 = BlogMediaStore(media_dir=TEST_DIR, metadata_path=TEST_META)
    assert store2.get_media_count(77777) == 1, "Data should persist across instances"
    
    data = store2.get_media_bytes(mid)
    assert data == img, "File content should persist"
    
    print("✅ test_persistence PASSED")

def test_multi_chat_isolation():
    """Test that different chats don't see each other's media."""
    store = BlogMediaStore(media_dir=TEST_DIR, metadata_path=TEST_META)
    
    store.add_media(b'\x00' * 10, "chatA.jpg", chat_id=111)
    store.add_media(b'\x00' * 10, "chatB.jpg", chat_id=222)
    
    assert store.get_media_count(111) >= 1
    assert store.get_media_count(222) >= 1
    
    # Publishing chat 111 should not affect chat 222
    store.mark_published(111)
    assert store.get_media_count(111) == 0
    assert store.get_media_count(222) >= 1  # chat 222 unaffected
    
    print("✅ test_multi_chat_isolation PASSED")

if __name__ == "__main__":
    cleanup()
    try:
        test_add_and_get()
        cleanup()
        
        test_publish_and_delete()
        cleanup()
        
        test_persistence()
        cleanup()
        
        test_multi_chat_isolation()
        cleanup()
        
        print("\n🎉 All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        cleanup()
