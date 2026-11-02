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
