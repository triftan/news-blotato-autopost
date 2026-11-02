"""Stop a fresh template from posting until config.json is filled in.

No third-party imports, so the GitHub Actions guard can run before pip install.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MARKERS = (
    "YOUR_BLOTATO_INSTAGRAM_ACCOUNT_ID",
    "YOUR_INSTAGRAM_USERNAME",
    "YOUR_BRAND_NAME",
    "YOUR_COMMUNITY_URL",
    "YOUR_COMMENT_KEYWORD",
    "YOUR_INSTAGRAM_HANDLE",
)

FIELDS = (
    ("blotato.instagram_account_id", ("blotato", "instagram_account_id")),
    ("blotato.instagram_username", ("blotato", "instagram_username")),
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
        if label == "blotato.instagram_account_id" and not value.isdigit():
            found.append(label)
    return found


def friendly_message(fields: list[str]) -> str:
    listed = ", ".join(fields)
    return (
        "config.json still has template placeholders in: "
        f"{listed}. Open config.json and replace them with your Blotato Instagram "
        "account id, Instagram username, brand name, handle, community link, and "
        "comment keyword. The Malaysia news searches in that file are examples — edit those too. "
        "Live posting stays off until blotato.instagram_account_id is the numeric id of an "
        "Instagram account connected in Blotato. If preflight fails after you set an id, "
        "that id does not match a connected account."
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
            "blotato.instagram_account_id is your real Blotato Instagram account id."
        )
        return 0

    _set_output("skip", "false")
    print(f"::error::{message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
