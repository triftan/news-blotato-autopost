import json
import os
import unittest
from unittest.mock import Mock, patch

import scraper


def _resp(body, content_type="application/json", status=200, headers=None):
    r = Mock(status_code=status)
    r.headers = {"content-type": content_type, **(headers or {})}
    r.text = body if isinstance(body, str) else json.dumps(body)
    r.json.return_value = body if not isinstance(body, str) else None
    r.raise_for_status = Mock()
    return r


class GoogleNewsDecodeTests(unittest.TestCase):
    def test_non_google_url_is_returned_unchanged(self):
        self.assertEqual(scraper.decode_google_news_url("https://bbc.com/x"), "https://bbc.com/x")

    def test_decode_failure_falls_back_to_original(self):
        url = "https://news.google.com/rss/articles/ABC?oc=5"
        with patch.object(scraper.requests, "get", side_effect=RuntimeError("blocked")):
            self.assertEqual(scraper.decode_google_news_url(url), url)

    def test_decodes_batchexecute_response(self):
        url = "https://news.google.com/rss/articles/ABC?oc=5"
        page = _resp('<c-wiz><div jscontroller="x" data-n-a-sg="SIG" data-n-a-ts="123"></div></c-wiz>', "text/html")
        inner = json.dumps(["garturlres", "https://www.bbc.com/news/articles/real", 1])
        batch = _resp(")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner]]), "text/plain")
        with patch.object(scraper.requests, "get", return_value=page), \
             patch.object(scraper.requests, "post", return_value=batch) as post:
            self.assertEqual(scraper.decode_google_news_url(url), "https://www.bbc.com/news/articles/real")
        self.assertIn("ABC", post.call_args.kwargs["data"])


class RedditViaSuperpowersTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("SUPERPOWERS_API_KEY")

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("SUPERPOWERS_API_KEY", None)
        else:
            os.environ["SUPERPOWERS_API_KEY"] = self.saved

    def test_skips_without_api_key(self):
        os.environ.pop("SUPERPOWERS_API_KEY", None)
        with patch.object(scraper.requests, "post") as post:
            self.assertEqual(scraper.fetch_reddit(["artificial"]), [])
        post.assert_not_called()

    def test_fetches_posts_over_mcp_event_stream(self):
        os.environ["SUPERPOWERS_API_KEY"] = "sp-key"
        now = int(scraper.datetime.now(scraper.timezone.utc).timestamp())
        posts = {"posts": [
            {"title": "OpenAI model jailbreak goes viral", "createdUtc": now,
             "url": "https://reddit.com/r/artificial/comments/1/x/",
             "selftext_preview": "submitted by /u/someone [link] [comments]"},
            {"title": "My cat photo", "createdUtc": now, "url": "https://reddit.com/2"},
        ]}
        init = _resp({"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"mcp-session-id": "s1"})
        notified = _resp("", "application/json", status=202)
        tool = _resp(
            "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": 2, "result": {
                "content": [{"type": "text", "text": json.dumps(posts)}]}}) + "\n\n",
            "text/event-stream",
        )
        with patch.object(scraper.requests, "post", side_effect=[init, notified, tool]) as post, \
             patch.object(scraper, "_local_subreddit", return_value="singapore"):
            stories = scraper.fetch_reddit(["artificial"])
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0]["source"], "r/artificial")
        self.assertEqual(stories[0]["reddit_score"], 500)
        last = post.call_args.kwargs
        self.assertEqual(last["headers"]["Authorization"], "Bearer sp-key")
        self.assertEqual(last["headers"]["Mcp-Session-Id"], "s1")
        self.assertEqual(last["json"]["params"]["name"], "reddit-get-posts")


if __name__ == "__main__":
    unittest.main()
