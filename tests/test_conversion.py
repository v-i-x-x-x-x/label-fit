# SPDX-License-Identifier: AGPL-3.0-only
import io
from pathlib import Path
import tempfile
import unittest

import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat

from label_engine import LabelSource, suggest_image_crop


def sample_pdf(rotation=0):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 45), "RETURN INSTRUCTIONS - not part of label", fontsize=12)
    page.draw_rect((72, 190, 504, 478), color=(0, 0, 0), width=2)
    page.insert_text((88, 222), "SAMPLE ONLY - DO NOT SHIP", fontsize=20)
    page.insert_text((88, 265), "RETURN SHIPPING LABEL", fontsize=16)
    page.insert_text((88, 299), "123 Example Street", fontsize=12)
    page.insert_text((88, 320), "Example City, NY 10001", fontsize=12)
    for i in range(72):
        x = 95 + i * 5
        page.draw_rect((x, 360, x + (1 if i % 3 else 3), 432),
                       color=None, fill=(0, 0, 0))
    page.insert_text((95, 458), "TEST BARCODE / 0000 0000 0000", fontsize=12)
    page.set_rotation(rotation)
    return doc


def rendered(doc, scale=1):
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.doc = sample_pdf()
        self.source = LabelSource(self.doc, "sample.pdf")

    def tearDown(self):
        self.source.close()

    def test_exact_size_and_vector_content(self):
        with self.source.make_label(0, (70, 188, 506, 480)) as out:
            saved = out.tobytes(garbage=4, deflate=True)
        with fitz.open(stream=saved, filetype="pdf") as reopened:
            self.assertEqual(tuple(reopened[0].rect), (0, 0, 288, 432))
            self.assertEqual(reopened[0].rotation, 0)
            self.assertIn("RETURN SHIPPING LABEL", reopened[0].get_text())
            self.assertEqual(reopened[0].get_images(), [])
            self.assertIn("PyMuPDF", reopened.metadata["producer"])
            self.assertIn("MuPDF", reopened.metadata["producer"])

    def test_crop_excludes_instruction_visually(self):
        with self.source.make_label(0, (70, 188, 506, 480), auto_rotate=False, margin=0) as out:
            actual = rendered(out, 2)
        pix = self.doc[0].get_pixmap(clip=fitz.Rect(70, 188, 506, 480),
                                    matrix=fitz.Matrix(2, 2), alpha=False)
        crop = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        expected = Image.new("RGB", actual.size, "white")
        width = actual.width
        height = round(crop.height * width / crop.width)
        expected.paste(crop.resize((width, height)), (0, (actual.height - height) // 2))
        diff = ImageStat.Stat(ImageChops.difference(actual, expected))
        self.assertLess(sum(diff.mean) / 3, 8)

    def test_auto_rotation_equals_explicit_clockwise(self):
        with self.source.make_label(0, (70, 188, 506, 480), auto_rotate=True) as a:
            first = rendered(a)
        with self.source.make_label(0, (70, 188, 506, 480), clockwise=90, auto_rotate=False) as b:
            self.assertIsNone(ImageChops.difference(first, rendered(b)).getbbox())

    def test_rotation_cycles_and_direction(self):
        crop = (70, 188, 506, 480)
        with self.source.make_label(0, crop, clockwise=0, auto_rotate=False) as out:
            first = rendered(out)
        with self.source.make_label(0, crop, clockwise=360, auto_rotate=False) as out:
            self.assertIsNone(ImageChops.difference(first, rendered(out)).getbbox())
        with self.source.make_label(0, crop, clockwise=180, auto_rotate=False) as out:
            rotated = rendered(out)
        expected = first.transpose(Image.Transpose.ROTATE_180)
        self.assertLess(sum(ImageStat.Stat(ImageChops.difference(expected, rotated)).mean) / 3, 2)

    def test_suggestion_includes_label_and_excludes_instructions(self):
        crop = self.source.suggest_crop(0)
        self.assertLess(crop.x0, 72)
        self.assertLess(crop.y0, 190)
        self.assertGreater(crop.x1, 504)
        self.assertGreater(crop.y1, 478)
        self.assertGreater(crop.y0, 100)

    def test_rotated_input_preserves_display(self):
        original = sample_pdf(90)
        before = rendered(original)
        source = LabelSource(original, "rotated.pdf")
        try:
            after = source.render(0, 792)
            self.assertEqual(before.size, after.size)
            self.assertIsNone(ImageChops.difference(before, after).getbbox())
            with source.make_label(0, source.page_rect(0), auto_rotate=False, margin=0) as out:
                self.assertEqual(tuple(out[0].rect), (0, 0, 288, 432))
        finally:
            source.close()

    def test_cropped_offset_input(self):
        doc = sample_pdf()
        doc[0].set_cropbox(fitz.Rect(60, 150, 520, 500))
        source = LabelSource(doc, "cropped.pdf")
        try:
            full = source.page_rect(0)
            with source.make_label(0, full, auto_rotate=False, margin=0) as out:
                self.assertIn("SAMPLE ONLY", out[0].get_text())
                image = rendered(out)
                self.assertIsNotNone(ImageChops.invert(image).getbbox())
        finally:
            source.close()

    def test_current_page_only(self):
        page = self.doc.new_page(width=288, height=432)
        page.insert_text((20, 40), "SECOND LABEL")
        with self.source.make_label(1, page.rect) as out:
            self.assertEqual(len(out), 1)
            self.assertIn("SECOND LABEL", out[0].get_text())

    def test_images_and_transparency(self):
        image = Image.new("RGBA", (300, 450), (0, 0, 0, 0))
        image.paste((0, 0, 0, 255), (30, 30, 270, 70))
        source = LabelSource.from_image(image)
        try:
            self.assertEqual(source.render(0).getpixel((0, 0)), (255, 255, 255))
            with source.make_label(0, source.page_rect(0)) as out:
                self.assertEqual(len(out[0].get_images()), 1)
                self.assertEqual(tuple(out[0].rect), (0, 0, 288, 432))
        finally:
            source.close()

    def test_blank_image_suggestion(self):
        self.assertEqual(suggest_image_crop(Image.new("RGB", (600, 800), "white")), (0, 0, 600, 800))

    def test_bad_crops_and_options(self):
        for crop in ((0, 0, 0, 1), (900, 900, 1000, 1000), (0, 0, 2, 2)):
            with self.assertRaises(ValueError):
                self.source.make_label(0, crop)
        with self.assertRaises(ValueError):
            self.source.make_label(0, self.doc[0].rect, margin=150)
        with self.assertRaises(ValueError):
            self.source.make_label(0, self.doc[0].rect, clockwise=45)

    def test_pdf_password_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "protected.pdf"
            self.doc.save(filename, encryption=fitz.PDF_ENCRYPT_AES_256,
                          owner_pw="owner", user_pw="secret")
            original = filename.read_bytes()
            with self.assertRaises(PermissionError):
                LabelSource.from_file(filename)
            source = LabelSource.from_file(filename, "secret")
            try:
                with source.make_label(0, (70, 188, 506, 480)) as out:
                    self.assertEqual(out[0].rect.width, 288)
            finally:
                source.close()
            self.assertEqual(filename.read_bytes(), original)

    def test_annotation_included(self):
        doc = fitz.open()
        page = doc.new_page(width=288, height=432)
        page.insert_text((20, 40), "LABEL")
        page.add_freetext_annot((30, 60, 250, 110), "ANNOTATED ADDRESS", fontsize=14)
        before = rendered(doc)
        source = LabelSource(doc, "annotated.pdf")
        try:
            with source.make_label(0, page.rect, margin=0) as out:
                after = rendered(out)
            self.assertLess(sum(ImageStat.Stat(ImageChops.difference(before, after)).mean) / 3, 1)
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
