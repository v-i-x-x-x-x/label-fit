# SPDX-License-Identifier: AGPL-3.0-only
"""Local, vector-preserving conversion of PDF/image crops to 4 x 6 PDFs."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageOps

LABEL_WIDTH = 4 * 72
LABEL_HEIGHT = 6 * 72
DEFAULT_MARGIN = 4.5  # 1/16 inch: a little breathing room for thermal printers.


class LabelSource:
    def __init__(self, document: fitz.Document, name: str):
        self.document = document
        self.name = name
        # Normalize the in-memory copy so preview and crop share coordinates.
        for page in document:
            page.remove_rotation()
        # Labels occasionally include annotations or filled form fields.
        document.bake(annots=True, widgets=True)

    @classmethod
    def from_file(cls, filename: str | Path, password: str | None = None):
        filename = Path(filename)
        if filename.suffix.lower() == ".pdf":
            doc = fitz.open(stream=filename.read_bytes(), filetype="pdf")
            if doc.needs_pass and not doc.authenticate(password or ""):
                doc.close()
                raise PermissionError("This PDF needs a password.")
            if not len(doc):
                doc.close()
                raise ValueError("This PDF has no pages.")
            try:
                return cls(doc, filename.name)
            except Exception:
                doc.close()
                raise
        with Image.open(filename) as image:
            return cls.from_image(ImageOps.exif_transpose(image), filename.name)

    @classmethod
    def from_image(cls, image: Image.Image, name="Pasted label"):
        image = ImageOps.exif_transpose(image).convert("RGBA")
        flattened = Image.new("RGB", image.size, "white")
        flattened.paste(image, mask=image.getchannel("A"))
        buf = io.BytesIO()
        flattened.save(buf, format="PNG")
        doc = fitz.open()
        page = doc.new_page(width=flattened.width, height=flattened.height)
        page.insert_image(page.rect, stream=buf.getvalue())
        return cls(doc, name)

    def close(self):
        self.document.close()

    def page_rect(self, page_number: int) -> fitz.Rect:
        return self.document[page_number].rect

    def render(self, page_number: int, max_side: int = 1500) -> Image.Image:
        page = self.document[page_number]
        scale = min(max_side / max(page.rect.width, page.rect.height), 2)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def suggest_crop(self, page_number: int) -> fitz.Rect:
        page = self.document[page_number]
        image = self.render(page_number, 850)
        box = suggest_image_crop(image)
        sx, sy = page.rect.width / image.width, page.rect.height / image.height
        return fitz.Rect(box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)

    def make_label(self, page_number: int, crop, clockwise=0,
                   auto_rotate=True, margin=DEFAULT_MARGIN) -> fitz.Document:
        page = self.document[page_number]
        crop = fitz.Rect(crop) & page.rect
        if crop.is_empty or crop.width < 4 or crop.height < 4:
            raise ValueError("Select a larger area around the entire label.")
        if not 0 <= margin < LABEL_WIDTH / 2:
            raise ValueError("The print margin is out of range.")
        if clockwise % 90:
            raise ValueError("Rotation must be a multiple of 90 degrees.")
        angle = ((90 if auto_rotate and crop.width > crop.height else 0)
                 + clockwise) % 360
        output = fitz.open()
        target = output.new_page(width=LABEL_WIDTH, height=LABEL_HEIGHT)
        printable = target.rect + (margin, margin, -margin, -margin)
        try:
            target.show_pdf_page(printable, self.document, page_number,
                                 clip=crop, rotate=-angle, keep_proportion=True)
            output.set_metadata({"title": "4 x 6 shipping label",
                                 "creator": "Label Fit",
                                 "producer": f"PyMuPDF {fitz.VersionBind} / MuPDF {fitz.VersionFitz}"})
            return output
        except Exception:
            output.close()
            raise


def suggest_image_crop(image: Image.Image) -> tuple[int, int, int, int]:
    """Suggest a content block separated by whitespace. User checks the preview.

    Wide blank gaps split return instructions from labels. Busy horizontal rows
    help favor barcodes over paragraphs. This is deliberately a suggestion;
    no carrier-specific rules or automatic printing are involved.
    """
    gray = ImageOps.grayscale(image)
    mask = gray.point(lambda p: 255 if p < 195 else 0)
    bounds = mask.getbbox()
    if bounds is None:
        return (0, 0, image.width, image.height)

    def trim(box):
        found = mask.crop(box).getbbox()
        if found is None:
            return None
        return (box[0] + found[0], box[1] + found[1],
                box[0] + found[2], box[1] + found[3])

    def partition(box, depth=0):
        if depth == 4:
            return [box]
        cropped = mask.crop(box)
        w, h = cropped.size
        data = cropped.tobytes()
        options = []
        # Find internal whitespace, considering both orientations.
        for axis, length in ((0, h), (1, w)):
            occupied = []
            for i in range(length):
                line = data[i * w:(i + 1) * w] if axis == 0 else data[i::w]
                occupied.append(any(line))
            start = None
            for i in range(length + 1):
                empty = i < length and not occupied[i]
                if empty and start is None:
                    start = i
                elif not empty and start is not None:
                    gap = i - start
                    if (gap >= max(22, max(image.size) * .055)
                            and start > 2 and i < length - 2):
                        options.append((gap / length, axis, start, i))
                    start = None
        if not options:
            return [box]
        _, axis, start, end = max(options)
        x0, y0, x1, y1 = box
        pieces = ((x0, y0, x1, y0 + start), (x0, y0 + end, x1, y1)) if axis == 0 else (
            (x0, y0, x0 + start, y1), (x0 + end, y0, x1, y1))
        result = []
        for piece in pieces:
            tight = trim(piece)
            if tight:
                result.extend(partition(tight, depth + 1))
        return result

    candidates = [bounds] + partition(bounds)

    def score(box):
        w, h = box[2] - box[0], box[3] - box[1]
        if min(w, h) < 35:
            return 0
        block = mask.crop(box)
        data = block.tobytes()
        busy_rows = 0
        for y in range(0, h, 3):
            row = data[y * w:(y + 1) * w]
            transitions = sum(a != b for a, b in zip(row, row[1:]))
            busy_rows += transitions > 36
        # Favor coherent label proportions and barcode-like content.
        ratio = max(w, h) / min(w, h)
        shape = min(ratio / 1.5, 1.5 / ratio) ** 3
        barcode = 1 + min(busy_rows / max(h / 3, 1), .5) * 6
        return w * h * shape * barcode

    # If a distinct block exists, avoid scoring the whole page of instructions.
    parts = partition(bounds)
    substantial = [b for b in parts if min(b[2] - b[0], b[3] - b[1]) >= 80]
    best = max(substantial or candidates, key=score)
    pad = max(8, round(min(image.size) * .015))
    return (max(0, best[0] - pad), max(0, best[1] - pad),
            min(image.width, best[2] + pad), min(image.height, best[3] + pad))
