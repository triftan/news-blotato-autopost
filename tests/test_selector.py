import unittest

import selector


class CaptionCtaTests(unittest.TestCase):
    def test_adds_missing_link_and_keeps_hashtags_last(self):
        caption = 'Hook.\n\nComment "AI" to join Brand\n\n#AINews #AI'
        out = selector.ensure_caption_cta(caption)
        self.assertIn(selector.COMMUNITY_URL, out)
        self.assertTrue(out.endswith(selector.HASHTAGS))
        self.assertEqual(out.count(f'"{selector.COMMENT_KEYWORD}"'), 1)

    def test_adds_full_cta_and_default_hashtags_when_missing(self):
        out = selector.ensure_caption_cta("Hook only")
        self.assertIn(f'Comment "{selector.COMMENT_KEYWORD}"', out)
        self.assertIn(selector.COMMUNITY_URL, out)
        self.assertTrue(out.endswith(selector.HASHTAGS))

    def test_leaves_complete_caption_alone(self):
        caption = f'Hook\n\nComment "{selector.COMMENT_KEYWORD}" to join\n→ {selector.COMMUNITY_URL}\n\n{selector.HASHTAGS}'
        self.assertEqual(selector.ensure_caption_cta(caption), caption)


    def test_singapore_hashtag_only_on_local_stories(self):
        global_caption = selector.ensure_caption_cta("Hook\n\n#AINews #Singapore")
        local_caption = selector.ensure_caption_cta("Hook", local=True)
        self.assertNotIn("#Singapore", global_caption)
        self.assertTrue(local_caption.endswith("#Singapore"))


class DashRemovalTests(unittest.TestCase):
    def test_replaces_em_and_en_dashes(self):
        self.assertEqual(
            selector.remove_dashes("AI spree — with no profit."), "AI spree, with no profit."
        )
        self.assertEqual(selector.remove_dashes("Big news – really big!"), "Big news, really big!")

    def test_keeps_number_ranges_readable(self):
        self.assertEqual(selector.remove_dashes("From 2024–2026"), "From 2024-2026")

    def test_strip_dashes_walks_nested_carousel(self):
        carousel = {"caption": "A — B", "slides": [{"headline": "C — D"}]}
        cleaned = selector._strip_dashes(carousel)
        self.assertEqual(cleaned["caption"], "A, B")
        self.assertEqual(cleaned["slides"][0]["headline"], "C, D")


if __name__ == "__main__":
    unittest.main()
