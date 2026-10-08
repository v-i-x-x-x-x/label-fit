# Label Fit

A small Windows app for turning a return shipping label on a full sheet into a
4 x 6 inch PDF. Open the PDF directly, draw a crop if needed, then print.
No screenshot, Word document, account, or file upload is needed.

**Platform:** Windows 10 or 11, with a label printer installed in Windows. The app
uses whichever printer you select; it is not tied to a particular printer brand,
computer, username, or local folder.

## Start

After cloning or downloading the source, double-click **Start Label Fit.bat** to
run the Python version. If you have a packaged build, the same launcher opens
**dist/Label Fit.exe**, or you can open the executable directly.
The packaged Windows executable needs no Python installation or internet access.
You can copy it to another folder and run it there.

If the executable is absent, the launcher runs the Python source instead. That
requires Python 3.10 or newer with Tkinter, added to PATH. It installs PyMuPDF and
Pillow if needed; that first setup needs an internet connection. Conversion runs
entirely locally.

You can also run `python label_fit.py` or `python label_fit.py "return-label.pdf"`.

## Convert and print

1. Choose **Open PDF or image** (Ctrl+O), or **Paste screenshot** (Ctrl+V).
2. Check the suggested crop. Drag a rectangle on the original sheet to replace it.
   Include the entire label, all barcodes, and their surrounding white space.
   **Find label** suggests a crop again; **Full page** selects the whole sheet.
3. Check the 4 x 6 preview. Wide selections rotate automatically. **Rotate 90
   degrees** (Ctrl+R) turns the result clockwise if it is upside down or sideways.
4. Choose **Print label** (Ctrl+P). The native Windows print dialog opens inside
   the app. Select your label printer, choose the number of copies, and click
   **Print**. The app requests **4 x 6 inch portrait** paper for that job and fits
   the full label inside the printer's printable area. It remembers the printer
   selection while the app is open. Cancel does not send a print job.
   If your driver rejects the custom size, select **4 x 6** or **100 x 150 mm** in
   Printer Properties and try again. Printer-wide defaults are never changed.

**Open PDF to print** remains available if you prefer your PDF viewer. In its
print dialog, choose 4 x 6 paper, Actual size / 100%, and portrait orientation.

**Save 4 x 6 PDF** (Ctrl+S) saves a reusable copy. A multi-page input lets you pick
the page; each export contains the currently selected page's crop only.

## How it handles labels

- Output pages are exactly 288 x 432 PDF points (4 x 6 inches).
- PDF text and barcodes stay as original PDF content; preview rendering does not
  reduce exported quality. Scanned PDFs and image inputs retain their original
  image quality, so a sharp original is best.
- Direct printing renders the converted PDF at the selected printer's resolution
  (including 203 dpi thermal printers), rather than printing the screen preview.
  Saved PDFs retain their vector content.
- The crop fits proportionally, with no stretching or intentional clipping.
- A removable 1/16-inch print margin is enabled by default.
- Crop detection is a whitespace/content heuristic, not carrier recognition.
  Unusual layouts, multiple labels, and labels mixed with instructions may need
  a manual crop. Always check the preview before printing.
- PDF page rotation, image EXIF orientation, and transparent images are handled.
  Password-protected PDFs prompt for a password.
- Opening for print creates a local PDF in `%TEMP%\LabelFit`. Those files contain
  the label and remain until you remove them or Windows clears temporary files.

## Development

Install dependencies with `python -m pip install -r requirements.txt`.
Run conversion checks with `python -m unittest discover -s tests -v`.
For the optional native print test, run
`$env:LABEL_FIT_PRINT_TESTS = '1'` first in PowerShell. It uses Microsoft Print to
PDF, never a physical printer.

The UI is `label_fit.py`; the independent conversion engine is `label_engine.py`.
Native dialog and printing code lives in `windows_print.py`. It uses Windows APIs
and Pillow already bundled with the app; no additional installation is required.
PyMuPDF's vector page placement is documented at
[Page.show_pdf_page](https://pymupdf.readthedocs.io/en/latest/page.html#Page.show_pdf_page).

To rebuild the Windows executable, install PyInstaller and run:

```powershell
python -m PyInstaller --noconfirm --onefile --windowed --name "Label Fit" label_fit.py
```

## License and sharing

Label Fit is licensed under **GNU AGPL version 3 only**. See [LICENSE](LICENSE)
and [third-party notices](THIRD_PARTY_NOTICES.md). PyMuPDF/MuPDF uses the AGPL open
source license; a commercial license is also available from Artifex. Pillow uses
the MIT-CMU license.
