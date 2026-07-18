"""날짜 파싱/정규화 유틸.

published_at은 소스별 포맷이 혼재한다 (텔레그램=ISO, 블로그 RSS=RFC822).
적재 시점에 ISO 8601(UTC)로 정규화해 SQL 정렬이 가능하게 한다.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# 시각 없는 날짜 문자열 폴백 (일부 RSS pubDate는 "Thu, 09 Jul 2026"처럼 날짜만 옴 —
# parsedate_to_datetime가 실패하므로 직접 시도)
_DATE_ONLY_FORMATS = ("%a, %d %b %Y", "%d %b %Y", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d")


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        try:
            dt = parsedate_to_datetime(s)
        except Exception:
            dt = None
        if dt is None:
            for fmt in _DATE_ONLY_FORMATS:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_iso_utc(s: str) -> str:
    """혼재 포맷 → ISO 8601 UTC 문자열. 파싱 실패 시 원본 유지."""
    dt = parse_dt(s)
    return dt.astimezone(timezone.utc).isoformat() if dt else (s or "")
