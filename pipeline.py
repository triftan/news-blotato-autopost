"""
Main pipeline orchestrator:
  scraper → selector (OpenRouter) → image_gen (Pixabay) → builder → Buffer → logger
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import builder
import config_check
import image_gen
import logger
import poster
import scraper
import selector


def check_visual_quality(image_sources: list[str], dry_run: bool) -> int:
    """Block live publication when too many slides lack photographic backgrounds."""
    gradient_count = image_sources.count("gradient")
    if gradient_count:
        print(f"[pipeline] Visual quality warning: {gradient_count}/10 slides use gradients")
    if not dry_run and gradient_count > 2:
        raise RuntimeError(
            "Visual quality gate blocked publication: "
            f"{gradient_count}/10 slides have no photographic background. "
            "Configure PIXABAY_API_KEY, then run a dry run first."
        )
    return gradient_count


def _half_year_periods(text: str) -> set[tuple[int, str]]:
    """Extract half-year references such as 1H2026, H1 2026, or 2H-2025."""
    periods = set()
    pattern = r"\b(?:(1|2)H|H(1|2))[-\s]?(20\d{2})\b"
    for first, second, year in re.findall(pattern, text, re.I):
        periods.add((int(first or second), year))
    return periods


def validate_carousel_facts(story: dict, carousel: dict) -> None:
    """Block deterministic date-period conflicts before rendering or posting."""
    source_text = " ".join(str(story.get(key, "")) for key in ("headline", "summary"))
    source_periods = _half_year_periods(source_text)
    if not source_periods:
        return
    carousel_periods = _half_year_periods(json.dumps(carousel, ensure_ascii=False))
    conflicts = carousel_periods - source_periods
    if conflicts:
        raise ValueError(
            "Carousel period conflicts with source headline: "
            f"source={sorted(source_periods)}, carousel={sorted(carousel_periods)}"
        )


def write_review_manifest(
    png_paths: list[str],
    story: dict,
    carousel: dict,
    image_sources: list[str],
    run_id: str,
) -> str:
    """Save the exact story, caption, and source list beside inspected slide PNGs."""
    if not png_paths:
        raise ValueError("Cannot write review manifest without slide PNGs")
    path = Path(png_paths[0]).parent / "review_manifest.json"
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "story": story,
                "carousel": carousel,
                "image_sources": image_sources,
                "slides": [Path(item).name for item in png_paths],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"[pipeline] Review manifest: {path}")
    return str(path)


def is_news_carousel(post: dict, cfg: dict) -> bool:
    """True for posts this bot makes (or that use its caption), not the owner's own reels/stories."""
    marker = f'Comment "{cfg.get("comment_keyword", "AI")}" to join'
    return marker in str(post.get("text", ""))


def posts_already_today(cfg: dict, channel_id: str) -> list[dict]:
    """News carousels scheduled/sent for this channel on today's local date.

    The owner's own reels and stories don't count, so they never block the daily post.
    """
    tz = ZoneInfo(cfg.get("timezone", "Asia/Singapore"))
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    posts = poster.posts_between(channel_id, start.isoformat(), end.isoformat())
    return [p for p in posts if is_news_carousel(p, cfg)]


def scheduled_post_time(cfg: dict, now: datetime | None = None) -> str | None:
    """Today's posting time (config post_time, local timezone) as ISO, or None to post now.

    The run starts early and schedules the post in Buffer, so GitHub's late
    starts don't move the posting time. If the run is already past the
    posting time (or within 10 minutes of it), post right away.
    """
    post_time = str(cfg.get("post_time", "")).strip()
    if not post_time:
        return None
    tz = ZoneInfo(cfg.get("timezone", "Asia/Singapore"))
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    hour, minute = (int(x) for x in post_time.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due - now < timedelta(minutes=10):
        return None
    return due.isoformat()


def buffer_topics(cfg: dict, channel_id: str) -> list[str]:
    """First caption line of Buffer posts from 7 days back to 7 days ahead.

    Covers posts queued by hand in Buffer, so the bot does not repeat their topic.
    """
    if not os.environ.get("BUFFER_API_KEY", "").strip():
        return []
    now = datetime.now(timezone.utc)
    try:
        posts = poster.posts_between(
            channel_id, (now - timedelta(days=7)).isoformat(), (now + timedelta(days=7)).isoformat()
        )
    except Exception as e:
        print(f"[pipeline] Could not read Buffer posts for the topic check ({e})")
        return []
    topics = []
    for p in posts:
        first = next((line.strip() for line in str(p.get("text", "")).splitlines() if line.strip()), "")
        if first:
            topics.append(first[:140])
    print(f"[pipeline] {len(topics)} Buffer posts in the last/next 7 days added to the topic check")
    return topics


def run_manual(spec_path: str, cfg: dict, account_id: str, dry_run: bool, buffer_draft: bool) -> None:
    """Build (and optionally post or schedule) a hand-written carousel.

    The spec is a JSON file committed to the repo with: story, carousel (cover
    text, 8 slides, caption), images (10 entries, see image_gen.images_from_spec)
    and an optional due_at (ISO time) to schedule instead of posting now.
    """
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    story = spec["story"]
    story.setdefault("category", "global_ai")
    carousel = selector._strip_dashes(spec["carousel"])
    carousel["caption"] = selector.ensure_caption_cta(
        carousel.get("caption", ""), local=story["category"] == "local"
    )
    run_id = spec.get("run_id") or f"manual_{Path(spec_path).stem}"
    print(f"\n── MANUAL CAROUSEL: {story.get('headline', run_id)[:70]} ──")

    image_paths, new_img_urls, image_sources = image_gen.images_from_spec(
        spec.get("images", []), f"/tmp/carousel_imgs_{run_id}", logger.get_used_img_urls()
    )
    png_paths = builder.run(carousel, image_paths, run_id)
    write_review_manifest(png_paths, story, carousel, image_sources, run_id)
    if dry_run:
        print(f"\n[pipeline] DRY RUN: manual carousel built, nothing posted. PNGs: ~/Downloads/carousels/{run_id}/")
        return

    due_at = spec.get("due_at")
    post_id = poster.run(png_paths, carousel["caption"], account_id, run_id,
                         draft=buffer_draft, due_at=due_at)
    if buffer_draft:
        print(f"\n✓ BUFFER DRAFT SAVED (nothing published): {post_id}")
        return
    story["buffer_channel_id"] = account_id
    logger.log_posted(story, post_id, carousel, new_img_urls=new_img_urls)
    print(f"\n✓ DONE: {'scheduled for ' + due_at if due_at else 'posted'} ({post_id})")


def run(dry_run: bool = False, force_local: bool = False, buffer_draft: bool = False,
        story_url: str = "", manual_spec: str = ""):
    with open("config.json", encoding="utf-8") as config_file:
        cfg = json.load(config_file)
    account_id = cfg["buffer"]["channel_id"]
    account_username = cfg["buffer"]["instagram_username"]
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    # A fresh template must not spend API credits or post under placeholder brand values.
    action = config_check.guard_unconfigured(cfg)
    if action:
        print(config_check.friendly_message(config_check.placeholder_fields(cfg)))
        if action == "skip":
            print("[pipeline] Scheduled run skipped. Nothing was posted.")
            return
        sys.exit(1)

    # Fail before scraping, AI calls, and rendering if Buffer is unavailable.
    if not dry_run:
        print("\n── STEP 0: BUFFER PREFLIGHT ──")
        poster.validate_account(account_id, account_username)

    if manual_spec:
        run_manual(manual_spec, cfg, account_id, dry_run, buffer_draft)
        return

    if not dry_run and not buffer_draft and not story_url:
        print("\n── ONE POST PER DAY CHECK ──")
        try:
            existing = posts_already_today(cfg, account_id)
        except Exception as e:
            existing = []
            print(f"[pipeline] Could not check Buffer for today's posts ({e}); continuing.")
        if existing:
            first = existing[0]
            print(
                f"[pipeline] Buffer already has a post for today ({first.get('status')} at "
                f"{first.get('dueAt')}): {str(first.get('text', ''))[:60]!r}. Skipping, one post per day."
            )
            return

    if story_url:
        print("\n── STEP 1: STORY FROM URL ──")
        story = scraper.story_from_url(story_url)
        if not story.get("raw_text"):
            raise RuntimeError(f"Could not read article text from {story_url}")
        pairs = [(story, selector.write_carousel(story, logger.get_recent_angles(3)))]
        stories = []
    else:
        print("\n── STEP 1: SCRAPE ──")
        stories = scraper.run()
        pairs = None
    if not story_url and not stories:
        print("[pipeline] No stories scraped — exiting.")
        sys.exit(0)

    print("\n── STEP 2: DEDUP CHECK ──")
    posted_urls = logger.get_posted_urls()
    print(f"[pipeline] {len(posted_urls)} already-posted URLs loaded")

    hours_ago = logger.hours_since_last_post()
    print(f"[pipeline] Local log: last post was {hours_ago:.1f}h ago")
    if not dry_run and not buffer_draft and hours_ago < 7:
        print(f"[pipeline] Already posted {hours_ago:.1f}h ago — skipping to avoid double-post.")
        sys.exit(0)

    if pairs is None:
        print("\n── STEP 3: SELECT + WRITE ──")
        pairs = selector.run(stories, posted_urls, force_local=force_local,
                             extra_topics=buffer_topics(cfg, account_id))
    if not pairs:
        print("[pipeline] No fresh stories to post — exiting.")
        sys.exit(0)

    story, carousel = pairs[0]
    print(f"\n[pipeline] Selected: {story['headline'][:70]}")
    validate_carousel_facts(story, carousel)

    print("\n── STEP 4: IMAGE GENERATION ──")
    img_dir = f"/tmp/carousel_imgs_{run_ts}"
    og_url = story.get("og_image_url", "")
    used_img_urls = logger.get_used_img_urls()
    image_paths, new_img_urls, image_sources = image_gen.generate_slide_images(
        carousel,
        img_dir,
        og_image_url=og_url,
        used_img_urls=used_img_urls,
    )

    if not image_paths:
        raise RuntimeError("Image generation returned no slides")
    while len(image_paths) < 10:
        image_paths.append(image_paths[-1])
    image_paths = image_paths[:10]

    print("\n── STEP 5: BUILD CAROUSEL ──")
    run_id = f"{run_ts}_{story.get('category', 'ai')}"
    png_paths = builder.run(carousel, image_paths, run_id)
    check_visual_quality(image_sources, dry_run)
    write_review_manifest(png_paths, story, carousel, image_sources, run_id)

    if dry_run:
        print(f"\n[pipeline] DRY RUN — skipping post. PNGs at: ~/Downloads/carousels/{run_id}/")
        return

    print("\n── STEP 6: POST VIA BUFFER ──")
    caption = carousel.get("caption", "")
    due_at = None if buffer_draft else scheduled_post_time(cfg)
    if due_at:
        print(f"[pipeline] Scheduling for {due_at}")
    submission_id = poster.run(png_paths, caption, account_id, run_id, draft=buffer_draft, due_at=due_at)
    if buffer_draft:
        print(f"\n✓ BUFFER DRAFT SAVED (nothing published): {story['headline'][:60]}")
        print(f"  Buffer post ID: {submission_id}")
        return

    print("\n── STEP 7: LOG ──")
    story["buffer_channel_id"] = account_id
    logger.log_posted(story, submission_id, carousel, new_img_urls=new_img_urls)

    print(f"\n✓ DONE — Submitted: {story['headline'][:60]}")
    print(f"  Buffer post ID: {submission_id}")
    print(f"  Slides at: ~/Downloads/carousels/{run_id}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build but don't post")
    parser.add_argument("--local", action="store_true", help="Lead with a local (e.g. Singapore) story")
    parser.add_argument("--url", default="", help="Build the carousel for this article URL")
    parser.add_argument("--manual", default="", help="Build a hand-written carousel from this spec JSON")
    parser.add_argument("--buffer-draft", action="store_true",
                        help="Send to Buffer as a draft instead of publishing (end-to-end test)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, force_local=args.local, buffer_draft=args.buffer_draft,
        story_url=args.url.strip(), manual_spec=args.manual.strip())
