from datetime import datetime, timedelta
from database import get_connection


def is_cached(cache_key: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT expires_at FROM cache_meta WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    if row["expires_at"]:
        return datetime.fromisoformat(row["expires_at"]) > datetime.now()
    return True


def set_cache(cache_key: str, ttl_seconds: int):
    conn = get_connection()
    expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta (cache_key, fetched_at, expires_at) VALUES (?, datetime('now'), ?)",
        (cache_key, expires_at),
    )
    conn.commit()
    conn.close()


def invalidate_cache(cache_key: str):
    conn = get_connection()
    conn.execute("DELETE FROM cache_meta WHERE cache_key = ?", (cache_key,))
    conn.commit()
    conn.close()
