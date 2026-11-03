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



class JsonAndFallbackTests(unittest.TestCase):
    def test_parse_json_repairs_missing_comma(self):
        data = selector._parse_json('```json\n{"a": "x" "slides": [1, 2,]}\n```', "{")
        self.assertEqual(data["slides"], [1, 2])

    def test_write_carousel_retries_after_bad_json(self):
        from unittest.mock import patch
        good = '{"caption": "Hook", "slides": [{"num": 2, "headline": "H"}]}'
        with patch.object(selector, "_chat", side_effect=["not json at all", good]) as chat:
            carousel = selector.write_carousel({"headline": "x", "category": "global_ai"})
        self.assertEqual(chat.call_count, 2)
        self.assertTrue(chat.call_args_list[0].kwargs["json_mode"])
        self.assertFalse(chat.call_args_list[1].kwargs["json_mode"])
        self.assertEqual(carousel["slides"][0]["headline"], "H")

    def test_local_lead_falls_back_to_another_local_story(self):
        from unittest.mock import patch
        stories = [
            {"headline": "SG one", "url": "u1", "category": "local", "raw_text": "x" * 700},
            {"headline": "SG two", "url": "u2", "category": "local", "raw_text": "x" * 700},
            {"headline": "Global", "url": "u3", "category": "global_ai", "raw_text": "x" * 700},
        ]
        scored = [dict(s, score=90 - i) for i, s in enumerate(stories)]

        def fake_write(story, recent_angles=None):
            if story["url"] == "u1":
                raise ValueError("bad json")
            return {"caption": "c", "slides": [{}]}

        with patch.object(selector, "score_stories", return_value=scored), \
             patch.object(selector, "write_carousel", side_effect=fake_write):
            results = selector.run(stories, set(), force_local=True)
        self.assertEqual(results[0][0]["url"], "u2")


    def test_quality_gate_picks_global_when_local_is_weak(self):
        from unittest.mock import patch
        stories = [
            {"headline": "Global", "url": "g", "category": "global_ai", "score": 80},
            {"headline": "SG weak", "url": "s", "category": "local", "score": selector.MIN_LOCAL_SCORE - 1},
        ]
        with patch.object(selector, "score_stories", return_value=stories), \
             patch.object(selector, "write_carousel", return_value={"caption": "c", "slides": [{}]}):
            results = selector.run(stories, set())
        self.assertEqual(results[0][0]["url"], "g")

    def test_quality_gate_lets_strong_local_lead(self):
        from unittest.mock import patch
        stories = [
            {"headline": "Global", "url": "g", "category": "global_ai", "score": 95},
            {"headline": "SG strong", "url": "s", "category": "local", "score": selector.MIN_LOCAL_SCORE},
        ]
        with patch.object(selector, "score_stories", return_value=stories), \
             patch.object(selector, "write_carousel", return_value={"caption": "c", "slides": [{}]}):
            results = selector.run(stories, set())
        self.assertEqual(results[0][0]["url"], "s")


    def test_write_carousel_tells_writer_recent_angles(self):
        from unittest.mock import patch
        good = '{"caption": "Hook", "slides": [{"num": 2, "headline": "H"}]}'
        with patch.object(selector, "_chat", return_value=good) as chat:
            selector.write_carousel({"headline": "x", "category": "global_ai"}, ["NUMBERS", "CONTROVERSIAL"])
        prompt = chat.call_args.args[1]
        self.assertIn("newest first: NUMBERS, CONTROVERSIAL", prompt)


    def test_stories_about_recent_topics_are_skipped(self):
        from unittest.mock import patch
        import json as _json
        stories = [
            {"headline": "BBC: Binance users withdraw $3.6bn", "url": "a", "category": "global_ai", "source": "BBC", "raw_text": "x" * 700},
            {"headline": "Robots start working on their own", "url": "b", "category": "global_ai", "source": "X", "raw_text": "x" * 700},
        ]
        scores = _json.dumps([
            {"index": 0, "score": 95, "angle": 8, "same_as_recent": True},
            {"index": 1, "score": 70, "angle": 7, "same_as_recent": False},
        ])
        good = {"caption": "c", "slides": [{}]}
        with patch.object(selector, "_chat", return_value=scores) as chat, \
             patch.object(selector, "write_carousel", return_value=good), \
             patch("logger.get_recent_topics", return_value=["North Korea Binance hack"]):
            results = selector.run(stories, set(), extra_topics=["Queued: crypto heist"])
        self.assertEqual(results[0][0]["url"], "b")
        prompt = chat.call_args.args[1]
        self.assertIn("- North Korea Binance hack", prompt)
        self.assertIn("- Queued: crypto heist", prompt)


if __name__ == "__main__":
    unittest.main()
