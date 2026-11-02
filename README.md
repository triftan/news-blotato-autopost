# Daily AI news Instagram carousel

This is a template. Click **Use this template**, add three secrets, edit `config.json`, replace the logo, and a GitHub Action will build a 10-slide AI-news carousel and post it to your Instagram every day.

![How the bot posts](docs/how-it-works.png)

The picture is the daily flow. The handle and brand painted on that sample are illustrations. Your slides use the brand name, handle, comment keyword, and logo you set in step 4. A printable copy of the same picture is in [docs/how-it-works.pdf](docs/how-it-works.pdf).

One workflow does the whole job:

1. It checks that Buffer can see your Instagram channel.
2. It scrapes Google News plus tech sites for AI stories.
3. An LLM on OpenRouter (Claude by default) scores the stories, skips anything already in `posted_urls.json`, and writes 10 slides and a caption.
4. Pixabay supplies a photo for each slide. The bot will not reuse a photo it has already used.
5. Playwright renders the slides with your logo. If more than two slides have no photo, a live post is blocked.
6. The slides are saved as JPEGs on the repo's `media` branch, and Buffer publishes them to Instagram as a carousel.
7. The story URL is appended to `posted_urls.json` and committed back, so the same story is not posted again.

A run also refuses to post if the last successful post was less than 7 hours ago.

## What it costs

| Service | What you pay |
| --- | --- |
| GitHub Actions | Free on the public GitHub plan (this template runs one job a day). |
| Pixabay | Free API key. |
| OpenRouter | Pay per use. Scoring uses Claude Haiku and the carousel text uses Claude Sonnet by default. Change the models under `openrouter` in `config.json`. |
| Buffer | Free or paid plan. Buffer connects your Instagram account and publishes the carousel. |

You do not put API keys in the code. The workflow reads `OPENROUTER_API_KEY`, `BUFFER_API_KEY`, and `PIXABAY_API_KEY` from GitHub Actions secrets. It also uses the built-in `GITHUB_TOKEN` to host slide images on the `media` branch, because Buffer's API only accepts public image URLs. Keep the repository public so those URLs work.

## Setup

### 1. Create your own copy

On this repository, click **Use this template**, then **Create a new repository**. Leave it public unless you have GitHub Actions minutes on a private repo. The new repository is yours. The schedule will not publish anything until you finish the steps below.

### 2. Create the three accounts and copy the keys

- [OpenRouter](https://openrouter.ai/settings/keys) — create an API key and add some credit.
- [Buffer](https://publish.buffer.com/settings/api) — connect your Instagram Business or Creator account as a channel, then create an API key on that page. You also need the channel id, a 24-character code. It shows in the address bar when you open the channel in Buffer.
- [Pixabay API](https://pixabay.com/api/docs/) — sign in and copy your free API key.

### 3. Add the three secrets

In your new repository open **Settings → Secrets and variables → Actions → New repository secret**. Add these three as **Repository secrets**, not Environment secrets, with exactly these names:

- `OPENROUTER_API_KEY`
- `BUFFER_API_KEY`
- `PIXABAY_API_KEY`

### 4. Edit `config.json` and replace the logo

Open `config.json` and replace every value that contains `YOUR_`:

- `buffer.channel_id` — the 24-character Buffer channel id from step 2.
- `buffer.instagram_username` — the Instagram username as Buffer shows it, without the `@`.
- `account_handle`, `community_name`, `community_url`, and `comment_keyword` — how the slides and caption name you, and the word people comment to join.
- `posting.hashtags` — up to five hashtags. The poster keeps only the first five.
- `google_news_queries` and `subreddits` — what the bot searches. The file ships with 16 global queries (AI news, viral, hacks, discoveries, controversy) and 4 Singapore queries.
- `local_share` — how often the post leads with a local story. `0.2` means about 20% Singapore and 80% global.
- `country`, `local_keywords`, `government_bodies`, `local_landmarks` — the local market. Change these together if you cover somewhere else.

Replace `logo.png` with a square image of your own logo. A simple PNG or the existing filename is enough. The circle that says LOGO is only a placeholder.

### 5. Let Actions write back to the repository

Open **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**. Save.

The workflow already requests `contents: write`. That setting is what allows a fresh copy to commit `posted_urls.json` after a real post. Without it, the post can succeed and the next day will not remember it.

### 6. Dry run

Open **Actions → AI News Carousel → Run workflow**. Tick **Dry run** and run it.

A dry run builds the slides and uploads them as an artifact. It does not call Instagram. When the run finishes, open it, scroll to **Artifacts**, and download `carousel-slides-...`. You should see ten PNGs plus `review_manifest.json` (the story, the caption, and where each photo came from).

The first dry run fails on purpose if `config.json` still contains `YOUR_` placeholders. The log tells you which fields to edit. Fill those in and run it again.

### 7. Go live

Run **AI News Carousel** again and leave **Dry run** unticked. Or wait for the schedule. After a real post, the Action commits `posted_urls.json` so that URL is not used again.

You can also run **Preflight** any time. It checks the OpenRouter and Pixabay keys, and that the Buffer key can see the Instagram channel in `config.json`.

## Change the posting time

The schedule is in `.github/workflows/ai-news-carousel.yml`:

```yaml
- cron: '0 3 * * *'
```

GitHub cron is always **UTC**, not your local time. `0 3 * * *` means minute 0 of hour 3, every day: **03:00 UTC**. That is 11:00 in Singapore (UTC+8).

Edit the first number for the minute and the second number for the hour. `30 15 * * *` is 15:30 UTC. The workflow file has a short comment next to the line. After you commit the change, the next run uses the new time. GitHub can start a scheduled job a few minutes late when Actions is busy.

## Troubleshooting

**The workflow failed immediately and the log talks about placeholders.** `config.json` still has `YOUR_` text, or the account id is not a number. Edit the fields named in the log. A scheduled run on a fresh copy does not fail all night: it skips live posting until the account id is set.

**Preflight failed.** The log names the key or setting at fault. The usual cause is a `buffer.channel_id` that belongs to a different Buffer account, or a username that does not match that channel. A missing secret fails here too.

**Dry run slides are plain dark gradients, or a live run says the visual quality gate blocked publication.** `PIXABAY_API_KEY` is missing or rejected, so the bot could not download photos. A live post stops when more than two of the ten slides have no photo. Fix the secret and dry-run again.

**The run posted, but `posted_urls.json` did not change.** Workflow permissions are still read-only. Repeat step 5, then run once more. Until that file updates, a later run can pick the same story.

**It posted, then the next manual run did nothing.** The bot skips a live post when the last one was less than 7 hours ago. A dry run still builds slides during that window.

**The Action cannot find Python dependencies or Chromium.** Leave the workflow's "Install dependencies" step as it is. It installs `requirements.txt` and Playwright's Chromium on every run. You do not install those on your own computer unless you want to run `python pipeline.py --dry-run` locally.

## Run it on your own computer

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export OPENROUTER_API_KEY=...
export BUFFER_API_KEY=...
export PIXABAY_API_KEY=...
python pipeline.py --dry-run
```

Slides land in `~/Downloads/carousels/`. `--dry-run` skips Instagram. Omit it only when `config.json` has your real account id and you want a live post.
