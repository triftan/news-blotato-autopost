import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.original_api_key = os.environ.get("BLOTATO_API_KEY")
        os.environ["BLOTATO_API_KEY"] = "  test-key  "
        import poster
        self.poster = importlib.reload(poster)

    def tearDown(self):
        if self.original_api_key is None:
            os.environ.pop("BLOTATO_API_KEY", None)
        else:
            os.environ["BLOTATO_API_KEY"] = self.original_api_key

    def test_validate_account_accepts_configured_instagram(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "items": [{"id": "424242", "platform": "instagram", "username": "examplecreator"}]
        }
        with patch.object(self.poster.requests, "get", return_value=response) as get:
            account = self.poster.validate_account("424242", "examplecreator")
        self.assertEqual(account["username"], "examplecreator")
        get.assert_called_once_with(
            "https://backend.blotato.com/v2/users/me/accounts",
            headers={"blotato-api-key": "test-key", "Accept": "application/json"},
            params={"platform": "instagram"},
            timeout=30,
        )

    def test_validate_account_rejects_stale_account_id(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "items": [{"id": "99999", "platform": "instagram", "username": "other"}]
        }
        with patch.object(self.poster.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "Configured Instagram account 424242 is not connected"):
                self.poster.validate_account("424242")

    def test_validate_account_rejects_wrong_username(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "items": [{"id": "424242", "platform": "instagram", "username": "wrongaccount"}]
        }
        with patch.object(self.poster.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "does not match expected Instagram account"):
                self.poster.validate_account("424242", "examplecreator")

    def test_api_error_does_not_expose_key(self):
        response = Mock(status_code=401, text='{"message":"Invalid API key"}')
        with patch.object(self.poster.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, r"Blotato authentication check failed \(HTTP 401\)") as error:
                self.poster.validate_account("424242")
        self.assertNotIn("test-key", str(error.exception))

    def test_whitespace_key_fails_before_network(self):
        os.environ["BLOTATO_API_KEY"] = "   "
        with patch.object(self.poster.requests, "get") as get:
            with self.assertRaisesRegex(RuntimeError, "BLOTATO_API_KEY is missing or empty"):
                self.poster.validate_account("424242")
        get.assert_not_called()

    def test_upload_uses_presigned_flow_and_image_mime(self):
        create_response = Mock(status_code=201)
        create_response.json.return_value = {
            "presignedUrl": "https://uploads.example/signed",
            "publicUrl": "https://database.blotato.com/public/slide.jpg",
        }
        put_response = Mock(status_code=200)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "slide.jpg"
            image.write_bytes(b"jpeg-data")
            with (
                patch.object(self.poster.requests, "post", return_value=create_response) as post,
                patch.object(self.poster.requests, "put", return_value=put_response) as put,
            ):
                url = self.poster.upload_image(str(image))
        self.assertEqual(url, "https://database.blotato.com/public/slide.jpg")
        post.assert_called_once_with(
            "https://backend.blotato.com/v2/media/uploads",
            headers={"blotato-api-key": "test-key", "Accept": "application/json"},
            json={"filename": "slide.jpg"},
            timeout=30,
        )
        self.assertEqual(put.call_args.kwargs["headers"], {"Content-Type": "image/jpeg"})
        self.assertEqual(put.call_args.kwargs["timeout"], 120)

    def test_post_payload_is_instagram_carousel(self):
        response = Mock(status_code=201)
        response.json.return_value = {"postSubmissionId": "submission-123"}
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            result = self.poster.post_carousel("424242", "Caption", ["https://img/1.png", "https://img/2.png"])
        self.assertEqual(result, "submission-123")
        self.assertEqual(post.call_args.kwargs["json"], {
            "post": {
                "accountId": "424242",
                "content": {
                    "platform": "instagram",
                    "text": "Caption",
                    "mediaUrls": ["https://img/1.png", "https://img/2.png"],
                },
                "target": {"targetType": "instagram"},
            }
        })

    def test_post_payload_limits_instagram_caption_to_five_hashtags(self):
        response = Mock(status_code=201)
        response.json.return_value = {"postSubmissionId": "submission-123"}
        caption = "News #AI #Local #Daily #Tech #Automation #Agents #Future"
        with patch.object(self.poster.requests, "post", return_value=response) as post:
            self.poster.post_carousel("424242", caption, ["https://img/1.png"])
        posted_caption = post.call_args.kwargs["json"]["post"]["content"]["text"]
        self.assertEqual(posted_caption.count("#"), 5)
        self.assertIn("#Automation", posted_caption)
        self.assertNotIn("#Agents", posted_caption)
        self.assertNotIn("#Future", posted_caption)

    def test_wait_for_publication_returns_live_url(self):
        in_progress = Mock(status_code=200)
        in_progress.json.return_value = {"status": "in-progress"}
        published = Mock(status_code=200)
        published.json.return_value = {
            "status": "published",
            "publicUrl": "https://www.instagram.com/p/example/",
        }
        with (
            patch.object(self.poster.requests, "get", side_effect=[in_progress, published]),
            patch.object(self.poster.time, "sleep"),
        ):
            result = self.poster.wait_for_publication("submission-123", timeout=30, poll_interval=10)
        self.assertEqual(result["publicUrl"], "https://www.instagram.com/p/example/")

    def test_wait_for_publication_raises_on_failed_post(self):
        failed = Mock(status_code=200)
        failed.json.return_value = {"status": "failed", "errorMessage": "Instagram rejected post"}
        with patch.object(self.poster.requests, "get", return_value=failed):
            with self.assertRaisesRegex(RuntimeError, "Instagram rejected post"):
                self.poster.wait_for_publication("submission-123", timeout=30, poll_interval=10)


if __name__ == "__main__":
    unittest.main()
