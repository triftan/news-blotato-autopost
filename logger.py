"""Track posted stories in posted_urls.json to avoid duplicates."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOG_FILE = Path(__file__).parent / "posted_urls.json"


def _load() -> dict:
    if not _LOG_FILE.exists():
        return {"urls": [], "posts": []}
    try:
        return json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"urls": [], "posts": []}


def get_posted_urls() -> set:
    return set(_load().get("urls", []))


def get_used_img_urls() -> set:
    """Return all Pixabay/og:image URLs used in past posts — to avoid reuse."""
    return set(_load().get("img_urls", []))


def get_recent_topics(days: int = 7) -> list[str]:
    """Headlines of stories posted (or queued) in the last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for item in _load().get("topic_history", []):
        try:
            when = datetime.fromisoformat(item["date"])
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when >= cutoff:
            out.append(item.get("headline", ""))
    return [h for h in out if h]


def get_recent_angles(n: int = 3) -> list[str]:
    """Hook angles of the last n posts, newest first (used to rotate angles)."""
    history = _load().get("angle_history", [])
    return list(reversed(history[-n:]))


def get_last_post_time() -> datetime | None:
    """Return UTC datetime of the most recent post, or None if no posts yet."""
    posts = _load().get("posts", [])
    if not posts:
        return None
    try:
        return datetime.fromisoformat(posts[-1]["posted_at"])
    except Exception:
        return None


def hours_since_last_post() -> float:
    """Return hours elapsed since the last post. Returns 999 if never posted."""
    last = get_last_post_time()
    if last is None:
        return 999.0
    delta = datetime.now(timezone.utc) - last
    return delta.total_seconds() / 3600


def log_posted(story: dict, ig_post_id: str, carousel: dict, new_img_urls: set | None = None):
    data = _load()
    data.setdefault("urls", [])
    data.setdefault("posts", [])
    data.setdefault("img_urls", [])

    if story["url"] not in data["urls"]:
        data["urls"].append(story["url"])

    for u in (new_img_urls or set()):
        if u not in data["img_urls"]:
            data["img_urls"].append(u)

    data.setdefault("topic_history", []).append({
        "headline": story["headline"][:140],
        "date": datetime.now(timezone.utc).isoformat(),
    })

    angle = str(carousel.get("angle_name") or "").strip().upper()
    if angle:
        data.setdefault("angle_history", []).append(angle)

    data["posts"].append({
        "url": story["url"],
        "headline": story["headline"][:80],
        "ig_post_id": ig_post_id,
        "posted_at": datetime.now(timezone.utc).isoformat(),
    })

    _LOG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"[logger] Logged: {story['headline'][:60]}")


if __name__ == "__main__":
    print(f"[logger] {len(get_posted_urls())} stories posted")
    print(f"[logger] Hours since last post: {hours_since_last_post():.1f}h")
