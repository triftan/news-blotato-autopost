import os
import unittest

import config_check


READY = {
    "account_handle": "@examplecreator",
    "community_name": "Example News",
    "community_url": "example.com/join",
    "comment_keyword": "NEWS",
    "blotato": {
        "instagram_account_id": "424242",
        "instagram_username": "examplecreator",
    },
}


class ConfigCheckTests(unittest.TestCase):
    def test_template_config_on_disk_is_still_a_placeholder(self):
        fields = config_check.placeholder_fields(config_check.load_config())
        self.assertIn("blotato.instagram_account_id", fields)
        self.assertIn("community_name", fields)

    def test_numeric_account_id_is_ready(self):
        self.assertEqual(config_check.placeholder_fields(READY), [])

    def test_non_numeric_account_id_blocks_posting(self):
        cfg = {
            **READY,
            "blotato": {**READY["blotato"], "instagram_account_id": "not-an-id"},
        }
        self.assertIn("blotato.instagram_account_id", config_check.placeholder_fields(cfg))

    def test_scheduled_fresh_copy_skips_instead_of_failing(self):
        original = os.environ.get("GITHUB_EVENT_NAME")
        os.environ["GITHUB_EVENT_NAME"] = "schedule"
        try:
            self.assertEqual(config_check.guard_unconfigured(config_check.load_config()), "skip")
            self.assertIsNone(config_check.guard_unconfigured(READY))
        finally:
            if original is None:
                os.environ.pop("GITHUB_EVENT_NAME", None)
            else:
                os.environ["GITHUB_EVENT_NAME"] = original

    def test_manual_run_fails_while_placeholders_remain(self):
        original = os.environ.pop("GITHUB_EVENT_NAME", None)
        try:
            self.assertEqual(config_check.guard_unconfigured(config_check.load_config()), "fail")
        finally:
            if original is not None:
                os.environ["GITHUB_EVENT_NAME"] = original


if __name__ == "__main__":
    unittest.main()
