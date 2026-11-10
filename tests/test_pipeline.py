import json
import tempfile
import unittest
from pathlib import Path

import pipeline


class VisualQualityGateTests(unittest.TestCase):
    def test_live_post_is_blocked_when_most_slides_are_gradients(self):
        with self.assertRaisesRegex(RuntimeError, "Visual quality gate blocked"):
            pipeline.check_visual_quality(["gradient"] * 10, dry_run=False)

    def test_dry_run_is_allowed_for_visual_inspection(self):
        count = pipeline.check_visual_quality(["gradient"] * 10, dry_run=True)
        self.assertEqual(count, 10)

    def test_live_post_allows_up_to_two_gradient_fallbacks(self):
        sources = ["pixabay"] * 8 + ["gradient"] * 2
        count = pipeline.check_visual_quality(sources, dry_run=False)
        self.assertEqual(count, 2)


class CarouselFactValidationTests(unittest.TestCase):
    def test_prompt_preserves_compound_source_scope(self):
        self.assertIn(
            "never narrow it to \"just data centres\"",
            pipeline.selector.WRITE_PROMPT,
        )

    def test_rejects_conflicting_half_year_period(self):
        story = {"headline": "Approved investments in 1H2026"}
        carousel = {"slides": [{"headline": "Approved investments in 1H2025"}]}
        with self.assertRaisesRegex(ValueError, "period conflicts"):
            pipeline.validate_carousel_facts(story, carousel)

    def test_allows_matching_half_year_period(self):
        story = {"headline": "Approved investments in 1H2026"}
        carousel = {"slides": [{"headline": "Approved investments in 1H2026"}]}
        pipeline.validate_carousel_facts(story, carousel)

    def test_review_manifest_preserves_exact_caption_and_story(self):
        with tempfile.TemporaryDirectory() as output_dir:
            slide = Path(output_dir) / "slide_01.png"
            slide.touch()
            path = pipeline.write_review_manifest(
                [str(slide)],
                {"headline": "Verified story", "url": "https://example.com/story"},
                {"caption": "Exact approved caption"},
                ["pixabay"],
                "run-123",
            )
            data = json.loads(Path(path).read_text())
        self.assertEqual(data["carousel"]["caption"], "Exact approved caption")
        self.assertEqual(data["story"]["url"], "https://example.com/story")



class OnePostPerDayTests(unittest.TestCase):
    def test_skips_when_buffer_already_has_a_post_today(self):
        from unittest.mock import patch
        with patch.object(pipeline.poster, "validate_account"), \
             patch.object(pipeline.poster, "posts_between",
                          return_value=[{"status": "scheduled", "dueAt": "x", "text": "queued"}]) as lookup, \
             patch.object(pipeline.scraper, "run") as scrape:
            pipeline.run()
        scrape.assert_not_called()
        start, end = lookup.call_args.args[1], lookup.call_args.args[2]
        self.assertTrue(start.endswith("+08:00") and "T00:00:00" in start)
        self.assertIn("T23:59:59", end)

    def test_continues_when_today_is_free(self):
        from unittest.mock import patch
        with patch.object(pipeline.poster, "validate_account"), \
             patch.object(pipeline.poster, "posts_between", return_value=[]), \
             patch.object(pipeline.scraper, "run", return_value=[]) as scrape:
            with self.assertRaises(SystemExit):
                pipeline.run()
        scrape.assert_called_once()



class ManualSpecTests(unittest.TestCase):
    def test_manual_dry_run_builds_without_scraping_or_posting(self):
        from unittest.mock import patch
        spec = {
            "story": {"headline": "Test launch", "url": "https://example.com/a", "category": "global_ai"},
            "carousel": {"cover_headline": "Big \u2014 news", "slides": [{"num": 2, "headline": "H"}],
                         "caption": "Hook line"},
            "images": [{"gradient": True}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec))
            png = Path(tmp) / "slide_01.png"
            png.touch()
            with patch.object(pipeline.scraper, "run") as scrape, \
                 patch.object(pipeline.builder, "run", return_value=[str(png)]) as build, \
                 patch.object(pipeline.poster, "run") as post:
                pipeline.run(dry_run=True, manual_spec=str(path))
            manifest = json.loads((Path(tmp) / "review_manifest.json").read_text())
        scrape.assert_not_called()
        post.assert_not_called()
        carousel = build.call_args.args[0]
        self.assertEqual(carousel["cover_headline"], "Big, news")
        self.assertIn("brandonlee.ai/group", manifest["carousel"]["caption"])


if __name__ == "__main__":
    unittest.main()
