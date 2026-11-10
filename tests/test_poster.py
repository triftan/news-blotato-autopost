import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

CHANNEL = "6a47686c5ab6d2f1069c7d07"


def _gql(data):
    response = Mock(status_code=200)
    response.json.return_value = {"data": data}
    return response


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("BUFFER_API_KEY", "GITHUB_TOKEN", "GITHUB_REPOSITORY")}
        os.environ["BUFFER_API_KEY"] = "  test-key  "
        os.environ["GITHUB_TOKEN"] = "gh-token"
        os.environ["GITHUB_REPOSITORY"] = "owner/repo"
        import poster
        self.poster = importlib.reload(poster)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _channel(self, **overrides):
        channel = {"id": CHANNEL, "name": "examplecreator", "service": "instagram",
                   "isDisconnected": False, "isLocked": False}
        channel.update(overrides)
        return _gql({"channel": channel})

    def test_validate_account_accepts_connected_instagram_channel(self):
        with patch.object(self.poster.requests, "post", return_value=self._channel()) as post:
            channel = self.poster.validate_account(CHANNEL, "@ExampleCreator")
        self.assertEqual(channel["name"], "examplecreator")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kwargs["json"]["variables"], {"id": CHANNEL})

    def test_validate_account_rejects_non_instagram_channel(self):
        with patch.object(self.poster.requests, "post", return_value=self._channel(service="linkedin")):
            with self.assertRaisesRegex(RuntimeError, "not Instagram"):
                self.poster.validate_account(CHANNEL)

    def test_validate_account_rejects_disconnected_channel(self):
        with patch.object(self.poster.requests, "post", return_value=self._channel(isDisconnected=True)):
            with self.assertRaisesRegex(RuntimeError, "disconnected"):
                self.poster.validate_account(CHANNEL)

    def test_validate_account_only_warns_on_stale_username(self):
        with patch.object(self.poster.requests, "post", return_value=self._channel(name="oldname")):
            channel = self.poster.validate_account(CHANNEL, "examplecreator")
        self.assertEqual(channel["id"], CHANNEL)

    def test_graphql_errors_are_raised(self):
        response = Mock(status_code=200)
        response.json.return_value = {"errors": [{"message": "Not authorized"}]}
        with patch.object(self.poster.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Not authorized"):
                self.poster.validate_account(CHANNEL)

    def test_missing_api_key_fails_before_network(self):
        os.environ["BUFFER_API_KEY"] = "   "
        with patch.object(self.poster.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "BUFFER_API_KEY is missing or empty"):
                self.poster.validate_account(CHANNEL)
        post.assert_not_called()

    def test_upload_image_commits_jpeg_and_returns_raw_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "slide_01.png"
            Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(png)
            with patch.object(self.poster.requests, "put", return_value=Mock(status_code=201)) as put:
                url = self.poster.upload_image(str(png), "run-1")
        self.assertEqual(
            url, "https://raw.githubusercontent.com/owner/repo/media/slides/run-1/slide_01.jpg"
        )
        self.assertEqual(
            put.call_args.args[0],
            "https://api.github.com/repos/owner/repo/contents/slides/run-1/slide_01.jpg",
        )
        self.assertEqual(put.call_args.kwargs["json"]["branch"], "media")

    def test_post_carousel_sends_images_and_instagram_metadata(self):
        response = _gql({"createPost": {"post": {"id": "p1", "status": "sending"}}})
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            post_id = self.poster.post_carousel(CHANNEL, "Caption", ["https://img/1.jpg", "https://img/2.jpg"])
        self.assertEqual(post_id, "p1")
        data = post.call_args.kwargs["json"]["variables"]["input"]
        self.assertEqual(data["channelId"], CHANNEL)
        self.assertEqual(data["mode"], "shareNow")
        self.assertEqual(data["assets"], [{"image": {"url": "https://img/1.jpg"}},
                                          {"image": {"url": "https://img/2.jpg"}}])
        self.assertEqual(data["metadata"]["instagram"], {"type": "post", "shouldShareToFeed": True})

    def test_post_carousel_draft_mode_saves_draft(self):
        response = _gql({"createPost": {"post": {"id": "p1", "status": "draft"}}})
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            self.poster.post_carousel(CHANNEL, "Caption", ["https://img/1.jpg"], draft=True)
        data = post.call_args.kwargs["json"]["variables"]["input"]
        self.assertTrue(data["saveToDraft"])
        self.assertEqual(data["mode"], "addToQueue")

    def test_post_carousel_schedules_with_due_at(self):
        response = _gql({"createPost": {"post": {"id": "p1", "status": "scheduled"}}})
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            self.poster.post_carousel(CHANNEL, "Caption", ["https://img/1.jpg"], due_at="2026-11-11T11:00:00+08:00")
        data = post.call_args.kwargs["json"]["variables"]["input"]
        self.assertEqual(data["mode"], "customScheduled")
        self.assertEqual(data["dueAt"], "2026-11-11T11:00:00+08:00")

    def test_post_carousel_raises_on_mutation_error(self):
        response = _gql({"createPost": {"message": "Invalid image"}})
        with patch.object(self.poster.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Invalid image"):
                self.poster.post_carousel(CHANNEL, "Caption", ["https://img/1.jpg"])

    def test_post_carousel_keeps_first_five_hashtags(self):
        caption = "Read this #One #Two #Three #Four #Five #Six #Seven"
        response = _gql({"createPost": {"post": {"id": "p1", "status": "sending"}}})
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            self.poster.post_carousel(CHANNEL, caption, ["https://img/1.jpg"])
        text = post.call_args.kwargs["json"]["variables"]["input"]["text"]
        self.assertEqual(text, "Read this #One #Two #Three #Four #Five")

    def test_wait_for_publication_polls_until_sent(self):
        sending = _gql({"post": {"id": "p1", "status": "sending"}})
        sent = _gql({"post": {"id": "p1", "status": "sent", "externalLink": "https://instagram.com/p/x"}})
        with (
            patch.object(self.poster.requests, "post", side_effect=[sending, sent]),
            patch.object(self.poster.time, "sleep"),
        ):
            result = self.poster.wait_for_publication("p1", timeout=30, poll_interval=10)
        self.assertEqual(result["status"], "sent")

    def test_wait_for_publication_raises_buffer_error(self):
        failed = _gql({"post": {"id": "p1", "status": "error", "error": {"message": "Media rejected"}}})
        with patch.object(self.poster.requests, "post", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Media rejected"):
                self.poster.wait_for_publication("p1", timeout=30, poll_interval=10)


if __name__ == "__main__":
    unittest.main()
