from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from riegel_logo_detector import detect_logo
from riegel_logo_remover import remove_detected_logo


FIXTURES = Path(__file__).parent / 'fixtures'


class RiegelLogoDetectorTests(unittest.TestCase):
    def test_faint_watermark_is_located(self):
        result = detect_logo(FIXTURES / 'riegel-faint-15863.png')
        self.assertTrue(result['match'], result['message'])
        x, y, width, height = result['bbox']
        self.assertTrue(37 <= x + width / 2 <= 189)
        self.assertTrue(273 <= y + height / 2 <= 361)

    def test_faint_watermark_survives_resize_and_jpeg(self):
        with Image.open(FIXTURES / 'riegel-faint-15863.png') as image:
            resized = image.convert('RGB').resize(
                (image.width * 2, image.height * 2), Image.Resampling.BICUBIC
            )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'resized.jpg'
            resized.save(path, quality=72)
            result = detect_logo(path)
        self.assertTrue(result['match'], result['message'])
        x, y, width, height = result['bbox']
        self.assertTrue(74 <= x + width / 2 <= 378)
        self.assertTrue(546 <= y + height / 2 <= 722)

    def test_additional_faint_watermarks_are_located(self):
        cases = (
            ('riegel-faint-25380.png', (26, 248, 242, 383)),
            ('riegel-overlap-26004.png', (53, 259, 341, 387)),
        )
        for name, (left, top, right, bottom) in cases:
            with self.subTest(name=name):
                result = detect_logo(FIXTURES / name)
                self.assertTrue(result['match'], result['message'])
                x, y, width, height = result['bbox']
                self.assertTrue(left <= x + width / 2 <= right)
                self.assertTrue(top <= y + height / 2 <= bottom)

    def test_remove_creates_png_copy_only_inside_logo_box(self):
        path = FIXTURES / 'riegel-faint-15863.png'
        original_bytes = path.read_bytes()
        class FakeModel:
            def setInput(self, *_args):
                pass

            def forward(self):
                return np.full((1, 3, 256, 256), 128, dtype=np.float32)

        with patch('riegel_logo_remover._get_model', return_value=FakeModel()):
            data, detection = remove_detected_logo(path)
        self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(path.read_bytes(), original_bytes)
        with Image.open(path) as original, Image.open(BytesIO(data)) as cleaned:
            self.assertEqual(cleaned.size, original.size)
            changed = ImageChops.difference(original.convert('RGB'), cleaned.convert('RGB')).getbbox()
        self.assertIsNotNone(changed)
        x, y, width, height = detection['bbox']
        self.assertLess(changed[0], x + width)
        self.assertGreater(changed[2], x)
        self.assertLess(changed[1], y + height)
        self.assertGreater(changed[3], y)
        self.assertLess(changed[3], 500)

    def test_remove_rejects_unmarked_photo(self):
        with self.assertRaises(ValueError):
            remove_detected_logo(FIXTURES / 'no-riegel-12000.jpg')

    def test_unmarked_bottles_are_not_flagged(self):
        for name in ('no-riegel-12000.jpg', 'no-riegel-22840.jpg'):
            with self.subTest(name=name):
                result = detect_logo(FIXTURES / name)
                self.assertTrue(result['checked'], result['message'])
                self.assertFalse(result['match'], result['message'])


if __name__ == '__main__':
    unittest.main()