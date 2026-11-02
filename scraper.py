"""Scrape AI news from Google News RSS, HackerNews, Reddit, GitHub Trending."""
import json
import time
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "anthropic", "openai", "machine learning",
    "deep learning", "neural", "transformer", "diffusion", "chatbot", "model", "inference",
    "agent", "rag", "fine-tun", "malaysia", "mdec", "naio", "mosti", "data centre", "data center",
]

def _is_ai_relevant(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in AI_KEYWORDS)


def fetch_hackernews(min_score: int = 150, max_stories: int = 30) -> list[dict]:
    """Fetch top HN stories with min_score points — pre-validated by tech community."""
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        ).json()[:200]
    except Exception as e:
        print(f"[scraper] HN top stories error: {e}")
        return []

    stories = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    for story_id in ids:
        if len(stories) >= max_stories:
            break
        try:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=6
            ).json()
            if not item or item.get("type") != "story":
                continue
            score = item.get("score", 0)
            title = item.get("title", "")
            if score < min_score:
                continue
            if not _is_ai_relevant(title):
                continue
            published = datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc)
            if published < cutoff:
                continue
            stories.append({
                "headline": title,
                "summary": title,
                "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                "source": "HackerNews",
                "published_at": published.isoformat(),
                "category": "global_ai",
                "hn_score": score,
                "hn_comments": item.get("descendants", 0),
                "reddit_score": 0,
                "gh_stars": 0,
                "raw_text": "",
            })
            time.sleep(0.1)
        except Exception:
            continue

    print(f"[scraper] HackerNews: {len(stories)} AI stories with {min_score}+ points")
    return stories


def fetch_reddit(subreddits: list[str] = None, min_score: int = 60) -> list[dict]:
    """Fetch hot Reddit posts — no auth needed via JSON API."""
    if subreddits is None:
        subreddits = ["MachineLearning", "LocalLLaMA", "artificial", "Malaysia"]

    stories = []
    # Reddit blocks generic bots — use a browser-like user agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 429:
                print(f"[scraper] Reddit r/{sub}: rate limited, skipping")
                time.sleep(2)
                continue
            r.raise_for_status()
            data = r.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                p = post.get("data", {})
                score = p.get("score", 0)
                title = p.get("title", "")
                if score < min_score:
                    continue
                if sub not in ("malaysia",) and not _is_ai_relevant(title):
                    continue
                created = datetime.fromtimestamp(p.get("created_utc", 0), tz=timezone.utc)
                if created < cutoff:
                    continue
                link = p.get("url", "")
                if "reddit.com" in link:
                    link = f"https://reddit.com{p.get('permalink','')}"
                stories.append({
                    "headline": title,
                    "summary": p.get("selftext", "")[:300] or title,
                    "url": link,
                    "source": sub,
                    "published_at": created.isoformat(),
                    "category": "malaysia_local" if sub == "malaysia" else "global_ai",
                    "hn_score": 0,
                    "reddit_score": score,
                    "reddit_comments": p.get("num_comments", 0),
                    "gh_stars": 0,
                    "raw_text": "",
                })
            time.sleep(1)
        except Exception as e:
            print(f"[scraper] Reddit r/{sub} error: {e}")

    print(f"[scraper] Reddit: {len(stories)} stories ({min_score}+ upvotes)")
    return stories


def fetch_github_trending(topic: str = "ai", since: str = "daily") -> list[dict]:
    """Scrape GitHub Trending for viral AI repos."""
    stories = []
    try:
        url = f"https://github.com/trending/python?since={since}&spoken_language_code=en"
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        repos = soup.select("article.Box-row")[:15]
        for repo in repos:
            name_el = repo.select_one("h2 a")
            desc_el = repo.select_one("p")
            stars_el = repo.select_one("a[href$='/stargazers']")
            if not name_el:
                continue
            name = name_el.get_text(strip=True).replace("\n", "").replace(" ", "")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            stars_text = stars_el.get_text(strip=True).replace(",", "") if stars_el else "0"
            stars = int(stars_text) if stars_text.isdigit() else 0
            if not _is_ai_relevant(name + " " + desc):
                continue
            stories.append({
                "headline": f"{name} — {desc[:80]}" if desc else name,
                "summary": desc or name,
                "url": f"https://github.com/{name.strip('/')}",
                "source": "GitHub Trending",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "category": "global_ai",
                "hn_score": 0,
                "reddit_score": 0,
                "gh_stars": stars,
                "raw_text": "",
            })
    except Exception as e:
        print(f"[scraper] GitHub Trending error: {e}")

    print(f"[scraper] GitHub Trending: {len(stories)} AI repos")
    return stories


def fetch_research_blogs(hours_back: int = 24) -> list[dict]:
    """Fetch from official AI research lab blogs — zero noise."""
    blog_feeds = [
        ("https://openai.com/news/rss.xml", "OpenAI Blog"),
        ("https://huggingface.co/blog/feed.xml", "HuggingFace Blog"),
        ("https://www.anthropic.com/rss.xml", "Anthropic Blog"),
        ("https://blog.google/technology/ai/rss/", "Google AI Blog"),
        ("https://ai.meta.com/blog/rss/", "Meta AI Blog"),
        ("https://deepmind.google/blog/rss.xml", "Google DeepMind"),
        ("https://blogs.microsoft.com/ai/feed/", "Microsoft AI Blog"),
    ]
    stories = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    for feed_url, source_name in blog_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    published = datetime.now(timezone.utc)
                if published < cutoff:
                    continue
                title = entry.title.split(" - ")[0].strip()
                stories.append({
                    "headline": title,
                    "summary": BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()[:300],
                    "url": entry.link,
                    "source": source_name,
                    "published_at": published.isoformat(),
                    "category": "global_ai",
                    "hn_score": 0,
                    "reddit_score": 0,
                    "gh_stars": 0,
                    "raw_text": "",
                })
        except Exception as e:
            print(f"[scraper] Blog feed error ({source_name}): {e}")
    print(f"[scraper] Research blogs: {len(stories)} stories")
    return stories


def fetch_google_news(queries: list[str], hours_back: int = 14) -> list[dict]:
    """Fetch stories from Google News RSS for each query."""
    stories = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    for query in queries:
        url = f"https://news.google.com/rss/search?q={query}&hl=en-SG&gl=SG&ceid=SG:en"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published < cutoff:
                    continue
                # Strip HTML from summary and remove trailing source name
                raw_summary = entry.get("summary", "")
                soup_sum = BeautifulSoup(raw_summary, "html.parser")
                # The link text IS the headline — use the font tag text as source, p tag as summary
                link_text = soup_sum.find("a")
                clean_headline = link_text.get_text(strip=True) if link_text else entry.title
                clean_headline = clean_headline.split(" - ")[0].strip()
                clean_summary = clean_headline  # Summary same as headline for Google News
                stories.append({
                    "headline": clean_headline,
                    "summary": clean_summary,
                    "url": entry.link,
                    "source": entry.get("source", {}).get("title", "Google News"),
                    "published_at": published.isoformat(),
                    "category": _categorise(query),
                    "query": query,
                    "raw_text": "",
                })
        except Exception as e:
            print(f"[scraper] Google News error for '{query}': {e}")

    return _dedupe(stories)


def fetch_article_content(url: str) -> tuple[str, str]:
    """Fetch article body text AND og:image URL in a single request.
    Returns (text, og_image_url).
    """
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")

        # Extract og:image (the article's hero/featured image)
        og_image = ""
        og_tag = soup.find("meta", property="og:image")
        if og_tag and og_tag.get("content"):
            og_image = og_tag["content"]
        else:
            tw_tag = soup.find("meta", attrs={"name": "twitter:image"})
            if tw_tag and tw_tag.get("content"):
                og_image = tw_tag["content"]

        # Extract body text
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs)
        return text[:3000], og_image
    except Exception:
        return "", ""


def fetch_article_text(url: str) -> str:
    """Fetch and extract article body text only (backward compat wrapper)."""
    text, _ = fetch_article_content(url)
    return text


def enrich_with_text(stories: list[dict]) -> list[dict]:
    """Add raw_text and og_image_url to each story by fetching the article."""
    for story in stories:
        if not story.get("raw_text"):
            text, og_image = fetch_article_content(story["url"])
            story["raw_text"] = text
            if og_image:
                story["og_image_url"] = og_image
                print(f"[scraper] og:image found for: {story['headline'][:50]}...")
    return stories


def _categorise(query: str) -> str:
    malaysia_keywords = ["malaysia", "mdec", "naio", "mosti", "klcc", "putrajaya", "penang", "johor"]
    q = query.lower()
    if any(k in q for k in malaysia_keywords):
        return "malaysia_local"
    return "global_ai"


def _dedupe(stories: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for s in stories:
        if s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out


def run() -> list[dict]:
    """Main entry — returns merged, deduped story list from all sources."""
    with open("config.json") as f:
        cfg = json.load(f)

    all_stories = []

    # Tier 1 — Malaysian local (Google News)
    queries = cfg["google_news_queries"]
    print(f"[scraper] Google News: {len(queries)} queries...")
    gn = fetch_google_news(queries)
    # Ensure engagement fields exist on Google News stories
    for s in gn:
        s.setdefault("hn_score", 0)
        s.setdefault("reddit_score", 0)
        s.setdefault("gh_stars", 0)
    all_stories.extend(gn)

    # Tier 2 — HackerNews (pre-validated by community)
    all_stories.extend(fetch_hackernews(min_score=150))

    # Tier 3 — Reddit hot AI subs
    all_stories.extend(fetch_reddit(
        subreddits=["MachineLearning", "LocalLLaMA", "artificial", "malaysia"],
        min_score=60
    ))

    # Tier 4 — GitHub Trending AI
    all_stories.extend(fetch_github_trending())

    # Tier 5 — Official AI research blogs
    all_stories.extend(fetch_research_blogs())

    # Dedup + enrich
    stories = _dedupe(all_stories)
    print(f"\n[scraper] Total unique stories: {len(stories)}")
    print(f"[scraper] Enriching article text...")
    stories = enrich_with_text(stories)
    print(f"[scraper] Done. {len(stories)} stories ready for selection.")
    return stories


if __name__ == "__main__":
    results = run()
    print(json.dumps(results[:3], indent=2, default=str))
