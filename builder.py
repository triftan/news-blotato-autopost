"""Build HTML carousel from story data + images, then export 10 PNGs via Playwright."""
import asyncio
import base64
import html
import json
import os
from pathlib import Path

_cfg_path = Path(__file__).parent / "config.json"
with open(_cfg_path) as f:
    _CFG = json.load(f)
ACCOUNT_HANDLE = _CFG.get("account_handle", "@YOUR_INSTAGRAM_HANDLE")
COMMUNITY_URL  = _CFG.get("community_url", "YOUR_COMMUNITY_URL")
COMMUNITY_NAME = _CFG.get("community_name", "YOUR_BRAND_NAME")
COMMENT_KEYWORD = _CFG.get("comment_keyword", "YOUR_COMMENT_KEYWORD")
FLAG_EMOJI     = _CFG.get("flag_emoji", "🇲🇾")

# Replace logo.png with your own square image.
_LOGO_PATH = Path(__file__).parent / "logo.png"

SLIDE_W    = 1080
SLIDE_H    = 1350
VIEWPORT_W = 540
VIEWPORT_H = 675
SCALE      = SLIDE_W / VIEWPORT_W  # 2.0


def _img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _accent_line(text: str) -> str:
    import re
    return re.sub(r"\*\*(.*?)\*\*", r'<span class="acc">\1</span>', text)

_amber_line = _accent_line


def build_html(carousel: dict, image_paths: list[str], out_path: str) -> str:
    slides_html = []

    # Load logo
    logo_b64 = _img_to_b64(str(_LOGO_PATH)) if _LOGO_PATH.exists() else ""
    logo_mime = "image/png" if _LOGO_PATH.suffix.lower() == ".png" else "image/jpeg"
    logo_html = (
        f'<div class="logo-sticker"><img src="data:{logo_mime};base64,{logo_b64}" alt="logo"></div>'
        if logo_b64 else ""
    )
    handle = html.escape(ACCOUNT_HANDLE, quote=True)
    community_name = html.escape(COMMUNITY_NAME, quote=True)
    community_url = html.escape(COMMUNITY_URL, quote=True)
    comment_keyword = html.escape(COMMENT_KEYWORD, quote=True)

    # ── Slide 1: Cover ──────────────────────────────────────────────────────
    cover_b64  = _img_to_b64(image_paths[0]) if image_paths else ""
    meme_text  = carousel.get("meme_text", "")
    badge      = carousel.get("cover_badge", "AI NEWS")
    meme_html  = f'<div class="meme-bubble">{meme_text}</div>' if meme_text else ""

    slides_html.append(f"""
    <div class="slide cover-slide">
      <div class="cover-photo" style="background-image:url('data:image/jpeg;base64,{cover_b64}')"></div>
      <div class="cover-scrim"></div>
      <div class="top-line"></div>
      {logo_html}
      <span class="cover-handle">{handle}</span>
      {meme_html}
      <div class="cover-bottom">
        <div class="cover-source"><span class="src-line"></span>{community_name}<span class="src-line"></span></div>
        <div class="cover-badge">● {badge}</div>
        <h1 class="cover-h1">{carousel.get('cover_headline', 'AI NEWS')}</h1>
        <p class="cover-sub">{carousel.get('cover_subheadline', '')}</p>
        <div class="swipe-hint">SWIPE TO EXPLORE →</div>
        <div class="dots">{_dots(10, 0)}</div>
      </div>
      <div class="prog-track"><div class="prog-fill" style="width:10%"></div></div>
    </div>""")

    # ── Slides 2–9: Inner ───────────────────────────────────────────────────
    for i, slide in enumerate(carousel.get("slides", [])):
        idx     = i + 1
        img_b64 = _img_to_b64(image_paths[idx]) if idx < len(image_paths) else ""
        num     = slide.get("num", i + 2)
        pct     = int((num / 10) * 100)
        slides_html.append(f"""
    <div class="slide inner-slide">
      <div class="inner-photo" style="background-image:url('data:image/jpeg;base64,{img_b64}')"></div>
      <div class="inner-scrim"></div>
      <div class="top-line"></div>
      <div class="slide-num">{num:02d}<span class="num-total"> /10</span></div>
      <span class="inner-handle">{handle}</span>
      <div class="inner-bottom">
        <div class="label">{slide.get('label', '')}</div>
        <h2 class="inner-h2">{slide.get('headline', '')}</h2>
        <p class="insight">{slide.get('insight', '')}</p>
      </div>
      <div class="arr">›</div>
      <div class="prog-track"><div class="prog-fill" style="width:{pct}%"></div></div>
    </div>""")

    # ── Slide 10: CTA ───────────────────────────────────────────────────────
    cta_b64 = _img_to_b64(image_paths[-1]) if len(image_paths) >= 10 else ""
    slides_html.append(f"""
    <div class="slide cta-slide">
      <div class="cover-photo" style="background-image:url('data:image/jpeg;base64,{cta_b64}')"></div>
      <div class="cover-scrim"></div>
      <div class="top-line"></div>
      {logo_html}
      <div class="cta-inner">
        <span class="cover-handle">{handle}</span>
        <div class="cta-body">
          <h2 class="cta-h2">WANT MORE<br>STORIES LIKE THIS?</h2>
          <div class="cta-btn">Comment <span class="acc">{comment_keyword}</span></div>
          <p class="cta-desc">Join the {community_name} community<br>Get AI news straight to your DMs</p>
          <div class="cta-url">{community_url}</div>
        </div>
      </div>
      <div class="prog-track"><div class="prog-fill" style="width:100%"></div></div>
    </div>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,400;0,500;0,600;0,700;0,800;0,900;1,400&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#000; font-family:'Inter',system-ui,sans-serif; overflow:hidden; }}

  :root {{
    --bg:    #090909;
    --acc:   #C8714A;
    --text:  #F0EDE8;
    --dim:   rgba(240,237,232,0.65);
    --muted: rgba(240,237,232,0.28);
    --border:rgba(240,237,232,0.07);
  }}

  .viewport {{ width:{VIEWPORT_W}px; height:{VIEWPORT_H}px; overflow:hidden; position:relative; }}
  .track    {{ display:flex; width:{10 * VIEWPORT_W}px; transition:transform .3s ease; }}

  /* ── Base Slide ── */
  .slide {{
    width:{VIEWPORT_W}px; height:{VIEWPORT_H}px; flex-shrink:0;
    background:var(--bg); position:relative; overflow:hidden;
  }}

  /* Orange top rule */
  .top-line {{
    position:absolute; top:0; left:0; right:0; height:1.5px;
    background:var(--acc); z-index:10;
  }}

  /* Progress bar */
  .prog-track {{
    position:absolute; bottom:0; left:0; right:0; height:2px;
    background:var(--border); z-index:10;
  }}
  .prog-fill {{ height:100%; background:var(--acc); }}

  /* Logo sticker — top left */
  .logo-sticker {{
    position:absolute; top:16px; left:18px; z-index:8;
    width:52px; height:52px; border-radius:50%; overflow:hidden;
    box-shadow:0 2px 12px rgba(0,0,0,.5);
  }}
  .logo-sticker img {{ width:100%; height:100%; object-fit:cover; }}

  /* ── Cover & CTA (shared photo+scrim pattern) ───────────────────── */
  .cover-photo {{
    position:absolute; inset:0; z-index:1;
    background-size:cover; background-position:center top; opacity:1;
  }}
  .cover-scrim {{
    position:absolute; inset:0; z-index:2;
    background: linear-gradient(to top,
      rgba(0,0,0,.97) 0%,
      rgba(0,0,0,.90) 26%,
      rgba(0,0,0,.28) 54%,
      rgba(0,0,0,.04) 72%,
      transparent 100%);
  }}
  .cover-handle {{
    position:absolute; top:22px; right:20px; z-index:8;
    font-size:9px; color:rgba(255,255,255,.25); letter-spacing:1px;
    text-transform:lowercase;
  }}
  .meme-bubble {{
    position:absolute; top:86px; left:18px; z-index:8;
    max-width:75%;
    background:rgba(22,22,22,.94);
    border-radius:4px 18px 18px 18px;
    padding:12px 16px;
    font-size:13px; color:rgba(255,255,255,.90);
    line-height:1.55; font-style:italic;
    transform:rotate(-1.5deg);
    box-shadow:0 4px 28px rgba(0,0,0,.65);
    border:1px solid rgba(255,255,255,.07);
  }}
  .cover-bottom {{
    position:absolute; bottom:0; left:0; right:0; z-index:5;
    padding:0 22px 26px;
    display:flex; flex-direction:column; align-items:center;
  }}
  .cover-source {{
    font-size:9px; font-weight:700; letter-spacing:3px;
    color:rgba(255,255,255,.40); text-transform:uppercase;
    display:flex; align-items:center; gap:8px; width:100%;
    justify-content:center; margin-bottom:10px;
  }}
  .src-line {{ flex:1; max-width:44px; height:1px; background:rgba(255,255,255,.25); }}
  .cover-badge {{
    font-size:11px; font-weight:700; letter-spacing:1.5px;
    color:var(--acc); text-transform:uppercase; margin-bottom:10px;
  }}
  .cover-h1 {{
    font-size:36px; font-weight:900; color:#fff;
    line-height:1.07; text-transform:uppercase; letter-spacing:-.3px;
    text-align:center; margin-bottom:10px;
    text-shadow:0 2px 24px rgba(0,0,0,.5);
  }}
  .cover-sub {{
    font-size:12px; font-weight:600; color:rgba(255,255,255,.60);
    text-align:center; margin-bottom:14px; max-width:92%;
  }}
  .swipe-hint {{
    font-size:8px; letter-spacing:3.5px; color:rgba(255,255,255,.26);
    text-transform:uppercase; margin-bottom:9px;
  }}
  .dots {{ display:flex; gap:4px; align-items:center; }}
  .dot {{ width:5px; height:5px; border-radius:50%; background:rgba(240,237,232,.15); }}
  .dot.on {{ background:var(--acc); width:18px; border-radius:2px; }}

  /* ── Inner Slides ─────────────────────────────────────────────── */
  /* Full-bleed photo — fully visible */
  .inner-photo {{
    position:absolute; inset:0; z-index:1;
    background-size:cover; background-position:center; opacity:1;
  }}
  /* Gradient: transparent top → dark bottom (text zone ~40%) */
  .inner-scrim {{
    position:absolute; inset:0; z-index:2;
    background: linear-gradient(to top,
      rgba(0,0,0,.97) 0%,
      rgba(0,0,0,.93) 32%,
      rgba(0,0,0,.45) 56%,
      rgba(0,0,0,.06) 74%,
      transparent 100%);
  }}
  .slide-num {{
    position:absolute; top:16px; right:20px; z-index:6;
    font-size:11px; color:rgba(255,255,255,.35); letter-spacing:.5px;
    font-variant-numeric:tabular-nums;
  }}
  .num-total {{ opacity:.5; font-size:10px; }}
  .inner-handle {{
    position:absolute; top:20px; left:20px; z-index:6;
    font-size:9px; color:rgba(255,255,255,.25); letter-spacing:1px;
    text-transform:lowercase;
  }}
  /* Text anchored to bottom */
  .inner-bottom {{
    position:absolute; bottom:0; left:0; right:0; z-index:5;
    padding:0 24px 28px;
  }}
  .label {{
    font-size:9px; font-weight:700; letter-spacing:3px; text-transform:uppercase;
    color:var(--acc); display:flex; align-items:center; gap:8px; margin-bottom:12px;
  }}
  .label::before {{
    content:''; width:14px; height:1.5px; background:var(--acc);
    display:block; flex-shrink:0;
  }}
  .inner-h2 {{
    font-size:32px; font-weight:800; color:#fff;
    line-height:1.14; letter-spacing:-.4px; margin-bottom:12px;
    text-shadow:0 2px 16px rgba(0,0,0,.6);
  }}
  .insight {{
    font-size:14px; font-weight:500; color:var(--dim); line-height:1.55;
  }}
  .acc {{ color:var(--acc); }}
  .arr {{
    position:absolute; right:18px; bottom:22px; z-index:6;
    font-size:20px; color:var(--acc); opacity:.6; line-height:1;
  }}

  /* ── CTA ──────────────────────────────────────────────────────── */
  .cta-inner {{
    position:relative; z-index:5; height:100%;
    padding:18px 24px 28px;
    display:flex; flex-direction:column;
  }}
  .cta-body {{
    flex:1; display:flex; flex-direction:column;
    align-items:center; justify-content:center; text-align:center;
  }}
  .cta-h2     {{ font-size:28px; font-weight:900; color:#fff;
                 line-height:1.14; letter-spacing:-.4px; margin-bottom:22px;
                 text-shadow:0 2px 20px rgba(0,0,0,.5); }}
  .cta-btn    {{ font-size:13px; font-weight:700; color:#fff;
                 border:1.5px solid var(--acc); padding:11px 30px;
                 border-radius:30px; margin-bottom:20px; letter-spacing:.3px; }}
  .cta-desc   {{ font-size:12px; color:rgba(255,255,255,.60); line-height:1.65; margin-bottom:14px; }}
  .cta-url    {{ font-size:11px; font-weight:700; color:var(--acc); letter-spacing:.8px; }}
</style>
</head>
<body>
<div class="viewport">
  <div class="track" id="track">
{''.join(slides_html)}
  </div>
</div>
<script>
let cur=0;
function go(n){{
  cur=Math.max(0,Math.min(9,n));
  document.getElementById('track').style.transform=`translateX(-${{cur*{VIEWPORT_W}}}px)`;
}}
</script>
</body>
</html>"""

    with open(out_path, "w") as f:
        f.write(html)
    print(f"[builder] HTML written: {out_path}")
    return out_path


def _dots(total: int, active: int) -> str:
    return "".join(
        f'<div class="dot{"" if i != active else " on"}"></div>'
        for i in range(total)
    )


async def _export_pngs(html_path: str, out_dir: str, n_slides: int = 10) -> list[str]:
    from playwright.async_api import async_playwright

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            device_scale_factor=SCALE,
        )
        abs_path = os.path.abspath(html_path)
        await page.goto(f"file://{abs_path}", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        vp = await page.query_selector(".viewport")
        for i in range(n_slides):
            await page.evaluate(f"go({i})")
            await page.wait_for_timeout(400)
            out = f"{out_dir}/slide_{i+1:02d}.png"
            await vp.screenshot(path=out)
            paths.append(out)
            print(f"[builder] Exported slide {i+1}: {out}")

        await browser.close()

    return paths


def export_pngs(html_path: str, out_dir: str, n_slides: int = 10) -> list[str]:
    return asyncio.run(_export_pngs(html_path, out_dir, n_slides))


def run(carousel: dict, image_paths: list[str], run_id: str) -> list[str]:
    html_out = f"/tmp/carousel_{run_id}.html"
    png_dir  = os.path.expanduser(f"~/Downloads/carousels/{run_id}")

    build_html(carousel, image_paths, html_out)
    png_paths = export_pngs(html_out, png_dir)
    print(f"[builder] Done — {len(png_paths)} PNGs in {png_dir}")
    return png_paths
