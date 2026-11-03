import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import logger


class AngleHistoryTests(unittest.TestCase):
    def test_log_posted_records_angle_and_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "posted_urls.json"
            log.write_text(json.dumps({"urls": [], "posts": [], "angle_history": ["NUMBERS"]}))
            with patch.object(logger, "_LOG_FILE", log):
                logger.log_posted({"url": "u", "headline": "h"}, "p1", {"angle_name": "Controversial"})
                self.assertEqual(logger.get_recent_angles(3), ["CONTROVERSIAL", "NUMBERS"])


class TopicHistoryTests(unittest.TestCase):
    def test_recent_topics_keep_last_week_and_new_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "posted_urls.json"
            log.write_text(json.dumps({"urls": [], "posts": [], "topic_history": [
                {"headline": "Old story", "date": "2020-01-01T00:00:00+00:00"},
                {"headline": "Queued for later", "date": "2099-01-01T00:00:00+00:00"},
            ]}))
            with patch.object(logger, "_LOG_FILE", log):
                logger.log_posted({"url": "u", "headline": "Binance hack"}, "p1", {})
                topics = logger.get_recent_topics(days=7)
        self.assertEqual(topics, ["Queued for later", "Binance hack"])
