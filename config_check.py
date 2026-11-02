"""Stop a fresh template from posting until config.json is filled in.

No third-party imports, so the GitHub Actions guard can run before pip install.
"""
from __future__ import annotations

import json
import re
import os
import sys
from pathlib import Path

MARKERS = (
    "YOUR_BUFFER_CHANNEL_ID",
    "YOUR_INSTAGRAM_USERNAME",
    "YOUR_BRAND_NAME",
    "YOUR_COMMUNITY_URL",
    "YOUR_COMMENT_KEYWORD",
    "YOUR_INSTAGRAM_HANDLE",
)

FIELDS = (
    ("buffer.channel_id", ("buffer", "channel_id")),
    ("buffer.instagram_username", ("buffer", "instagram_username")),
    ("account_handle", ("account_handle",)),
    ("community_name", ("community_name",)),
    ("community_url", ("community_url",)),
    ("comment_keyword", ("comment_keyword",)),
)


def load_config(path: str | Path = "config.json") -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _dig(cfg: dict, path: tuple[str, ...]) -> str:
    current = cfg
    for key in path:
        current = current[key]
    return str(current)


def placeholder_fields(cfg: dict) -> list[str]:
    """Return config fields that are still template placeholders."""
    found = []
    for label, path in FIELDS:
        try:
            value = _dig(cfg, path).strip()
        except (KeyError, TypeError):
            found.append(label)
            continue
        if not value or "YOUR_" in value or any(marker in value for marker in MARKERS):
            found.append(label)
            continue
        if label == "buffer.channel_id" and not re.fullmatch(r"[0-9a-f]{24}", value):
            found.append(label)
    return found


def friendly_message(fields: list[str]) -> str:
    listed = ", ".join(fields)
    return (
        "config.json still has template placeholders in: "
        f"{listed}. Open config.json and replace them with your Buffer Instagram "
        "channel id, Instagram username, brand name, handle, community link, and "
        "comment keyword. The Malaysia news searches in that file are examples — edit those too. "
        "Live posting stays off until buffer.channel_id is the 24-character id of an "
        "Instagram channel connected in Buffer. If preflight fails after you set an id, "
        "that id does not match a connected channel."
    )


def guard_unconfigured(cfg: dict) -> str | None:
    """Return 'skip' on a scheduled fresh copy, 'fail' otherwise, or None when ready."""
    if not placeholder_fields(cfg):
        return None
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        return "skip"
    return "fail"


def _set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def main() -> int:
    fields = placeholder_fields(load_config())
    if not fields:
        _set_output("skip", "false")
        print("config.json has no template placeholders.")
        return 0

    message = friendly_message(fields)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        _set_output("skip", "true")
        print(message)
        print(
            "Scheduled run skipped. A fresh copy does not post until "
            "every placeholder in config.json is filled in."
        )
        return 0

    _set_output("skip", "false")
    print(f"::error::{message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
