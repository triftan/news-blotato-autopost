"""Upload slides and post carousels to Instagram via the Blotato REST API."""

import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://backend.blotato.com/v2"
REQUEST_TIMEOUT = 30
UPLOAD_TIMEOUT = 120


def _headers() -> dict[str, str]:
    """Build API headers lazily so missing or whitespace-only secrets fail clearly."""
    api_key = os.environ.get("BLOTATO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BLOTATO_API_KEY is missing or empty")
    return {"blotato-api-key": api_key, "Accept": "application/json"}


def _response_error(response: requests.Response, action: str) -> RuntimeError:
    """Return a useful API error without exposing credentials."""
    body = (getattr(response, "text", "") or "").strip().replace("\n", " ")
    if len(body) > 500:
        body = body[:500] + "…"
    detail = f": {body}" if body else ""
    return RuntimeError(f"Blotato {action} failed (HTTP {response.status_code}){detail}")


def _require_success(response: requests.Response, action: str) -> None:
    if not 200 <= response.status_code < 300:
        raise _response_error(response, action)


def validate_account(account_id: str, expected_username: Optional[str] = None) -> dict:
    """Verify the API key and configured Instagram account before expensive work."""
    response = requests.get(
        f"{BASE_URL}/users/me/accounts",
        headers=_headers(),
        params={"platform": "instagram"},
        timeout=REQUEST_TIMEOUT,
    )
    _require_success(response, "authentication check")
    accounts = response.json().get("items", [])
    account = next((item for item in accounts if str(item.get("id")) == str(account_id)), None)
    if account is None:
        available = ", ".join(
            f"{item.get('id')} (@{item.get('username', 'unknown')})" for item in accounts
        ) or "none"
        raise RuntimeError(
            f"Configured Instagram account {account_id} is not connected in Blotato. "
            f"Available Instagram accounts: {available}"
        )
    if expected_username:
        actual = str(account.get("username", "")).lstrip("@").lower()
        expected = expected_username.lstrip("@").lower()
        if actual != expected:
            raise RuntimeError(
                f"Blotato account {account_id} (@{actual or 'unknown'}) does not match "
                f"expected Instagram account @{expected}"
            )
    print(
        f"[poster] Blotato ready: Instagram @{account.get('username', 'unknown')} "
        f"(account {account_id})"
    )
    return account


def upload_image(image_path: str) -> str:
    """Upload one local image with Blotato's presigned-upload flow."""
    path = Path(image_path)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    response = requests.post(
        f"{BASE_URL}/media/uploads",
        headers=_headers(),
        json={"filename": path.name},
        timeout=REQUEST_TIMEOUT,
    )
    _require_success(response, "presigned upload creation")
    data = response.json()
    presigned_url = data.get("presignedUrl")
    public_url = data.get("publicUrl")
    if not presigned_url or not public_url:
        raise RuntimeError("Blotato upload response omitted presignedUrl or publicUrl")

    with path.open("rb") as image_file:
        put_response = requests.put(
            presigned_url,
            data=image_file,
            headers={"Content-Type": content_type},
            timeout=UPLOAD_TIMEOUT,
        )
    _require_success(put_response, "file upload")

    print(f"[poster] Uploaded: {path.name} → {public_url[:60]}...")
    return public_url


def upload_all_slides(image_paths: list[str]) -> list[str]:
    public_urls = []
    for path in image_paths:
        public_urls.append(upload_image(path))
        time.sleep(0.5)
    return public_urls


def _limit_instagram_hashtags(caption: str, limit: int = 5) -> str:
    """Keep only the first hashtags allowed by Blotato's Instagram validator."""
    count = 0

    def keep_or_remove(match: re.Match) -> str:
        nonlocal count
        count += 1
        return match.group(0) if count <= limit else ""

    cleaned = re.sub(r"(?<!\w)#[\w]+", keep_or_remove, caption)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def post_carousel(account_id: str, caption: str, media_urls: list[str]) -> str:
    """Submit an Instagram carousel and return its Blotato submission ID."""
    payload = {
        "post": {
            "accountId": account_id,
            "content": {
                "platform": "instagram",
                "text": _limit_instagram_hashtags(caption),
                "mediaUrls": media_urls,
            },
            "target": {"targetType": "instagram"},
        }
    }
    response = requests.post(
        f"{BASE_URL}/posts",
        headers={**_headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    _require_success(response, "post submission")
    submission_id = response.json().get("postSubmissionId")
    if not submission_id:
        raise RuntimeError("Blotato accepted the request but returned no postSubmissionId")
    print(f"[poster] Submitted! submission_id={submission_id}")
    return submission_id


def wait_for_publication(
    submission_id: str,
    timeout: int = 180,
    poll_interval: int = 10,
) -> dict:
    """Wait until Blotato confirms the post is published or failed."""
    deadline = time.monotonic() + timeout
    while True:
        response = requests.get(
            f"{BASE_URL}/posts/{submission_id}",
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        _require_success(response, "post status check")
        data = response.json()
        state = data.get("state") if isinstance(data.get("state"), dict) else {}
        status = str(data.get("status") or state.get("type") or "").lower()

        if status == "published":
            public_url = data.get("publicUrl") or state.get("publicUrl")
            print(f"[poster] Published! {public_url or '(URL pending)'}")
            return data
        if status == "scheduled":
            raise RuntimeError(
                f"Blotato unexpectedly scheduled immediate submission {submission_id}"
            )
        if status == "failed":
            message = data.get("errorMessage") or state.get("errorMessage") or "Unknown error"
            raise RuntimeError(f"Blotato publication failed: {message}")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Blotato submission {submission_id} is still in progress after {timeout}s"
            )
        time.sleep(poll_interval)


def run(image_paths: list[str], caption: str, account_id: str) -> str:
    """Upload all slides, submit the carousel, and return its submission ID."""
    print(f"[poster] Uploading {len(image_paths)} slides...")
    public_urls = upload_all_slides(image_paths)
    print(f"[poster] Posting carousel to account {account_id}...")
    submission_id = post_carousel(account_id, caption, public_urls)
    wait_for_publication(submission_id)
    return submission_id


if __name__ == "__main__":
    print("[poster] Module loaded — run via pipeline.py")
