import tempfile
import unittest
from pathlib import Path

from PIL import Image

import builder


class BuildHtmlTests(unittest.TestCase):
    def test_build_html_writes_page_with_brand_details(self):
        carousel = {
            "cover_headline": "Cover\nLine two",
            "cover_subheadline": "Sub",
            "cover_badge": "BREAKING",
            "meme_text": "",
            "slides": [
                {"num": i, "label": "LABEL", "headline": f"Headline {i}", "insight": "Insight"}
                for i in range(2, 10)
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            images = []
            for i in range(10):
                path = Path(tmp) / f"slide_{i + 1:02d}.jpg"
                Image.new("RGB", (8, 10)).save(path)
                images.append(str(path))
            out = Path(tmp) / "carousel.html"
            builder.build_html(carousel, images, str(out))
            page = out.read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("Headline 9", page)


if __name__ == "__main__":
    unittest.main()
