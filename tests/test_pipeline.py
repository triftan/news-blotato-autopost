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
        sources = ["pexels"] * 8 + ["gradient"] * 2
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
                ["pexels"],
                "run-123",
            )
            data = json.loads(Path(path).read_text())
        self.assertEqual(data["carousel"]["caption"], "Exact approved caption")
        self.assertEqual(data["story"]["url"], "https://example.com/story")


if __name__ == "__main__":
    unittest.main()
