"""Scrape AI news from Google News RSS, HackerNews, Reddit, GitHub Trending."""
import json
import os
import re
import time
from urllib.parse import quote, urlparse
import feedparser
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "anthropic", "openai", "machine learning",
    "deep learning", "neural", "transformer", "diffusion", "chatbot", "model", "inference",
    "agent", "rag", "fine-tun", "data centre", "data center", "deepfake", "robot", "humanoid",
    "jailbreak", "hack", "breach", "exploit", "quantum", "breakthrough", "chatgpt", "nvidia",
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


SUPERPOWERS_MCP_URL = "https://superpowers.social/mcp"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class SuperpowersClient:
    """Minimal MCP-over-HTTP client for superpowers.social (Reddit proxy).

    Reddit blocks GitHub Actions IPs, so Reddit posts are fetched through the
    Social Superpowers MCP server with an API key instead.
    """

    def __init__(self, api_key: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._next_id = 0
        self._initialize()

    def _post(self, method: str, params: dict | None = None, notify: bool = False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._next_id += 1
            body["id"] = self._next_id
        r = requests.post(SUPERPOWERS_MCP_URL, headers=self.headers, json=body, timeout=60)
        if r.status_code == 401:
            raise RuntimeError("Social Superpowers rejected SUPERPOWERS_API_KEY (HTTP 401)")
        r.raise_for_status()
        if "mcp-session-id" in r.headers:
            self.headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        if notify:
            return None
        return self._parse(r)

    @staticmethod
    def _parse(r: requests.Response) -> dict:
        if "text/event-stream" in r.headers.get("content-type", ""):
            message = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data:
                        message = json.loads(data)
            if message is None:
                raise RuntimeError("Social Superpowers returned an empty event stream")
        else:
            message = r.json()
        if message.get("error"):
            raise RuntimeError(f"Social Superpowers error: {message['error']}")
        return message.get("result", {})

    def _initialize(self):
        self._post("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "news-blotato-autopost", "version": "1.0"},
        })
        self._post("notifications/initialized", notify=True)

    def call(self, tool: str, arguments: dict) -> dict:
        result = self._post("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            raise RuntimeError(f"{tool} failed: {text[:200]}")
        if result.get("structuredContent"):
            return result["structuredContent"]
        for item in result.get("content", []):
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except ValueError:
                    continue
        return {}


def fetch_reddit(subreddits: list[str] = None, per_sub: int = 10) -> list[dict]:
    """Fetch today's top posts per subreddit through Social Superpowers.

    The API returns posts ranked by top-of-day, without vote counts, so rank is
    turned into an approximate reddit_score for the scoring prompt.
    """
    if subreddits is None:
        subreddits = ["MachineLearning", "LocalLLaMA", "artificial"]

    api_key = os.environ.get("SUPERPOWERS_API_KEY", "").strip()
    if not api_key:
        print("[scraper] Reddit skipped: SUPERPOWERS_API_KEY is not set")
        return []
    try:
        client = SuperpowersClient(api_key)
    except Exception as e:
        print(f"[scraper] Reddit skipped: {e}")
        return []

    local_sub = _local_subreddit()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rank_scores = [500, 300, 200, 150, 120, 100, 80, 70, 60, 60]
    stories = []
    for sub in subreddits:
        try:
            data = client.call("reddit-get-posts", {
                "subreddit": sub, "count": per_sub, "time_filter": "day",
            })
        except Exception as e:
            print(f"[scraper] Reddit r/{sub} error: {e}")
            continue
        kept = 0
        for rank, p in enumerate(data.get("posts", [])):
            title = p.get("title", "")
            is_local = sub.lower() == local_sub
            if not is_local and not _is_ai_relevant(title):
                continue
            created = datetime.fromtimestamp(p.get("createdUtc", 0) or 0, tz=timezone.utc)
            if created < cutoff:
                continue
            preview = (p.get("selftext_preview") or "").replace("[link]", "").replace("[comments]", "")
            preview = re.sub(r"submitted by /u/\S+", "", preview).strip()
            stories.append({
                "headline": title,
                "summary": preview[:300] or title,
                "url": p.get("url", ""),
                "source": f"r/{sub}",
                "published_at": created.isoformat(),
                "category": "local" if is_local else "global_ai",
                "hn_score": 0,
                "reddit_score": rank_scores[min(rank, len(rank_scores) - 1)],
                "gh_stars": 0,
                "raw_text": preview,
            })
            kept += 1
        print(f"[scraper] Reddit r/{sub}: {kept} posts kept")

    print(f"[scraper] Reddit: {len(stories)} stories via Social Superpowers")
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


def decode_google_news_url(url: str) -> str:
    """Turn a news.google.com/rss/articles/... redirect into the real article URL.

    Returns the original URL when decoding fails.
    """
    if "news.google.com" not in url:
        return url
    try:
        article_id = urlparse(url).path.rstrip("/").split("/")[-1]
        page = requests.get(
            f"https://news.google.com/rss/articles/{article_id}",
            headers={"User-Agent": _BROWSER_UA}, timeout=15,
        )
        div = BeautifulSoup(page.text, "html.parser").select_one("c-wiz > div[jscontroller]")
        if div is None:
            return url
        signature, timestamp = div.get("data-n-a-sg"), div.get("data-n-a-ts")
        if not signature or not timestamp:
            return url
        request = [
            "Fbv4je",
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,'
            'null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{article_id}",{timestamp},"{signature}"]',
        ]
        resp = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={
                "User-Agent": _BROWSER_UA,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            data=f"f.req={quote(json.dumps([[request]]))}",
            timeout=15,
        )
        body = resp.text.split("\n\n")[1]
        decoded = json.loads(json.loads(body)[0][2])[1]
        return decoded if isinstance(decoded, str) and decoded.startswith("http") else url
    except Exception as e:
        print(f"[scraper] Google News decode failed: {e}")
        return url


def fetch_article_content(url: str) -> tuple[str, str]:
    """Fetch article body text AND og:image URL in a single request.
    Returns (text, og_image_url).
    """
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": _BROWSER_UA}, allow_redirects=True)
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
        if "news.google.com" in story.get("url", ""):
            real_url = decode_google_news_url(story["url"])
            if real_url != story["url"]:
                story["google_news_url"] = story["url"]
                story["url"] = real_url
            time.sleep(0.3)
        if not story.get("raw_text") or len(story.get("raw_text", "")) < 400:
            text, og_image = fetch_article_content(story["url"])
            if len(text) > len(story.get("raw_text", "")):
                story["raw_text"] = text
            if text and story.get("summary", "") == story.get("headline", ""):
                story["summary"] = text[:300]
            if og_image:
                story["og_image_url"] = og_image
                print(f"[scraper] og:image found for: {story['headline'][:50]}...")
    return stories


def story_from_url(url: str) -> dict:
    """Build a story dict for one article URL (used for hand-picked posts)."""
    url = decode_google_news_url(url)
    headline = ""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": _BROWSER_UA}, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
        headline = (tag.get("content") if tag else "") or (soup.title.get_text() if soup.title else "")
    except Exception as e:
        print(f"[scraper] Could not read headline from {url}: {e}")
    headline = re.split(r"\s+[|\-–]\s+(?=[^|\-–]*$)", headline.strip())[0] or url
    text, og_image = fetch_article_content(url)

    cfg = _load_cfg()
    keywords = [k.lower().strip() for k in cfg.get("local_keywords", []) if k.strip()]
    keywords.append(str(cfg.get("country", "")).lower())
    blob = f"{headline} {text[:800]}".lower()
    category = "local" if any(k and k in blob for k in keywords) else "global_ai"

    story = {
        "headline": headline,
        "summary": text[:300] or headline,
        "url": url,
        "source": urlparse(url).netloc.replace("www.", ""),
        "published_at": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "hn_score": 0, "reddit_score": 0, "gh_stars": 0,
        "raw_text": text,
    }
    if og_image:
        story["og_image_url"] = og_image
    print(f"[scraper] Story from URL: {headline[:70]} ({category}, {len(text)} chars)")
    return story


def _load_cfg() -> dict:
    with open("config.json") as f:
        return json.load(f)


def _local_subreddit() -> str:
    return str(_load_cfg().get("country", "")).lower().replace(" ", "")


def _categorise(query: str) -> str:
    """Tag a Google News query as local when it mentions the configured country."""
    cfg = _load_cfg()
    keywords = [k.lower() for k in cfg.get("local_keywords", [])]
    keywords.append(str(cfg.get("country", "")).lower())
    q = query.lower().replace("+", " ")
    if any(k.strip() and k.strip() in q for k in keywords):
        return "local"
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

    # Tier 1 — Google News (global + local queries from config.json)
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

    # Tier 3 — Reddit hot posts (AI + viral tech subs, plus the local country sub)
    all_stories.extend(fetch_reddit(
        subreddits=cfg.get("subreddits", ["MachineLearning", "LocalLLaMA", "artificial"]),
    ))

    # Tier 4 — GitHub Trending AI
    all_stories.extend(fetch_github_trending())

    # Tier 5 — Official AI research blogs
    all_stories.extend(fetch_research_blogs())

    # Dedup + enrich
    stories = _dedupe(all_stories)
    print(f"\n[scraper] Total unique stories: {len(stories)}")
    print(f"[scraper] Enriching article text...")
    stories = _dedupe(enrich_with_text(stories))
    print(f"[scraper] Done. {len(stories)} stories ready for selection.")
    return stories


if __name__ == "__main__":
    results = run()
    print(json.dumps(results[:3], indent=2, default=str))
