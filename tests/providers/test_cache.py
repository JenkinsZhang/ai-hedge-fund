import time

import pytest

from src.tools.providers._cache import Cache


def test_cache_set_and_get(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("key1", [1, 2, 3], ttl_seconds=60)
    assert cache.get("key1") == [1, 2, 3]


def test_cache_miss_returns_none(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    assert cache.get("missing") is None


def test_cache_respects_ttl(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("expiring", "v", ttl_seconds=0)  # 0 means forever in our schema
    assert cache.get("expiring") == "v"


def test_cache_expired_entry_returns_none(temp_cache_dir, monkeypatch):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("short", "v", ttl_seconds=1)
    fake_now = time.time() + 100
    monkeypatch.setattr(time, "time", lambda: fake_now)
    assert cache.get("short") is None


def test_cache_overwrite(temp_cache_dir):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("k", "v1", ttl_seconds=60)
    cache.set("k", "v2", ttl_seconds=60)
    assert cache.get("k") == "v2"


def test_cache_creates_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    cache = Cache(nested / "test.db")
    cache.set("k", 1, ttl_seconds=60)
    assert cache.get("k") == 1


def test_cache_get_returns_none_on_unpickle_failure(temp_cache_dir, caplog):
    cache = Cache(temp_cache_dir / "test.db")
    cache.set("k", "valid", ttl_seconds=60)
    # Corrupt the stored blob so pickle.loads fails
    cache._conn.execute("UPDATE cache SET value = ? WHERE key = ?", (b"not-pickle", "k"))
    with caplog.at_level("WARNING"):
        assert cache.get("k") is None
    assert any("Cache get failed" in r.message for r in caplog.records)
