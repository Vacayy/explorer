import re

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def scrape_channel(channel_name: str) -> list[dict]:
    """Scrape latest messages from a public Telegram channel.

    Uses t.me/s/{channel_name} preview page.
    Only works for PUBLIC channels with preview enabled.
    """
    url = f"https://t.me/s/{channel_name}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
    except Exception:
        return []

    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    messages = []

    for bubble in soup.find_all("div", class_="tgme_widget_message_bubble"):
        # 본문 = js-message_text. 답글 메시지는 인용문 div(js-message_reply_text)도
        # tgme_widget_message_text 클래스를 가져, generic first-match면 잘린 인용문("…")을
        # 본문으로 오인한다 → 원문 유실. js-message_text로 실제 본문만 타겟 (D-103).
        text_div = bubble.find("div", class_="js-message_text")
        time_el = bubble.find("time")

        parent = bubble.find_parent("div", class_="tgme_widget_message")
        msg_link = parent.get("data-post", "") if parent else ""

        content = _extract_text_with_breaks(text_div) if text_div else ""
        date = time_el.get("datetime", "") if time_el else ""
        msg_id = msg_link.split("/")[-1] if "/" in msg_link else msg_link

        # 첨부 이미지 (증시일정 짤 등) — background-image CDN URL 추출
        images = []
        for photo in bubble.find_all("a", class_="tgme_widget_message_photo_wrap"):
            m = re.search(r"url\('([^']+)'\)", photo.get("style", ""))
            if m:
                images.append(m.group(1))

        # 이미지만 있는 메시지(텍스트 없음)도 수집한다
        if content or images:
            messages.append({
                "message_id": msg_id,
                "content": content,
                "date": date,
                "link": f"https://t.me/{msg_link}" if msg_link else "",
                "images": images,
            })

    return messages


def fetch_message_body(channel: str, msg_id: str) -> str | None:
    """개별 메시지 본문(js-message_text) 전문 — 백필용(D-103). 실패/본문없음이면 None."""
    url = f"https://t.me/{channel}/{msg_id}?embed=1&mode=tme"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    td = soup.find("div", class_="js-message_text")
    return _extract_text_with_breaks(td) if td else None


def _extract_text_with_breaks(element) -> str:
    """Extract text preserving intentional line breaks only.

    <br> tags → newline
    Block elements (div, p) → newline before
    Inline elements (b, i, a, span, em, code) → no extra newline
    """
    import re
    from copy import copy

    # Work on a copy to avoid mutating the original
    el = copy(element)

    # Replace <br> with newline marker
    for br in el.find_all("br"):
        br.replace_with("\n")

    # Add newline before block-level elements
    for tag_name in ["div", "p", "blockquote", "ul", "ol", "li", "pre"]:
        for tag in el.find_all(tag_name):
            tag.insert_before("\n")
            tag.insert_after("\n")

    text = el.get_text()

    # Clean up: collapse 3+ newlines to 2, strip trailing spaces per line
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_channel_display_name(channel_name: str) -> str | None:
    """Fetch the display name / title of a public Telegram channel."""
    url = f"https://t.me/s/{channel_name}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    title_el = soup.find("div", class_="tgme_channel_info_header_title")
    if title_el:
        return title_el.get_text(strip=True)
    return None
