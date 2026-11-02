"""Track posted stories in posted_urls.json to avoid duplicates."""
from __future__ import annotations
import json
from datetime import datetime, timezone
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
    """Return all Pexels/og:image URLs used in past posts — to avoid reuse."""
    return set(_load().get("img_urls", []))


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
