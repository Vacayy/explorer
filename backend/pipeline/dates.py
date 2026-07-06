"""날짜 파싱/정규화 유틸.

published_at은 소스별 포맷이 혼재한다 (텔레그램=ISO, 블로그 RSS=RFC822).
적재 시점에 ISO 8601(UTC)로 정규화해 SQL 정렬이 가능하게 한다.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_iso_utc(s: str) -> str:
    """혼재 포맷 → ISO 8601 UTC 문자열. 파싱 실패 시 원본 유지."""
    dt = parse_dt(s)
    return dt.astimezone(timezone.utc).isoformat() if dt else (s or "")
