"""Fetch carousel slide background images from Pixabay API — free, real photos."""
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

# 1080x1350 px Instagram portrait (4:5)
WIDTH, HEIGHT = 1080, 1350

# Default search queries per slide position (used as fallback if no image_prompt).
# Local slides use Singapore scenes. Change the city names to match config.json.
# Slides 1, 3, and 10 try a local query first, then fall back to a neutral one.
# Queries chosen for cinematic drama — bold, moody, visually striking on Instagram
_DEFAULT_QUERIES = [
    "Singapore Marina Bay night aerial",        # slide 1  cover  (local)
    "server room blue glow technology dark",    # slide 2  WHAT HAPPENED
    "Singapore skyline golden sunset",          # slide 3  why it matters (local)
    "rain window city lights bokeh night",      # slide 4  THE NUMBER
    "silhouette dramatic spotlight empty stage",# slide 5  MOST PEOPLE DON'T KNOW
    "speaker stage spotlight crowd dark",       # slide 6  EXPERT TAKE
    "light trail highway night long exposure",  # slide 7  HOW WE GOT HERE
    "person laptop night window city view",     # slide 8  WHAT TO DO NOW
    "storm clouds lightning dramatic dark sky", # slide 9  WATCH OUT FOR
    "Singapore skyline night city lights",      # slide 10 CTA (local)
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
    """Trim an image_prompt into a short Pixabay-friendly search query.

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
    # Strip country/place names unless this is a local (country-specific) slide
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


PIXABAY_CATEGORIES = {
    "backgrounds", "fashion", "nature", "science", "education", "feelings", "health",
    "people", "religion", "places", "animals", "industry", "computer", "food", "sports",
    "transportation", "travel", "buildings", "business", "music",
}


def _pixabay_search(q: str, category: str | None, used_urls: set | None) -> tuple[bytes | None, str]:
    """One Pixabay search. Picks randomly among the top hits only, to stay on-topic."""
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not api_key or not q:
        return None, ""
    params = {
        "key": api_key,
        "q": q[:100],
        "image_type": "photo",
        "safesearch": "true",
        "order": "popular",
        "per_page": 20,
        "min_width": 900,
    }
    if category in PIXABAY_CATEGORIES:
        params["category"] = category
    try:
        resp = requests.get("https://pixabay.com/api/", params=params, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])[:8]
        random.shuffle(hits)
        for hit in hits:
            img_url = hit.get("largeImageURL") or hit.get("webformatURL")
            # Download links rotate per request, so dedupe on the stable page URL.
            photo_key = hit.get("pageURL") or img_url
            if not img_url or (used_urls and photo_key in used_urls):
                continue
            img_resp = requests.get(img_url, timeout=30)
            img_resp.raise_for_status()
            label = f"{q}" + (f" [{category}]" if params.get("category") else "")
            print(f"[image_gen] Pixabay: '{label}' → {photo_key[:60]}...")
            return img_resp.content, photo_key
    except Exception as e:
        print(f"[image_gen] Pixabay error for '{q}': {e}")
    return None, ""


def _fetch_pixabay(query: str, slide_index: int, fallback_query: str | None = None,
                   used_urls: set | None = None, category: str | None = None) -> tuple[bytes | None, str]:
    """Try the query with its category, then without, then the neutral fallback."""
    attempts = [(query, category)]
    if category:
        attempts.append((query, None))
    words = query.split()
    if len(words) > 2:
        attempts.append((" ".join(words[:2]), category))
    if fallback_query and fallback_query != query:
        attempts.append((fallback_query, None))
    for q, cat in attempts:
        result, url = _pixabay_search(q, cat, used_urls)
        if result is not None:
            return result, url
    print(f"[image_gen] Pixabay: no fresh results for '{query}'")
    return None, ""


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
    """Dark gradient fallback if Pixabay unavailable."""
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
    """Fetch 10 Pixabay photos (or gradient fallback) for the carousel slides.

    Returns (paths, new_used_urls, sources). Sources records whether each slide used
    an article image, Pixabay, or the non-photographic gradient fallback.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    paths = []
    session_used = set(used_img_urls or set())  # running set for this session too

    # Build Pixabay queries. Prefer the writer's literal image_query keywords;
    # fall back to trimming the descriptive image_prompt.
    queries: list[str] = []
    categories: list[str | None] = []

    def _query_for(item: dict, query_key: str, prompt_key: str, default: str, allow_location: bool) -> str:
        literal = str(item.get(query_key, "")).strip()
        if literal and "literal keywords" not in literal:
            return literal
        prompt = item.get(prompt_key, "")
        return _prompt_to_query(prompt, allow_location=allow_location) if prompt else default

    queries.append(_query_for(carousel, "cover_image_query", "cover_image_prompt", _DEFAULT_QUERIES[0], True))
    categories.append(carousel.get("cover_image_category"))

    for i, slide in enumerate(carousel.get("slides", [])):
        query_idx = i + 1
        queries.append(_query_for(
            slide, "image_query", "image_prompt",
            _DEFAULT_QUERIES[min(query_idx, 8)], query_idx in _LOCAL_SLIDE_INDICES,
        ))
        categories.append(slide.get("image_category"))

    queries.append(_DEFAULT_QUERIES[9])
    categories.append("buildings")

    while len(queries) < 10:
        queries.append(_DEFAULT_QUERIES[len(queries) % len(_DEFAULT_QUERIES)])
        categories.append(None)
    queries = queries[:10]
    categories = categories[:10]

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
                print("[image_gen] og:image skipped — falling back to Pixabay")

        if img_bytes is None:
            img_bytes, img_url = _fetch_pixabay(query, slide_index=i,
                                                fallback_query=_NEUTRAL_FALLBACK_QUERIES[i],
                                                used_urls=session_used,
                                                category=categories[i])
            if img_url:
                new_urls.add(img_url)
                session_used.add(img_url)  # prevent reuse within same carousel too
                source = "pixabay"

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


def _place(img: Image.Image, path: str, fit: bool = False, crop: list | None = None,
           y_frac: float = 0.30) -> None:
    """Save one background. crop = [left, top, right, bottom] as fractions.

    fit=True letterboxes the whole image (for logos and graphics) on its own
    corner colour instead of cropping it to 4:5.
    """
    img = img.convert("RGB")
    if crop:
        w, h = img.size
        img = img.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    if fit:
        canvas = Image.new("RGB", (WIDTH, HEIGHT), img.getpixel((3, 3)))
        thumb = img.copy()
        thumb.thumbnail((WIDTH - 80, int(HEIGHT * 0.6)))
        canvas.paste(thumb, ((WIDTH - thumb.width) // 2, int(HEIGHT * y_frac) - thumb.height // 2))
        canvas.save(path, "JPEG", quality=92)
        return
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    _crop_and_resize(buf.getvalue(), path)


def images_from_spec(entries: list[dict], output_dir: str,
                     used_img_urls: set | None = None) -> tuple[list[str], set, list[str]]:
    """Build the 10 slide backgrounds for a hand-written carousel.

    Each entry is one of:
      {"query": "server room", "category": "computer"}   Pixabay search
      {"url": "https://..."}                              a specific image (article photo, logo)
      {"repo_file": "manual/assets/x.jpg"}                an image committed to the repo
      {"gradient": true}                                  plain dark background
    "fit": true and "crop": [l, t, r, b] (fractions) work with url and repo_file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    session_used = set(used_img_urls or set())
    paths, sources, new_urls = [], [], set()
    entries = list(entries)[:10] + [{"gradient": True}] * max(0, 10 - len(entries))
    for i, entry in enumerate(entries):
        path = os.path.join(output_dir, f"slide_{i + 1:02d}.jpg")
        source = "gradient"
        try:
            if entry.get("query"):
                data, key = _fetch_pixabay(entry["query"], slide_index=i,
                                           fallback_query=_NEUTRAL_FALLBACK_QUERIES[i],
                                           used_urls=session_used, category=entry.get("category"))
                if data:
                    _crop_and_resize(data, path)
                    session_used.add(key)
                    new_urls.add(key)
                    source = "pixabay"
            elif entry.get("url"):
                resp = requests.get(entry["url"], timeout=30, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
                resp.raise_for_status()
                _place(Image.open(io.BytesIO(resp.content)), path, entry.get("fit", False), entry.get("crop"))
                source = "url"
            elif entry.get("repo_file"):
                local = Path(__file__).parent / entry["repo_file"]
                _place(Image.open(local), path, entry.get("fit", False), entry.get("crop"))
                source = "repo_file"
        except Exception as e:
            print(f"[image_gen] Slide {i + 1} image failed ({e}); using gradient")
            source = "gradient"
        if source == "gradient":
            _gradient_fallback(path, i)
        print(f"[image_gen] Slide {i + 1}: {source}")
        paths.append(path)
        sources.append(source)
    return paths, new_urls, sources
