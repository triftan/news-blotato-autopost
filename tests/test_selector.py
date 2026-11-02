import unittest

import selector


class CaptionCtaTests(unittest.TestCase):
    def test_adds_missing_link_and_keeps_hashtags_last(self):
        caption = 'Hook.\n\nComment "AI" to join Brand\n\n#AINews #AI'
        out = selector.ensure_caption_cta(caption)
        self.assertIn(selector.COMMUNITY_URL, out)
        self.assertTrue(out.endswith("#AINews #AI"))
        self.assertEqual(out.count(f'"{selector.COMMENT_KEYWORD}"'), 1)

    def test_adds_full_cta_and_default_hashtags_when_missing(self):
        out = selector.ensure_caption_cta("Hook only")
        self.assertIn(f'Comment "{selector.COMMENT_KEYWORD}"', out)
        self.assertIn(selector.COMMUNITY_URL, out)
        self.assertTrue(out.endswith(selector.HASHTAGS))

    def test_leaves_complete_caption_alone(self):
        caption = f'Hook\n\nComment "{selector.COMMENT_KEYWORD}" to join\n→ {selector.COMMUNITY_URL}\n\n{selector.HASHTAGS}'
        self.assertEqual(selector.ensure_caption_cta(caption), caption)


if __name__ == "__main__":
    unittest.main()
