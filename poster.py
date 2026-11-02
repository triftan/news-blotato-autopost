"""Host slides on GitHub and post the carousel to Instagram through the Buffer API.

Buffer's API has no upload endpoint, so each slide is converted to JPEG and
committed to a separate `media` branch of this (public) repository. The raw
GitHub URLs are then handed to Buffer as image assets.
"""

import base64
import io
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

BUFFER_URL = "https://api.buffer.com"
GITHUB_API = "https://api.github.com"
MEDIA_BRANCH = "media"
REQUEST_TIMEOUT = 30
UPLOAD_TIMEOUT = 120


# ── Buffer ────────────────────────────────────────────────────────────────

def _buffer_headers() -> dict[str, str]:
    """Build API headers lazily so missing or whitespace-only secrets fail clearly."""
    api_key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BUFFER_API_KEY is missing or empty")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _short(text: str, limit: int = 500) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit] + "…" if len(text) > limit else text


def _graphql(query: str, variables: dict, action: str) -> dict:
    """Run one Buffer GraphQL call and return its `data`, raising on any error."""
    response = requests.post(
        BUFFER_URL,
        headers=_buffer_headers(),
        json={"query": query, "variables": variables},
        timeout=REQUEST_TIMEOUT,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(
            f"Buffer {action} failed (HTTP {response.status_code}): {_short(response.text)}"
        )
    body = response.json()
    if body.get("errors"):
        messages = "; ".join(str(e.get("message", e)) for e in body["errors"])
        raise RuntimeError(f"Buffer {action} failed: {_short(messages)}")
    return body.get("data") or {}


CHANNEL_QUERY = """
query Channel($id: ChannelId!) {
  channel(input: { id: $id }) {
    id
    name
    displayName
    service
    isDisconnected
    isLocked
  }
}
"""


def validate_account(channel_id: str, expected_username: Optional[str] = None) -> dict:
    """Verify the API key and that the channel is a connected Instagram account."""
    data = _graphql(CHANNEL_QUERY, {"id": channel_id}, "channel check")
    channel = data.get("channel")
    if not channel:
        raise RuntimeError(f"Buffer channel {channel_id} was not found for this API key")
    if str(channel.get("service", "")).lower() != "instagram":
        raise RuntimeError(
            f"Buffer channel {channel_id} is {channel.get('service')}, not Instagram"
        )
    if channel.get("isDisconnected"):
        raise RuntimeError(
            f"Buffer channel @{channel.get('name')} is disconnected. Reconnect it in Buffer."
        )
    if channel.get("isLocked"):
        raise RuntimeError(
            f"Buffer channel @{channel.get('name')} is locked (plan limit). Unlock it in Buffer."
        )
    if expected_username:
        actual = str(channel.get("name", "")).lstrip("@").lower()
        expected = expected_username.lstrip("@").lower()
        if actual != expected:
            # Buffer keeps the old name after an Instagram rename, so the channel id
            # is what counts. Warn instead of blocking the post.
            print(
                f"[poster] Note: Buffer shows this channel as @{actual or 'unknown'}, "
                f"config.json says @{expected}. Posting to channel {channel_id} anyway. "
                "Reconnect the channel in Buffer to refresh the name."
            )
    print(f"[poster] Buffer ready: Instagram @{channel.get('name')} (channel {channel_id})")
    return channel


# ── Image hosting on GitHub ──────────────────────────────────────────────

def _github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing; it is needed to host slides for Buffer")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _github_repo() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is missing; it is needed to host slides for Buffer")
    return repo


def _ensure_media_branch(repo: str) -> None:
    """Create the media branch from the default branch if it does not exist yet."""
    headers = _github_headers()
    ref = requests.get(
        f"{GITHUB_API}/repos/{repo}/git/ref/heads/{MEDIA_BRANCH}",
        headers=headers, timeout=REQUEST_TIMEOUT,
    )
    if ref.status_code == 200:
        return
    info = requests.get(f"{GITHUB_API}/repos/{repo}", headers=headers, timeout=REQUEST_TIMEOUT)
    info.raise_for_status()
    default = info.json()["default_branch"]
    head = requests.get(
        f"{GITHUB_API}/repos/{repo}/git/ref/heads/{default}",
        headers=headers, timeout=REQUEST_TIMEOUT,
    )
    head.raise_for_status()
    created = requests.post(
        f"{GITHUB_API}/repos/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{MEDIA_BRANCH}", "sha": head.json()["object"]["sha"]},
        timeout=REQUEST_TIMEOUT,
    )
    if created.status_code not in (201, 422):  # 422 = created by a parallel run
        raise RuntimeError(
            f"Could not create '{MEDIA_BRANCH}' branch (HTTP {created.status_code}): "
            f"{_short(created.text)}"
        )


def _to_jpeg_bytes(image_path: str) -> bytes:
    """Instagram only accepts JPEG, so convert the rendered PNG."""
    with Image.open(image_path) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, "JPEG", quality=92)
        return buffer.getvalue()


def upload_image(image_path: str, folder: str) -> str:
    """Commit one slide as JPEG to the media branch and return its public raw URL."""
    repo = _github_repo()
    name = Path(image_path).stem + ".jpg"
    repo_path = f"slides/{folder}/{name}"
    response = requests.put(
        f"{GITHUB_API}/repos/{repo}/contents/{repo_path}",
        headers=_github_headers(),
        json={
            "message": f"media: {folder}/{name} [skip ci]",
            "content": base64.b64encode(_to_jpeg_bytes(image_path)).decode(),
            "branch": MEDIA_BRANCH,
        },
        timeout=UPLOAD_TIMEOUT,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Slide upload to GitHub failed (HTTP {response.status_code}): {_short(response.text)}"
        )
    url = f"https://raw.githubusercontent.com/{repo}/{MEDIA_BRANCH}/{repo_path}"
    print(f"[poster] Hosted: {name} → {url}")
    return url


def upload_all_slides(image_paths: list[str], folder: str) -> list[str]:
    _ensure_media_branch(_github_repo())
    urls = [upload_image(path, folder) for path in image_paths]
    # Give raw.githubusercontent.com a moment so Buffer never fetches a 404.
    for url in urls:
        for _ in range(10):
            if requests.head(url, timeout=REQUEST_TIMEOUT).status_code == 200:
                break
            time.sleep(3)
        else:
            raise RuntimeError(f"Hosted slide is not reachable yet: {url}")
    return urls


# ── Posting ──────────────────────────────────────────────────────────────

def _limit_instagram_hashtags(caption: str, limit: int = 5) -> str:
    """Keep only the first few hashtags so the caption stays clean."""
    count = 0

    def keep_or_remove(match: re.Match) -> str:
        nonlocal count
        count += 1
        return match.group(0) if count <= limit else ""

    cleaned = re.sub(r"(?<!\w)#[\w]+", keep_or_remove, caption)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id status } }
    ... on MutationError { message }
  }
}
"""


def post_carousel(channel_id: str, caption: str, media_urls: list[str]) -> str:
    """Ask Buffer to publish the carousel now and return the Buffer post id."""
    variables = {
        "input": {
            "channelId": channel_id,
            "text": _limit_instagram_hashtags(caption),
            "schedulingType": "automatic",
            "mode": "shareNow",
            "needsApproval": False,
            "assets": [{"image": {"url": url}} for url in media_urls],
            "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}},
        }
    }
    data = _graphql(CREATE_POST_MUTATION, variables, "post submission")
    result = data.get("createPost") or {}
    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError(f"Buffer rejected the post: {result.get('message') or result}")
    print(f"[poster] Submitted! buffer_post_id={post['id']} status={post.get('status')}")
    return post["id"]


POST_STATUS_QUERY = """
query Post($id: PostId!) {
  post(input: { id: $id }) {
    id
    status
    externalLink
    error { message }
  }
}
"""


def wait_for_publication(post_id: str, timeout: int = 240, poll_interval: int = 10) -> dict:
    """Wait until Buffer reports the post as sent or failed."""
    deadline = time.monotonic() + timeout
    while True:
        data = _graphql(POST_STATUS_QUERY, {"id": post_id}, "post status check")
        post = data.get("post") or {}
        status = str(post.get("status", "")).lower()
        if status == "sent":
            print(f"[poster] Published! {post.get('externalLink') or '(URL pending)'}")
            return post
        if status == "error":
            message = (post.get("error") or {}).get("message") or "Unknown error"
            raise RuntimeError(f"Buffer publication failed: {message}")
        if status in ("draft", "needs_approval"):
            raise RuntimeError(f"Buffer saved post {post_id} as {status} instead of publishing")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Buffer post {post_id} is still '{status}' after {timeout}s")
        time.sleep(poll_interval)


def run(image_paths: list[str], caption: str, channel_id: str, folder: str) -> str:
    """Host all slides, submit the carousel, and return the Buffer post id."""
    print(f"[poster] Hosting {len(image_paths)} slides on GitHub ({MEDIA_BRANCH} branch)...")
    public_urls = upload_all_slides(image_paths, folder)
    print(f"[poster] Posting carousel to Buffer channel {channel_id}...")
    post_id = post_carousel(channel_id, caption, public_urls)
    wait_for_publication(post_id)
    return post_id


if __name__ == "__main__":
    print("[poster] Module loaded — run via pipeline.py")
