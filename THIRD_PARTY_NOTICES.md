# Third-party notices

Label Fit is distributed under the GNU Affero General Public License version 3
only (AGPL-3.0-only). See LICENSE for the full terms.

## PyMuPDF and MuPDF

- Copyright Artifex Software, Inc. and contributors.
- Open-source license: GNU AGPL version 3. A separate commercial license is
  available from Artifex.
- PyMuPDF source: https://github.com/pymupdf/PyMuPDF
- MuPDF source and bundled dependency notices: https://github.com/ArtifexSoftware/mupdf
- Licensing: https://pymupdf.io/licensing

The full AGPL text is provided in LICENSE. Label Fit preserves the PDF engine's
producer attribution in generated PDFs. It does not modify PyMuPDF or MuPDF.

## Pillow

- Copyright the Pillow contributors and Secret Labs AB / Fredrik Lundh.
- License: MIT-CMU, including the Python Imaging Library permission notice.
- Source: https://github.com/python-pillow/Pillow
- Full license text: LICENSES/Pillow.txt

## Python, Tcl/Tk, and packaging

Running from source uses the recipient's installed Python and Tcl/Tk. A packaged
Windows executable also includes parts of that runtime and image-library native
dependencies. Their applicable licenses and notices must accompany a binary
release, along with these notices and the corresponding source required by each
license. PyInstaller's bootloader includes an exception allowing redistribution
of bundled applications under their own licenses.

- Python licensing: https://docs.python.org/3/license.html
- Tcl/Tk licensing: https://www.tcl-lang.org/software/tcltk/license.html
- PyInstaller licensing: https://pyinstaller.org/en/stable/license.html

The source repository does not include compiled binaries. When publishing a
binary release, use the same source revision and record the exact dependency
versions used to build it. Provide corresponding dependency source, licenses,
and build instructions alongside the application source, as required by their
licenses; this file does not replace those requirements.
