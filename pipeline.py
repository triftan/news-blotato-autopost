"""
Main pipeline orchestrator:
  scraper → selector → image_gen → builder → Blotato → logger
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
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
            "Configure PEXELS_API_KEY, then run a dry run first."
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


def run(dry_run: bool = False):
    with open("config.json", encoding="utf-8") as config_file:
        cfg = json.load(config_file)
    account_id = cfg["blotato"]["instagram_account_id"]
    account_username = cfg["blotato"]["instagram_username"]
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")

    # A fresh template must not spend API credits or post under placeholder brand values.
    action = config_check.guard_unconfigured(cfg)
    if action:
        print(config_check.friendly_message(config_check.placeholder_fields(cfg)))
        if action == "skip":
            print("[pipeline] Scheduled run skipped. Nothing was posted.")
            return
        sys.exit(1)

    # Fail before scraping, AI calls, and rendering if Blotato is unavailable.
    if not dry_run:
        print("\n── STEP 0: BLOTATO PREFLIGHT ──")
        poster.validate_account(account_id, account_username)

    print("\n── STEP 1: SCRAPE ──")
    stories = scraper.run()
    if not stories:
        print("[pipeline] No stories scraped — exiting.")
        sys.exit(0)

    print("\n── STEP 2: DEDUP CHECK ──")
    posted_urls = logger.get_posted_urls()
    print(f"[pipeline] {len(posted_urls)} already-posted URLs loaded")

    hours_ago = logger.hours_since_last_post()
    print(f"[pipeline] Local log: last post was {hours_ago:.1f}h ago")
    if not dry_run and hours_ago < 7:
        print(f"[pipeline] Already posted {hours_ago:.1f}h ago — skipping to avoid double-post.")
        sys.exit(0)

    print("\n── STEP 3: SELECT + WRITE ──")
    pairs = selector.run(stories, posted_urls)
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

    print("\n── STEP 6: POST VIA BLOTATO ──")
    caption = carousel.get("caption", "")
    submission_id = poster.run(png_paths, caption, account_id)

    print("\n── STEP 7: LOG ──")
    story["blotato_account_id"] = account_id
    logger.log_posted(story, submission_id, carousel, new_img_urls=new_img_urls)

    print(f"\n✓ DONE — Submitted: {story['headline'][:60]}")
    print(f"  Blotato submission ID: {submission_id}")
    print(f"  Slides at: ~/Downloads/carousels/{run_id}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build but don't post")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
