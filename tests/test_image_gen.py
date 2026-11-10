import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


class ImageGenerationFallbackTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PIXABAY_API_KEY", None)
        import image_gen
        self.image_gen = importlib.reload(image_gen)

    def test_gemini_fallback_is_not_part_of_the_pipeline(self):
        self.assertFalse(hasattr(self.image_gen, "GEMINI_API_KEY"))
        self.assertFalse(hasattr(self.image_gen, "_generate_gemini_image"))

    def test_records_gradient_sources_when_pixabay_fails(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(self.image_gen, "_fetch_pixabay", return_value=(None, "")),
                patch.object(self.image_gen, "_gradient_fallback") as gradient,
            ):
                paths, urls, sources = self.image_gen.generate_slide_images({}, output_dir)

        self.assertEqual(len(paths), 10)
        self.assertEqual(urls, set())
        self.assertEqual(sources, ["gradient"] * 10)
        self.assertEqual(gradient.call_count, 10)

    def test_uses_writer_image_query_and_category(self):
        carousel = {
            "cover_image_query": "hacker laptop dark",
            "cover_image_category": "computer",
            "slides": [{"image_query": "bitcoin coins", "image_category": "business"}],
        }
        with tempfile.TemporaryDirectory() as output_dir:
            with (
                patch.object(self.image_gen, "_fetch_pixabay", return_value=(None, "")) as fetch,
                patch.object(self.image_gen, "_gradient_fallback"),
            ):
                self.image_gen.generate_slide_images(carousel, output_dir)
        first, second = fetch.call_args_list[0], fetch.call_args_list[1]
        self.assertEqual(first.args[0], "hacker laptop dark")
        self.assertEqual(first.kwargs["category"], "computer")
        self.assertEqual(second.args[0], "bitcoin coins")
        self.assertEqual(second.kwargs["category"], "business")



class ImagesFromSpecTests(unittest.TestCase):
    def setUp(self):
        import image_gen
        self.image_gen = importlib.reload(image_gen)

    def test_mixes_pixabay_url_and_gradient_entries(self):
        import io
        from unittest.mock import Mock
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (400, 200), (250, 250, 240)).save(buf, "PNG")
        resp = Mock(content=buf.getvalue())
        resp.raise_for_status = Mock()
        jpg = io.BytesIO()
        Image.new("RGB", (800, 1000), (10, 20, 30)).save(jpg, "JPEG")
        with tempfile.TemporaryDirectory() as out:
            with (
                patch.object(self.image_gen, "_fetch_pixabay", return_value=(jpg.getvalue(), "https://pixabay.com/p/1")) as pix,
                patch.object(self.image_gen.requests, "get", return_value=resp),
            ):
                paths, urls, sources = self.image_gen.images_from_spec(
                    [{"query": "robot arm", "category": "industry"},
                     {"url": "https://example.com/logo.png", "fit": True},
                     {"gradient": True}],
                    out,
                )
                size = Image.open(paths[1]).size
        self.assertEqual(len(paths), 10)
        self.assertEqual(sources[:3], ["pixabay", "url", "gradient"])
        self.assertEqual(sources[3:], ["gradient"] * 7)
        self.assertEqual(urls, {"https://pixabay.com/p/1"})
        self.assertEqual(pix.call_args.kwargs["category"], "industry")
        self.assertEqual(size, (1080, 1350))


if __name__ == "__main__":
    unittest.main()
