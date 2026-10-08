# SPDX-License-Identifier: AGPL-3.0-only
"""Label Fit: a small local Windows shipping-label converter."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf as fitz
from PIL import Image, ImageGrab, ImageTk

from label_engine import DEFAULT_MARGIN, LabelSource
from windows_print import WindowsPrinter

BG = "#f3f5f7"
INK = "#182638"
MUTED = "#586879"
BLUE = "#2563eb"


class LabelFit(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Label Fit - shipping labels made printable")
        self.geometry("1120x850")
        self.minsize(840, 640)
        self.configure(background=BG)
        self.source = None
        self.page_number = 0
        self.crop = None
        self.clockwise = 0
        self.source_image = None
        self.output_image = None
        self.source_photo = None
        self.output_photo = None
        self.source_display = None
        self.drag_start = None
        self.resize_job = None
        self.crop_job = None
        self.auto_rotate = tk.BooleanVar(value=True)
        self.add_margin = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Open a return-label PDF, an image, or paste a screenshot.")
        self.file_text = tk.StringVar(value="No label loaded")
        self.page_text = tk.StringVar(value="Page - of -")
        self.rotation_text = tk.StringVar(value="Rotation: auto")
        self.output_note = tk.StringVar(value="Your label will appear here")
        self.actions = []
        self.printer = None
        self._build_ui()
        self.bind("<Control-o>", lambda _: self.open_file())
        self.bind("<Control-v>", lambda _: self.paste_image())
        self.bind("<Control-s>", lambda _: self.save_pdf())
        self.bind("<Control-r>", lambda _: self.rotate())
        self.bind("<Control-p>", lambda _: self.print_label())
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 24, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Primary.TButton", foreground="white", background=BLUE)
        style.map("Primary.TButton", background=[("active", "#1d4ed8"),
                                                  ("disabled", "#aab9d1")])
        style.configure("TCheckbutton", background=BG, foreground=INK,
                        font=("Segoe UI", 10))
        shell = ttk.Frame(self, padding=24)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(4, weight=1)
        ttk.Label(shell, text="Label Fit", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(shell, text="From a full sheet to a 4 x 6 label. All on your computer.",
                  style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 16))
        toolbar = ttk.Frame(shell)
        toolbar.grid(row=2, column=0, sticky="ew")
        ttk.Button(toolbar, text="Open PDF or image...", style="Primary.TButton",
                   command=self.open_file).pack(side="left")
        ttk.Button(toolbar, text="Paste screenshot", command=self.paste_image).pack(
            side="left", padx=(8, 0))
        self.file_label = ttk.Label(shell, textvariable=self.file_text, style="Muted.TLabel", wraplength=760)
        self.file_label.grid(row=3, column=0, sticky="w", pady=(10, 14))

        panels = ttk.Frame(shell)
        panels.grid(row=4, column=0, sticky="nsew")
        panels.columnconfigure(0, weight=3, uniform="panels")
        panels.columnconfigure(1, weight=2, uniform="panels")
        panels.rowconfigure(2, weight=1)
        ttk.Label(panels, text="1. Select the label", style="Section.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(panels, text="2. Check your 4 x 6", style="Section.TLabel").grid(
            row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Label(panels, text="Drag on the sheet to draw or replace the crop.",
                  style="Muted.TLabel", wraplength=330).grid(row=1, column=0, sticky="w", pady=(4, 10))
        ttk.Label(panels, text="Everything inside the crop fits without stretching.",
                  style="Muted.TLabel", wraplength=310).grid(row=1, column=1, sticky="w",
                                            padx=(18, 0), pady=(4, 10))
        self.source_canvas = tk.Canvas(panels, background="#e1e6ec", highlightthickness=0,
                                       cursor="crosshair", width=500, height=440)
        self.source_canvas.grid(row=2, column=0, sticky="nsew")
        self.output_canvas = tk.Canvas(panels, background="#e1e6ec", highlightthickness=0,
                                       width=360, height=440)
        self.output_canvas.grid(row=2, column=1, sticky="nsew", padx=(18, 0))
        self.source_canvas.bind("<ButtonPress-1>", self.start_crop)
        self.source_canvas.bind("<B1-Motion>", self.drag_crop)
        self.source_canvas.bind("<ButtonRelease-1>", self.end_crop)
        self.source_canvas.bind("<Configure>", self.queue_redraw)
        self.output_canvas.bind("<Configure>", self.queue_redraw)

        source_tools = ttk.Frame(panels)
        source_tools.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.previous_button = ttk.Button(source_tools, text="<", command=lambda: self.change_page(-1))
        self.previous_button.configure(width=3)
        self.previous_button.pack(side="left")
        ttk.Label(source_tools, textvariable=self.page_text).pack(side="left", padx=8)
        self.next_button = ttk.Button(source_tools, text=">", command=lambda: self.change_page(1))
        self.next_button.configure(width=3)
        self.next_button.pack(side="left")
        self._action(source_tools, "Find label", self.find_label).pack(side="right")
        self._action(source_tools, "Full page", self.full_page).pack(side="right", padx=6)
        output_tools = ttk.Frame(panels)
        output_tools.grid(row=3, column=1, sticky="ew", padx=(18, 0), pady=(10, 0))
        self._action(output_tools, "Rotate 90 degrees", self.rotate).pack(side="left")
        ttk.Label(output_tools, textvariable=self.rotation_text,
                  style="Muted.TLabel").pack(side="left", padx=8)

        settings = ttk.Frame(shell)
        settings.grid(row=5, column=0, sticky="ew", pady=(14, 8))
        ttk.Checkbutton(settings, text="Auto-rotate wide labels", variable=self.auto_rotate,
                        command=self.settings_changed).pack(side="left")
        ttk.Checkbutton(settings, text="Small printer margin (1/16 inch)", variable=self.add_margin,
                        command=self.settings_changed).pack(side="left", padx=20)
        ttk.Label(shell, textvariable=self.output_note, style="Muted.TLabel").grid(row=6, column=0, sticky="w")
        footer = ttk.Frame(shell)
        footer.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        self._action(footer, "Print label...", self.print_label,
                     "Primary.TButton").pack(side="left")
        self._action(footer, "Save 4 x 6 PDF...", self.save_pdf).pack(side="left", padx=(8, 0))
        self._action(footer, "Open PDF to print", self.open_for_print).pack(side="left", padx=8)
        self.print_note_label = ttk.Label(shell, text="Print label opens the Windows print dialog. "
                  "Choose your label printer; the app requests 4 x 6 portrait paper.", style="Muted.TLabel",
                  wraplength=760)
        self.print_note_label.grid(row=8, column=0, sticky="w", pady=(10, 0))
        self.status_label = ttk.Label(shell, textvariable=self.status, wraplength=760)
        self.status_label.grid(row=9, column=0, sticky="w", pady=(8, 0))
        shell.bind("<Configure>", self.wrap_footer)
        self.update_controls()

    def wrap_footer(self, event):
        width = max(200, event.width - 48)
        for label in (self.file_label, self.print_note_label, self.status_label):
            label.configure(wraplength=width)

    def _action(self, parent, text, command, style="TButton"):
        button = ttk.Button(parent, text=text, command=command, style=style)
        self.actions.append(button)
        return button

    def update_controls(self):
        for button in self.actions:
            button.configure(state="normal" if self.source else "disabled")
        self.previous_button.configure(state="normal" if self.source and self.page_number > 0 else "disabled")
        self.next_button.configure(state="normal" if self.source and self.page_number < len(self.source.document) - 1 else "disabled")
        if self.source:
            self.page_text.set(f"Page {self.page_number + 1} of {len(self.source.document)}")

    def open_file(self):
        filename = filedialog.askopenfilename(title="Choose your shipping label",
            filetypes=[("PDFs and images", "*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
                       ("PDF documents", "*.pdf"), ("All files", "*.*")])
        if not filename:
            return
        try:
            try:
                source = LabelSource.from_file(filename)
            except PermissionError:
                password = simpledialog.askstring("Protected PDF", "PDF password:", show="*", parent=self)
                if password is None:
                    return
                source = LabelSource.from_file(filename, password)
            self.load_source(source)
        except Exception as exc:
            self.report_error("Could not open this file", exc)

    def paste_image(self):
        try:
            clipboard = ImageGrab.grabclipboard()
            if isinstance(clipboard, Image.Image):
                self.load_source(LabelSource.from_image(clipboard))
            elif isinstance(clipboard, list) and clipboard:
                self.load_source(LabelSource.from_file(clipboard[0]))
            else:
                messagebox.showinfo("No image on clipboard", "Copy an image or take a screenshot with "
                    "Win + Shift + S, then choose Paste screenshot.", parent=self)
        except Exception as exc:
            self.report_error("Could not paste the image", exc)

    def load_source(self, source):
        # Read the initial page before replacing a working document.
        try:
            image = source.render(0)
            crop = source.suggest_crop(0)
        except Exception:
            source.close()
            raise
        if self.source:
            self.source.close()
        self.source = source
        self.page_number = 0
        self.clockwise = 0
        self.crop = crop
        self.source_image = image
        self.file_text.set(source.name)
        self.update_controls()
        self.refresh_preview()
        self.status.set("Suggested crop ready. Check that the whole label and every barcode are included; "
                        "drag on the sheet to correct it.")

    def change_page(self, delta):
        if not self.source:
            return
        number = self.page_number + delta
        if not 0 <= number < len(self.source.document):
            return
        try:
            image = self.source.render(number)
            crop = self.source.suggest_crop(number)
            self.page_number = number
            self.source_image = image
            self.crop = crop
            self.clockwise = 0
            self.update_controls()
            self.refresh_preview()
            self.status.set("Check the suggested crop for this page before saving.")
        except Exception as exc:
            self.report_error("Could not read this page", exc)

    def find_label(self):
        if self.source:
            try:
                self.crop = self.source.suggest_crop(self.page_number)
                self.clockwise = 0
                self.refresh_preview()
                self.status.set("Suggested crop ready. Drag to adjust if it includes instructions or misses part of the label.")
            except Exception as exc:
                self.report_error("Could not suggest a crop", exc)

    def full_page(self):
        if self.source:
            self.crop = self.source.page_rect(self.page_number)
            self.clockwise = 0
            self.refresh_preview()
            self.status.set("Full page selected. Drag a rectangle around the label to remove instructions.")

    def rotate(self):
        if self.source:
            self.clockwise = (self.clockwise + 90) % 360
            self.refresh_preview()

    def settings_changed(self):
        if self.source:
            self.refresh_preview()

    def build_output(self):
        return self.source.make_label(self.page_number, self.crop, self.clockwise,
            self.auto_rotate.get(), DEFAULT_MARGIN if self.add_margin.get() else 0)

    def refresh_preview(self):
        if self.crop_job:
            self.after_cancel(self.crop_job)
            self.crop_job = None
        if not self.source:
            return
        try:
            with self.build_output() as doc:
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                self.output_image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            base = 90 if self.auto_rotate.get() and self.crop.width > self.crop.height else 0
            self.rotation_text.set(f"Rotation: {(base + self.clockwise) % 360} degrees")
            self.output_note.set("4 x 6 inches  |  Original proportions  |  " +
                ("PDF content preserved" if self.source.name.lower().endswith(".pdf") else "Original image resolution"))
        except Exception as exc:
            self.output_image = None
            self.output_note.set("Select an area containing the label.")
            self.status.set(f"Preview unavailable: {exc}")
        self.draw_canvases()

    def queue_redraw(self, _event=None):
        if self.resize_job:
            self.after_cancel(self.resize_job)
        self.resize_job = self.after(80, self.draw_canvases)

    @staticmethod
    def fit_image(canvas, image):
        w, h = max(1, canvas.winfo_width() - 32), max(1, canvas.winfo_height() - 32)
        scale = min(w / image.width, h / image.height)
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.LANCZOS))
        x, y = (canvas.winfo_width() - size[0]) / 2, (canvas.winfo_height() - size[1]) / 2
        canvas.create_rectangle(x + 3, y + 3, x + size[0] + 3, y + size[1] + 3,
                                fill="#c1c9d3", outline="")
        canvas.create_image(x, y, image=photo, anchor="nw")
        return photo, (x, y, size[0], size[1])

    def draw_canvases(self):
        self.resize_job = None
        for canvas in (self.source_canvas, self.output_canvas):
            canvas.delete("all")
        if self.source_image:
            self.source_photo, self.source_display = self.fit_image(self.source_canvas, self.source_image)
            self.draw_selection()
        else:
            self.source_canvas.create_text(self.source_canvas.winfo_width() / 2,
                self.source_canvas.winfo_height() / 2, text="Open a PDF or image to start\n\nCtrl + O  /  Ctrl + V",
                fill=MUTED, font=("Segoe UI", 13), justify="center")
        if self.output_image:
            self.output_photo, _ = self.fit_image(self.output_canvas, self.output_image)
        else:
            self.output_canvas.create_text(self.output_canvas.winfo_width() / 2,
                self.output_canvas.winfo_height() / 2, text="4 x 6 print preview", fill=MUTED,
                font=("Segoe UI", 13))

    def draw_selection(self):
        self.source_canvas.delete("selection")
        if self.crop is None or self.source_display is None:
            return
        x, y, w, h = self.source_display
        rect = self.source.page_rect(self.page_number)
        x0, y0 = x + self.crop.x0 / rect.width * w, y + self.crop.y0 / rect.height * h
        x1, y1 = x + self.crop.x1 / rect.width * w, y + self.crop.y1 / rect.height * h
        # Dim the discarded sheet; the selected label remains crisp.
        for box in ((x, y, x + w, y0), (x, y1, x + w, y + h),
                    (x, y0, x0, y1), (x1, y0, x + w, y1)):
            self.source_canvas.create_rectangle(*box, fill="#25364b", stipple="gray50",
                                                outline="", tags="selection")
        self.source_canvas.create_rectangle(x0, y0, x1, y1, outline=BLUE, width=2, tags="selection")
        for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            self.source_canvas.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3,
                fill="white", outline=BLUE, tags="selection")

    def event_point(self, event, clamp=False):
        if not self.source or not self.source_display:
            return None
        x, y, w, h = self.source_display
        if not clamp and not (x <= event.x <= x + w and y <= event.y <= y + h):
            return None
        rect = self.source.page_rect(self.page_number)
        return (min(max((event.x - x) / w, 0), 1) * rect.width,
                min(max((event.y - y) / h, 0), 1) * rect.height)

    def start_crop(self, event):
        self.drag_start = self.event_point(event)
        self.previous_crop = self.crop

    def drag_crop(self, event):
        if self.drag_start is None:
            return
        point = self.event_point(event, True)
        x, y = self.drag_start
        self.crop = fitz.Rect(min(x, point[0]), min(y, point[1]), max(x, point[0]), max(y, point[1]))
        self.draw_selection()
        if self.crop_job:
            self.after_cancel(self.crop_job)
        if self.crop.width >= 4 and self.crop.height >= 4:
            self.crop_job = self.after(120, self.refresh_preview)

    def end_crop(self, event):
        if self.drag_start is None:
            return
        self.drag_crop(event)
        if self.crop.width < 4 or self.crop.height < 4:
            self.crop = self.previous_crop
        else:
            self.status.set("Crop updated. Check that the entire barcode and its white border are visible.")
        self.drag_start = None
        self.refresh_preview()

    def save_pdf(self):
        if not self.source:
            return
        stem = Path(self.source.name).stem
        filename = filedialog.asksaveasfilename(title="Save your 4 x 6 label",
            initialfile=f"{stem}-4x6.pdf", defaultextension=".pdf", filetypes=[("PDF document", "*.pdf")])
        if not filename:
            return
        try:
            with self.build_output() as doc:
                self.atomic_save(doc, Path(filename))
            self.status.set(f"Saved {Path(filename).name}. Print on 4 x 6 paper at Actual size / 100%.")
        except Exception as exc:
            self.report_error("Could not save the label", exc)

    @staticmethod
    def atomic_save(doc, destination):
        # Save beside the destination, then replace only after the PDF is complete.
        handle, scratch = tempfile.mkstemp(suffix=".pdf", dir=destination.parent)
        os.close(handle)
        try:
            doc.save(scratch, garbage=4, deflate=True)
            os.replace(scratch, destination)
        finally:
            Path(scratch).unlink(missing_ok=True)

    def open_for_print(self):
        if not self.source:
            return
        try:
            output_dir = Path(tempfile.gettempdir()) / "LabelFit"
            output_dir.mkdir(exist_ok=True)
            handle, filename = tempfile.mkstemp(prefix="label-", suffix="-4x6.pdf", dir=output_dir)
            os.close(handle)
            with self.build_output() as doc:
                doc.save(filename, garbage=4, deflate=True)
            os.startfile(filename)
            self.status.set("Opened in your PDF viewer. Press Ctrl + P, choose your label printer, "
                            "4 x 6 paper and Actual size / 100%.")
        except Exception as exc:
            self.report_error("Could not open the print PDF", exc)

    def print_label(self):
        if not self.source:
            return
        try:
            with self.build_output() as doc:
                data = doc.tobytes(garbage=4, deflate=True)
            if self.printer is None:
                self.printer = WindowsPrinter()
            if not self.printer.choose(self.printer.owner_handle(self)):
                self.status.set("Printing canceled. Your label is ready when you are.")
                return
            self.status.set("Sending the label to the printer...")
            self.update_idletasks()
            name = self.printer.submit_pdf(data)
            self.status.set(f"Label sent to {name}. Check the printer queue if it does not print.")
        except Exception as exc:
            if self.printer:
                self.printer.release_dc()
            self.report_error("Could not print the label", exc)

    def report_error(self, title, exc):
        logging.exception(title)
        messagebox.showerror(title, str(exc), parent=self)

    def close(self):
        if self.printer:
            self.printer.close()
        if self.source:
            self.source.close()
        self.destroy()


def main():
    logging.basicConfig(level=logging.ERROR)
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
    app = LabelFit()
    if len(sys.argv) > 1:
        def load_argument():
            try:
                app.load_source(LabelSource.from_file(sys.argv[1]))
            except Exception as exc:
                app.report_error("Could not open this file", exc)
        app.after(150, load_argument)
    app.mainloop()


if __name__ == "__main__":
    main()
