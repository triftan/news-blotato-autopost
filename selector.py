"""Use an LLM via OpenRouter to score stories and write 10-slide carousel content."""
import os
import json
import random
import re
from pathlib import Path
import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Load country config
_cfg_path = Path(__file__).parent / "config.json"
with open(_cfg_path) as f:
    _CFG = json.load(f)

COUNTRY        = _CFG.get("country", "Singapore")
ACCOUNT_HANDLE = _CFG.get("account_handle", "@YOUR_INSTAGRAM_HANDLE")
COMMUNITY_NAME = _CFG.get("community_name", "YOUR_BRAND_NAME")
COMMUNITY_URL  = _CFG.get("community_url", "YOUR_COMMUNITY_URL")
COMMENT_KEYWORD = _CFG.get("comment_keyword", "YOUR_COMMENT_KEYWORD")
CURRENCY       = _CFG.get("currency", "Ringgit (RM)")
GOV_BODIES     = _CFG.get("government_bodies", "NAIO, MDEC")
LANDMARKS      = _CFG.get("local_landmarks", "KLCC, Putrajaya")
LOCAL_CONTEXT  = _CFG.get("local_context", "local founders and businesses")
FLAG_EMOJI     = _CFG.get("flag_emoji", "🇲🇾")
HASHTAGS       = " ".join(_CFG.get("posting", {}).get("hashtags", ["#AINews"]))
LOCAL_HASHTAGS = " ".join(_CFG.get("posting", {}).get("local_hashtags", []))
LOCAL_SHARE    = float(_CFG.get("local_share", 0.2))
SCORE_MODEL    = _CFG.get("openrouter", {}).get("score_model", "deepseek/deepseek-v4.1-flash")
WRITE_MODEL    = _CFG.get("openrouter", {}).get("write_model", "deepseek/deepseek-v4.1-flash")


def _chat(model: str, prompt: str, max_tokens: int) -> str:
    """Send one prompt to OpenRouter and return the reply text."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing or empty")
    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "news-blotato-autopost",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter {model} failed (HTTP {resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"OpenRouter {model} error: {body['error']}")
    return (body["choices"][0]["message"].get("content") or "").strip()

SCORE_PROMPT = f"""You are a viral social media editor for {ACCOUNT_HANDLE}, a global AI news page on Instagram run from {COUNTRY}.

The audience wants: big AI news, shocking or viral stories, hacks and exploits (security hacks, jailbreaks, and practical AI tricks), surprising discoveries, and controversy.

Score each story 0-100 for Instagram carousel potential. Use this rubric:
- 90-100: Jaw-dropping — major AI breakthrough or launch, scandal, viral moment, shocking discovery, serious hack
- 70-89: High value — controversial debate, surprising study, useful AI hack/trick, community-validated (high HN/Reddit score)
- 50-69: Interesting — solid AI news with a clear hook
- 30-49: Low priority — minor update, promotional, dry corporate news
- 0-29: Skip — off-topic, noise, already covered

Weighted scoring factors:
1. Shock / controversy / virality (3x weight): scandal, backlash, lawsuit, "this is insane", contrarian take, something people will argue about in the comments
2. Community validation (2x weight) — USE THE SIGNALS PROVIDED:
   - HN score 500+ = score 10, 300+ = 8, 150+ = 6
   - Reddit score 500+ = 10, 200+ = 8, 60+ = 5
   - GitHub stars 1000+ = 8, 500+ = 6
   - No signals = 3
3. Novelty / discovery (2x): Surprising stat, first-ever, new capability, a hack or trick most people don't know
4. Visual drama (1x): Can this story use strong editorial stock photography from Pixabay?
5. Shareability (1x): Will readers comment, share, or tag friends? Global stories score just as high as {COUNTRY} ones.

Also assign the best hook angle (1-8) for each story:
1=Against The Grain, 2=Controversial, 3=Trending, 4=Celebrity, 5=Small Change Big Difference, 6=Well Known Little Understood, 7=Uncommon/Weird, 8=Numbers

Return ONLY a compact JSON array — no explanation outside the array, no markdown fences. Keep reason under 8 words.
[{{"index": 0, "score": 85, "angle": 2, "reason": "AI deepfake scam goes viral"}}]

Stories (with community signals):
{{stories}}"""

WRITE_PROMPT = f"""You are a viral carousel writer for {ACCOUNT_HANDLE}, a global AI news page on Instagram run from {COUNTRY}. The audience loves big AI news, shocking viral stories, hacks, discoveries, and controversy.

Write a 10-slide Instagram carousel for this story.

## STEP 1: Pick the single best hook angle (these 8 angles)

1. AGAINST THE GRAIN — Contradicts common belief. Use when the story challenges what most people think.
   Cover: "Why [common belief] Is Dead Wrong" / "Why [popular advice] Is Keeping {COUNTRY} Behind"
   Example: "Why Saving on AI Tools Is Keeping {COUNTRY} Businesses Poor"

2. CONTROVERSIAL — Polarising, sparks debate. Use when the story has two strong opposing camps.
   Cover: "Is [X] a Scam?" / "Should People in {COUNTRY} Even Bother With [X]?"
   Example: "Is {COUNTRY}'s AI Bet a Waste of Money?"

3. TRENDING / TIMELY — Newsjack a current event. Best for breaking announcements.
   Cover: "What [current event] Reveals About [deeper truth for {COUNTRY}]"
   Example: "What a New Model Launch Reveals About {COUNTRY}'s AI Gap"

4. CELEBRITY / AUTHORITY — Borrow a known name. Best when a public figure is involved.
   Cover: "What [public figure]'s [action] Teaches Everyone in {COUNTRY} About [topic]"
   Example: "What This Leader Understands About AI That Most CEOs Don't"

5. SMALL CHANGE, BIG DIFFERENCE — High result, low effort. Best for tool/productivity stories.
   Cover: "One [tool/habit/move] That Changed How People in {COUNTRY} Are Using AI"
   Example: "This One Prompt Saved {COUNTRY} Founders 3 Hours a Day"

6. WELL KNOWN, LITTLE UNDERSTOOD — Surface knowledge vs mastery. Best for complex topics.
   Cover: "Everyone Knows [X]. Few People in {COUNTRY} Understand What It Actually Means."
   Example: "Everyone Knows {COUNTRY} Is Building Data Centres. Few Understand Why That's Dangerous."

7. UNCOMMON / WEIRD — Novelty and surprise. Best when the story has a counterintuitive angle.
   Cover: "The Weird Way [entity] Is Using AI Nobody Talks About"
   Example: "3 Weird AI Tools {COUNTRY} SMEs Are Using to Beat MNCs"

8. NUMBERS — Specificity = credibility. Best when the story has strong data.
   Cover: "[X]% of People in {COUNTRY} [surprising fact]" / "[Number] Things About [topic] That Will Shock You"
   Example: "73% of Companies in {COUNTRY} Are Using AI Wrong. Here's the Data."

## STEP 2: Write the full carousel

Writing rules — study these carefully:
- Write like a smart friend explaining news over WhatsApp. Not a journalist. Not a presenter.
- Preserve every date, year, reporting period, number, organisation, and attribution exactly as supplied by the source. Never change 1H2026 to 1H2025 or invent a missing fact.
- Preserve the full scope of compound facts. If the source says "data centres and cloud projects", keep both categories; never narrow it to "just data centres".
- Cover headline: Use Title Case (not ALLCAPS). Include a SPECIFIC number or name if the story has one. Max 10 words per line, 2-3 lines. Make someone stop scrolling.
  GOOD: "Someone Built a $32 Device That Shows Your AI Usage in Real Time"
  GOOD: "{COUNTRY} Just Secured a $10 Billion AI Deal Nobody Saw Coming"
  BAD: "WHAT THIS MEANS FOR THE AI FUTURE"
- Every slide headline must be a specific, conversational statement — not a generic label.
  GOOD: "Google just offered SpaceX $1.5 billion to launch satellites into orbit"
  BAD: "What the experts are saying"
- Amber line: the single most jaw-dropping stat or fact. Put the NUMBER in it if there is one.
  GOOD: **"This model runs 48x faster than GPT-4 — on a single laptop GPU."**
  BAD: **"This is a major development for the AI industry."**
- insight: ONE sentence only. Max 12 words. The single most surprising fact or takeaway. No corporate speak. Numbers preferred.
- Slide 3 explains why this matters to the reader. If the category is "local", or the story clearly affects {COUNTRY}, name real {COUNTRY} companies, bodies ({GOV_BODIES}), or people affected. For a global story with no real {COUNTRY} link, keep it global. Never invent a local angle.
- Never use em dashes or en dashes anywhere (captions, headlines, insights). Use a comma, a full stop, or a colon instead.
- Caption: Start with a provocative 1-line hook. Then 2-3 short lines expanding it. End with Comment {COMMENT_KEYWORD}. Use only these hashtags: {HASHTAGS}
- Write EXACTLY 8 slides (num 2 through 9). Do NOT write a slide 10 — the CTA is generated automatically.
- cover_badge: Pick one — BREAKING (major new announcement), LOCAL (story about {COUNTRY}), AI NEWS (global AI), EXCLUSIVE (insider/first), VIRAL (meme/funny).
- Photos come from Pixabay stock search, which matches keywords literally. For every slide give:
  - image_query: 2-4 plain English keywords for a REAL photo that shows the subject of that slide. Concrete nouns only (objects, scenes, people doing things). Examples: "bitcoin coins", "hacker laptop dark", "stock market screen", "robot arm factory", "smartphone app", "server room", "police tape", "courtroom gavel".
  - Never use brand names, people's names, place names, or abstract words (concept, future, impact, growth, timeline, data visualisation).
  - image_category: one of science, computer, business, industry, people, transportation, buildings, education, health. Pick the one the photo belongs to.
- meme_text: Only for funny/ironic/meme stories. Max 2 short lines, written like a screenshot of someone's shocked reaction or a tweet. Empty string for straight news.

Return valid JSON only:
{{
  "angle": 3,
  "angle_name": "TRENDING",
  "cover_formula": 3,
  "cover_headline": "Someone Built a $32 Device\\nThat Shows Your AI Usage\\nIn Real Time",
  "cover_subheadline": "AI usage tracking just went physical. And it only costs $32.",
  "cover_badge": "BREAKING",
  "meme_text": "Optional. For meme-worthy stories only (AI behaving weirdly, funny reversals, ironic stats): 1-2 lines of witty commentary shown as a chat bubble on the cover. Write it like a tweet reaction. Leave empty string for straight news.",
  "caption": "A $32 gadget is now more useful than most $2,000 AI dashboards.\\n\\nHere's what it does, and why developers in {COUNTRY} are already copying it.\\n\\nSwipe to see the full breakdown ➡️\\n\\nComment \\"{COMMENT_KEYWORD}\\" to join {COMMUNITY_NAME} {FLAG_EMOJI}\\n→ {COMMUNITY_URL}\\n\\n{HASHTAGS}",
  "cover_image_query": "2-4 literal keywords for the cover photo, e.g. hacker laptop dark",
  "cover_image_category": "computer",
  "cover_image_prompt": "A dramatic, high-quality photographic portrait. Prefer: a well-known tech CEO or entrepreneur relevant to this story (e.g. Sam Altman, Sundar Pichai, Elon Musk, a relevant local founder), OR a cinematic real-world scene (aerial city night, storm clouds, server room blue glow). Full-bleed portrait orientation. No logos, no flat graphics, no text. Dark and bold.",
  "slides": [
    {{
      "num": 2,
      "label": "WHAT HAPPENED",
      "headline": "Write a specific 8-10 word headline describing the actual news event",
      "insight": "One sentence, max 12 words. The most surprising fact or number from this story.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Dark tech concept relevant to the story, no text, portrait"
    }},
    {{
      "num": 3,
      "label": "WHY IT MATTERS",
      "headline": "Write how this directly affects the reader (use the {COUNTRY} angle only if the story really has one)",
      "insight": "One sentence, max 12 words. Direct impact on people or businesses — with a number if possible.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "City skyline at night, dark moody, no text (a {COUNTRY} landmark such as {LANDMARKS} only for local stories)"
    }},
    {{
      "num": 4,
      "label": "THE NUMBER",
      "headline": "Write the specific stat or data point as a surprising statement",
      "insight": "One sentence, max 12 words. The exact figure — e.g. $7.3 billion, 48x faster, 73% of companies.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Abstract data visualisation, dark background, no text"
    }},
    {{
      "num": 5,
      "label": "MOST PEOPLE DON'T KNOW",
      "headline": "Write the counterintuitive truth this story reveals",
      "insight": "One sentence, max 12 words. The thing that surprises even people who follow AI closely.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Contrast concept, light vs dark, modern vs old, no text"
    }},
    {{
      "num": 6,
      "label": "EXPERT TAKE",
      "headline": "Write what a credible person or organisation actually said about this",
      "insight": "One sentence, max 12 words. A direct quote or specific claim from a named expert.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Professional speaker or conference scene, spotlight, dark background, no text"
    }},
    {{
      "num": 7,
      "label": "HOW WE GOT HERE",
      "headline": "Write the key turning point or backstory in one specific statement",
      "insight": "One sentence, max 12 words. The single event or year that made today's news inevitable.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Timeline or milestone concept, dark background, glowing points, no text"
    }},
    {{
      "num": 8,
      "label": "WHAT TO DO NOW",
      "headline": "Write a specific actionable move or hack the reader can use today",
      "insight": "One sentence, max 12 words. The one thing early movers are doing right now.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Person working on laptop at night, city lights, focused, no text"
    }},
    {{
      "num": 9,
      "label": "WATCH OUT FOR",
      "headline": "Write the specific trap, risk, or overhyped claim people are falling for",
      "insight": "One sentence, max 12 words. The exact thing not worth your time or money right now.",
      "image_query": "2-4 literal keywords for this slide's photo",
      "image_category": "computer",
      "image_prompt": "Warning or caution concept, dramatic shadows, no text"
    }}
  ]
}}

IMPORTANT: You MUST return valid JSON no matter what. If article text is limited, use only facts present in the headline, summary, and supplied full text. Do not fill gaps from memory or invent specifics. Never refuse or explain — just write a conservative carousel and return JSON.

Story to write about:
Headline: {{headline}}
Summary: {{summary}}
Full text: {{raw_text}}
Category: {{category}}"""


def score_stories(stories: list[dict]) -> list[dict]:
    """Score all stories and return sorted list."""
    def _signal_str(s: dict) -> str:
        parts = []
        if s.get("hn_score", 0) >= 150:
            parts.append(f"HN:{s['hn_score']}pts")
        if s.get("reddit_score", 0) >= 60:
            parts.append(f"Reddit:{s['reddit_score']}↑")
        if s.get("gh_stars", 0) >= 100:
            parts.append(f"GH:{s['gh_stars']}★")
        return " | " + " ".join(parts) if parts else ""

    stories_text = "\n".join(
        f"[{i}] {s['headline']} | {s['source']} | {s['category']}{_signal_str(s)}"
        for i, s in enumerate(stories)
    )

    text = _chat(SCORE_MODEL, SCORE_PROMPT.replace("{stories}", stories_text), 8000)
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    # Extract JSON array
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end == 0:
        print(f"[selector] Score parse failed — raw response:\n{text[:300]}")
        # Return stories with default score 50
        for s in stories:
            s.setdefault("score", 50)
            s.setdefault("suggested_angle", 3)
        return stories
    scores = json.loads(text[start:end])

    for s in scores:
        idx = s["index"]
        if idx < len(stories):
            stories[idx]["score"] = s["score"]
            stories[idx]["score_reason"] = s.get("reason", "")
            stories[idx]["suggested_angle"] = s.get("angle", 3)

    return sorted(stories, key=lambda x: x.get("score", 0), reverse=True)


def remove_dashes(text: str) -> str:
    """Swap em/en dashes for commas so captions and slides read without them."""
    text = re.sub(r"(\d)\s*[—–]\s*(\d)", r"\1-\2", text or "")  # ranges: 2024–2026 → 2024-2026
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"^,\s*", "", text, flags=re.M)
    text = re.sub(r",[ \t]*$", "", text, flags=re.M)
    return re.sub(r",\s*([.!?])", r"\1", text)


def _strip_dashes(value):
    if isinstance(value, str):
        return remove_dashes(value)
    if isinstance(value, list):
        return [_strip_dashes(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_dashes(v) for k, v in value.items()}
    return value


def ensure_caption_cta(caption: str, local: bool = False) -> str:
    """Guarantee the caption ends with the comment keyword, community link, and hashtags.

    Hashtags are always rebuilt from config: the base set, plus the local
    hashtags (e.g. #Singapore) only when the story is local.
    """
    caption = (caption or "").strip()
    body_lines, tags = [], []
    for line in caption.splitlines():
        stripped = line.strip()
        if stripped and all(word.startswith("#") for word in stripped.split()):
            tags.extend(stripped.split())
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).rstrip()

    cta_lines = []
    if COMMENT_KEYWORD and f'"{COMMENT_KEYWORD}"' not in body and f"Comment {COMMENT_KEYWORD}" not in body:
        cta_lines.append(f'Comment "{COMMENT_KEYWORD}" to join {COMMUNITY_NAME} {FLAG_EMOJI}'.strip())
    if COMMUNITY_URL and COMMUNITY_URL not in body:
        cta_lines.append(f"→ {COMMUNITY_URL}")
    if cta_lines:
        joiner = "\n" if len(cta_lines) == 1 and cta_lines[0].startswith("→") else "\n\n"
        body = body + joiner + "\n".join(cta_lines)

    hashtags = HASHTAGS + (f" {LOCAL_HASHTAGS}" if local and LOCAL_HASHTAGS else "")
    return f"{body}\n\n{hashtags}".strip()


def write_carousel(story: dict) -> dict:
    """Write full 10-slide carousel content for a story."""
    prompt = (WRITE_PROMPT
        .replace("{headline}", story["headline"])
        .replace("{summary}", story.get("summary", ""))
        .replace("{raw_text}", story.get("raw_text", "")[:2000])
        .replace("{category}", story.get("category", "global_ai"))
    )

    text = _chat(WRITE_MODEL, prompt, 4000)
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"[selector] write_carousel parse failed:\n{text[:300]}")
    carousel = _strip_dashes(json.loads(text[start:end]))
    carousel["caption"] = ensure_caption_cta(
        carousel.get("caption", ""), local=story.get("category") == "local"
    )
    return carousel


def run(stories: list[dict], posted_urls: set, force_local: bool = False) -> tuple[dict, dict]:
    """Select top stories and write carousels. Retries next story if write fails."""
    # Filter already posted
    fresh = [s for s in stories if s["url"] not in posted_urls]
    print(f"[selector] {len(fresh)} fresh stories to score (removed {len(stories)-len(fresh)} already posted)")

    # Block content irrelevant to this audience
    _blocklist = [
        "anna's archive", "anna archive", "sci-hub", "libgen",
        "piracy", "torrent", "warez", "jailbreak iphone",
        "nfl", "nba", "premier league", "cricket",
    ]
    before = len(fresh)
    fresh = [s for s in fresh if not any(kw in s.get("headline", "").lower() for kw in _blocklist)]
    if len(fresh) < before:
        print(f"[selector] Blocked {before - len(fresh)} irrelevant stories")

    scored = score_stories(fresh)

    # Pick the best local and best global story, then order them so roughly
    # LOCAL_SHARE of posts lead with the local story (default 20% local, 80% global).
    local = next((s for s in scored if s.get("category") == "local"), None)
    global_ = next((s for s in scored if s.get("category") != "local"), None)

    lead_local = force_local or random.random() < LOCAL_SHARE
    if force_local and not local:
        print("[selector] Local story requested, but no local story was found today; using global.")
    ordered = [local, global_] if lead_local else [global_, local]
    print(f"[selector] Today's lead: {'local' if lead_local else 'global'} (local_share={LOCAL_SHARE})")
    picks = [s for s in ordered if s][:2]
    if not picks:
        picks = scored[:2]

    # Build a fallback pool — all scored stories not already in picks
    pick_urls = {s["url"] for s in picks}
    fallback_pool = [s for s in scored if s["url"] not in pick_urls]

    results = []
    for story in picks:
        print(f"[selector] Writing carousel for: {story['headline'][:60]}... (score: {story.get('score')})")
        try:
            carousel = write_carousel(story)
            results.append((story, carousel))
        except Exception as e:
            print(f"[selector] write_carousel failed: {e}")
            print(f"[selector] Trying next story from fallback pool...")
            # Try fallback stories one by one until one succeeds
            for fallback in fallback_pool:
                if fallback["url"] in {r[0]["url"] for r in results}:
                    continue
                print(f"[selector] Fallback: {fallback['headline'][:60]}...")
                try:
                    carousel = write_carousel(fallback)
                    results.append((fallback, carousel))
                    fallback_pool.remove(fallback)
                    break
                except Exception as e2:
                    print(f"[selector] Fallback also failed: {e2}")
                    continue

    return results


if __name__ == "__main__":
    import scraper
    stories = scraper.run()
    pairs = run(stories, set())
    for story, carousel in pairs:
        print(f"\n=== {story['headline']} ===")
        print(f"Cover: {carousel.get('cover_headline')}")
        print(f"Caption preview: {carousel.get('caption','')[:100]}")
