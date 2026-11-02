"""Fetch carousel slide background images from Pexels API — free, real photos."""
from __future__ import annotations
import os
import io
import random
import requests
from pathlib import Path
from PIL import Image, ImageDraw


# og:image URLs from these domains are generic/branded — not article-specific photos
_BAD_OG_DOMAINS = (
    "lh3.googleusercontent.com",
    "lh4.googleusercontent.com",
    "news.google.com",
    "gstatic.com",
    "googleusercontent.com",
)


def _is_bad_og_url(url: str) -> bool:
    """Return True if the og:image URL is a known generic/branded image source."""
    return any(domain in url for domain in _BAD_OG_DOMAINS)


def _fetch_url_image(url: str) -> bytes | None:
    """Download an image directly from a URL (e.g. article og:image)."""
    if _is_bad_og_url(url):
        print(f"[image_gen] og:image skipped (generic Google domain): {url[:60]}...")
        return None
    try:
        resp = requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "image" in content_type:
            return resp.content
        print(f"[image_gen] og:image URL not an image (content-type: {content_type})")
        return None
    except Exception as e:
        print(f"[image_gen] og:image download failed: {e}")
        return None

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# 1080x1350 px Instagram portrait (4:5)
WIDTH, HEIGHT = 1080, 1350

# Default search queries per slide position (used as fallback if no image_prompt).
# These match the Malaysia examples in config.json. Change the city names with your own.
# Slides 1, 3, and 10 try a local query first, then fall back to a neutral one.
# Queries chosen for cinematic drama — bold, moody, visually striking on Instagram
_DEFAULT_QUERIES = [
    "Kuala Lumpur KLCC night aerial",           # slide 1  cover  (MY-specific)
    "server room blue glow technology dark",    # slide 2  WHAT HAPPENED
    "Kuala Lumpur skyline golden sunset",       # slide 3  MY angle (MY-specific)
    "rain window city lights bokeh night",      # slide 4  THE NUMBER
    "silhouette dramatic spotlight empty stage",# slide 5  MOST PEOPLE DON'T KNOW
    "speaker stage spotlight crowd dark",       # slide 6  EXPERT TAKE
    "light trail highway night long exposure",  # slide 7  HOW WE GOT HERE
    "person laptop night window city view",     # slide 8  WHAT TO DO NOW
    "storm clouds lightning dramatic dark sky", # slide 9  WATCH OUT FOR
    "Kuala Lumpur skyline night city lights",   # slide 10 CTA (MY-specific)
]

# Neutral fallback queries used when a local search returns no results
_NEUTRAL_FALLBACK_QUERIES = [
    "city aerial night lights dramatic",        # slide 1  fallback
    "server room blue glow technology dark",    # slide 2
    "modern city skyline golden sunset",        # slide 3  fallback
    "rain window city lights bokeh night",      # slide 4
    "silhouette dramatic spotlight empty stage",# slide 5
    "speaker stage spotlight crowd dark",       # slide 6
    "light trail highway night long exposure",  # slide 7
    "person laptop night window city view",     # slide 8
    "storm clouds lightning dramatic dark sky", # slide 9
    "city skyline night dramatic lights",       # slide 10 fallback
]

# Slides that use a local query and should try a neutral fallback if it misses
_LOCAL_SLIDE_INDICES = {0, 2, 9}


def _prompt_to_query(prompt: str, allow_location: bool = False) -> str:
    """Trim an image_prompt into a short Pexels-friendly search query.

    By default strips country/location words to avoid wrong-country photo results.
    Set allow_location=True for the cover and the local-angle slides.
    """
    stop = {
        "dark", "dramatic", "no", "text", "portrait", "orientation",
        "cinematic", "moody", "amber", "glow", "glowing", "wide", "angle",
        "close", "up", "bleed", "shot", "background", "lighting", "light",
        "with", "and", "the", "for", "a", "an", "in", "of", "at", "on",
        "9:16", "3:4", "full", "side", "view",
    }
    # Strip country/place names unless this is a Malaysia-specific slide
    location_words = {
        "singapore", "malaysia", "america", "american", "usa", "us",
        "china", "chinese", "india", "indian", "australia", "australian",
        "uk", "british", "european", "europe",
    }
    if not allow_location:
        stop |= location_words

    words = [w.strip(",.;:()") for w in prompt.lower().split()]
    filtered = [w for w in words if w and w not in stop and len(w) > 2]
    return " ".join(filtered[:5])


def _fetch_pexels(query: str, slide_index: int, fallback_query: str | None = None,
                  used_urls: set | None = None) -> tuple[bytes | None, str]:
    """Call Pexels search API and return (raw image bytes, photo_url), or (None, '').

    Skips photos whose URLs are in used_urls to prevent reuse across posts.
    """
    if not PEXELS_API_KEY:
        return None, ""

    def _search(q: str) -> tuple[bytes | None, str]:
        try:
            # Stay on the first two result pages: deeper Pexels pages often drift
            # away from the query even when they technically match a keyword.
            for page in random.sample(range(1, 3), 2):
                resp = requests.get(
                    "https://api.pexels.com/v1/search",
                    headers={"Authorization": PEXELS_API_KEY},
                    params={
                        "query": q,
                        "per_page": 15,
                        "page": page,
                        "orientation": "portrait",
                        "size": "large",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                photos = resp.json().get("photos", [])
                if not photos:
                    continue
                # Shuffle and pick first photo not in used_urls
                random.shuffle(photos)
                for photo in photos:
                    img_url = photo["src"]["large2x"]
                    if used_urls and img_url in used_urls:
                        continue
                    img_resp = requests.get(img_url, timeout=30)
                    img_resp.raise_for_status()
                    print(f"[image_gen] Pexels: '{q}' (page {page}) → {img_url[:60]}...")
                    return img_resp.content, img_url
            print(f"[image_gen] Pexels: no fresh results for '{q}'")
            return None, ""
        except Exception as e:
            print(f"[image_gen] Pexels error for '{q}': {e}")
            return None, ""

    result, url = _search(query)
    if result is None and fallback_query and fallback_query != query:
        print(f"[image_gen] Retrying with neutral fallback: '{fallback_query}'")
        result, url = _search(fallback_query)
    return result, url


def _crop_and_resize(img_bytes: bytes, path: str):
    """Crop image to 4:5 ratio and resize to 1080x1350, save as JPEG."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size
    target_ratio = WIDTH / HEIGHT  # 0.8

    if w / h > target_ratio:
        # Too wide — crop sides
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        # Too tall — crop top/bottom
        new_h = int(w / target_ratio)
        top = (h - new_h) // 3  # bias toward top of image
        img = img.crop((0, top, w, top + new_h))

    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.save(path, "JPEG", quality=92)


def _gradient_fallback(path: str, slide_index: int):
    """Dark gradient fallback if Pexels unavailable."""
    palettes = [
        ((10, 10, 30), (25, 20, 60)),
        ((5, 20, 25), (10, 45, 55)),
        ((20, 10, 10), (50, 20, 15)),
        ((10, 15, 10), (20, 40, 20)),
        ((20, 10, 25), (45, 15, 55)),
        ((15, 10, 5), (45, 30, 10)),
        ((5, 5, 20), (15, 15, 50)),
        ((20, 5, 15), (55, 10, 35)),
        ((5, 20, 20), (10, 50, 50)),
        ((10, 10, 10), (30, 25, 5)),
    ]
    top, bottom = palettes[slide_index % len(palettes)]
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    img.save(path, "JPEG", quality=92)


def generate_slide_images(carousel: dict, output_dir: str, og_image_url: str = "",
                          used_img_urls: set | None = None) -> tuple[list[str], set, list[str]]:
    """Fetch 10 Pexels photos (or gradient fallback) for the carousel slides.

    Returns (paths, new_used_urls, sources). Sources records whether each slide used
    an article image, Pexels, or the non-photographic gradient fallback.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    session_used = set(used_img_urls or set())  # running set for this session too

    # Build Pexels queries.
    queries = []

    cover_prompt = carousel.get("cover_image_prompt", "")
    queries.append(_prompt_to_query(cover_prompt, allow_location=True) if cover_prompt else _DEFAULT_QUERIES[0])

    for i, slide in enumerate(carousel.get("slides", [])):
        prompt = slide.get("image_prompt", "")
        query_idx = i + 1
        is_local_slide = query_idx in _LOCAL_SLIDE_INDICES
        default_prompt = _DEFAULT_QUERIES[min(i + 1, 8)]
        queries.append(
            _prompt_to_query(prompt, allow_location=is_local_slide) if prompt
            else default_prompt
        )

    queries.append(_DEFAULT_QUERIES[9])

    while len(queries) < 10:
        queries.append(_DEFAULT_QUERIES[len(queries) % len(_DEFAULT_QUERIES)])
    queries = queries[:10]

    new_urls: set = set()
    sources: list[str] = []

    for i, query in enumerate(queries):
        path = os.path.join(output_dir, f"slide_{i+1:02d}.jpg")

        img_bytes = None
        source = ""
        # Cover slide: try article og:image first (real person/CEO photos)
        if i == 0 and og_image_url:
            print(f"[image_gen] Trying article og:image for cover: {og_image_url[:60]}...")
            img_bytes = _fetch_url_image(og_image_url)
            if img_bytes:
                print("[image_gen] og:image used for cover slide ✓")
                new_urls.add(og_image_url)
                source = "article"
            else:
                print("[image_gen] og:image skipped — falling back to Pexels")

        if img_bytes is None:
            neutral_fallback = _NEUTRAL_FALLBACK_QUERIES[i] if i in _LOCAL_SLIDE_INDICES else None
            img_bytes, img_url = _fetch_pexels(query, slide_index=i,
                                               fallback_query=neutral_fallback,
                                               used_urls=session_used)
            if img_url:
                new_urls.add(img_url)
                session_used.add(img_url)  # prevent reuse within same carousel too
                source = "pexels"

        if img_bytes:
            _crop_and_resize(img_bytes, path)
        else:
            print(f"[image_gen] Using gradient fallback for slide {i+1}")
            _gradient_fallback(path, i)
            source = "gradient"
        paths.append(path)
        sources.append(source)

    print(f"[image_gen] Generated {len(paths)} slide images in {output_dir}")
    print(f"[image_gen] Sources: {sources}")
    return paths, new_urls, sources


if __name__ == "__main__":
    result = generate_slide_images({}, "/tmp/cs_test_run")
    print(result)
