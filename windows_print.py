# SPDX-License-Identifier: AGPL-3.0-only
"""Native Windows print dialog and GDI output; no PDF viewer required.

Printer settings belong to this app's job, never the printer's global defaults.
The native dialog owns copies/collation. A single page is submitted once.
"""

from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import sys

import pymupdf as fitz
from PIL import Image, ImageWin


class PrintDialog(ct.Structure):
    # commdlg.h packs the 32-bit structure; the 64-bit structure uses alignment 8.
    _pack_ = 1 if ct.sizeof(ct.c_void_p) == 4 else 8
    _fields_ = [
        ("lStructSize", wt.DWORD), ("hwndOwner", wt.HWND),
        ("hDevMode", wt.HGLOBAL), ("hDevNames", wt.HGLOBAL), ("hDC", wt.HDC),
        ("Flags", wt.DWORD), ("nFromPage", wt.WORD), ("nToPage", wt.WORD),
        ("nMinPage", wt.WORD), ("nMaxPage", wt.WORD), ("nCopies", wt.WORD),
        ("hInstance", wt.HINSTANCE), ("lCustData", wt.LPARAM),
        ("lpfnPrintHook", ct.c_void_p), ("lpfnSetupHook", ct.c_void_p),
        ("lpPrintTemplateName", wt.LPCWSTR), ("lpSetupTemplateName", wt.LPCWSTR),
        ("hPrintTemplate", wt.HGLOBAL), ("hSetupTemplate", wt.HGLOBAL),
    ]


class DevNames(ct.Structure):
    _fields_ = [("driver", wt.WORD), ("device", wt.WORD),
                ("output", wt.WORD), ("default", wt.WORD)]


class DevMode(ct.Structure):
    _fields_ = [
        ("dmDeviceName", wt.WCHAR * 32), ("dmSpecVersion", wt.WORD),
        ("dmDriverVersion", wt.WORD), ("dmSize", wt.WORD),
        ("dmDriverExtra", wt.WORD), ("dmFields", wt.DWORD),
        ("dmOrientation", ct.c_short), ("dmPaperSize", ct.c_short),
        ("dmPaperLength", ct.c_short), ("dmPaperWidth", ct.c_short),
        ("dmScale", ct.c_short), ("dmCopies", ct.c_short),
        ("dmDefaultSource", ct.c_short), ("dmPrintQuality", ct.c_short),
        ("dmColor", ct.c_short), ("dmDuplex", ct.c_short),
        ("dmYResolution", ct.c_short), ("dmTTOption", ct.c_short),
        ("dmCollate", ct.c_short), ("dmFormName", wt.WCHAR * 32),
        ("dmLogPixels", wt.WORD), ("dmBitsPerPel", wt.DWORD),
        ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD),
        ("dmDisplayFlags", wt.DWORD), ("dmDisplayFrequency", wt.DWORD),
        ("dmICMMethod", wt.DWORD), ("dmICMIntent", wt.DWORD),
        ("dmMediaType", wt.DWORD), ("dmDitherType", wt.DWORD),
        ("dmReserved1", wt.DWORD), ("dmReserved2", wt.DWORD),
        ("dmPanningWidth", wt.DWORD), ("dmPanningHeight", wt.DWORD),
    ]


class DocInfo(ct.Structure):
    _fields_ = [("cbSize", ct.c_int), ("lpszDocName", wt.LPCWSTR),
                ("lpszOutput", wt.LPCWSTR), ("lpszDatatype", wt.LPCWSTR),
                ("fwType", wt.DWORD)]


@dataclass(frozen=True)
class PrintPlacement:
    x: int
    y: int
    width: int
    height: int


def label_placement(dpi_x, dpi_y, page_width, page_height, printable_width, printable_height):
    """Fit a 4x6 label inside the device's printable area without distortion."""
    if min(dpi_x, dpi_y, page_width, page_height, printable_width, printable_height) <= 0:
        raise ValueError("The printer reported an invalid paper size or resolution.")
    inches = (page_width / dpi_x, page_height / dpi_y)
    # Includes commonly named 100 x 150 mm labels (3.94 x 5.91 inches).
    if abs(inches[0] - 4) > .18 or abs(inches[1] - 6) > .18:
        raise ValueError(f"The printer is using {inches[0]:.2f} x {inches[1]:.2f} inch paper. "
                         "Choose 4 x 6 (or 100 x 150 mm), portrait, in Printer Properties and try again.")
    scale = min(1, printable_width / (4 * dpi_x), printable_height / (6 * dpi_y))
    width = min(printable_width, round(4 * dpi_x * scale))
    height = min(printable_height, round(6 * dpi_y * scale))
    return PrintPlacement((printable_width - width) // 2, (printable_height - height) // 2,
                          width, height)


class WindowsPrinter:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Direct printing requires Windows. Save a PDF to print on other systems.")
        self.dialog = PrintDialog()
        self.dialog.lStructSize = ct.sizeof(PrintDialog)
        self.dialog.Flags = (0x100 | 0x40000 | 0x4 | 0x8 | 0x100000 | 0x80000 | 0x1000)
        # RETURNDC, USEDEVMODECOPIESANDCOLLATE, NOSELECTION, NOPAGENUMS,
        # HIDEPRINTTOFILE, DISABLEPRINTTOFILE, ENABLEPRINTHOOK.
        self.dialog.nMinPage = self.dialog.nMaxPage = self.dialog.nCopies = 1
        self.gdi = ct.WinDLL("gdi32", use_last_error=True)
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.spool = ct.WinDLL("winspool.drv", use_last_error=True)
        self.common = ct.WinDLL("comdlg32", use_last_error=True)
        self.user = ct.WinDLL("user32", use_last_error=True)
        self._bind(self.common, "PrintDlgW", [ct.POINTER(PrintDialog)], wt.BOOL)
        self._bind(self.common, "CommDlgExtendedError", [], wt.DWORD)
        self._bind(self.kernel, "GlobalLock", [wt.HGLOBAL], ct.c_void_p)
        self._bind(self.kernel, "GlobalUnlock", [wt.HGLOBAL], wt.BOOL)
        self._bind(self.kernel, "GlobalFree", [wt.HGLOBAL], wt.HGLOBAL)
        self._bind(self.gdi, "DeleteDC", [wt.HDC], wt.BOOL)
        self._bind(self.gdi, "ResetDCW", [wt.HDC, ct.c_void_p], wt.HDC)
        self._bind(self.gdi, "GetDeviceCaps", [wt.HDC, ct.c_int], ct.c_int)
        self._bind(self.gdi, "StartDocW", [wt.HDC, ct.POINTER(DocInfo)], ct.c_int)
        for name in ("StartPage", "EndPage", "EndDoc", "AbortDoc"):
            self._bind(self.gdi, name, [wt.HDC], ct.c_int)
        self._bind(self.spool, "OpenPrinterW", [wt.LPWSTR, ct.POINTER(wt.HANDLE), ct.c_void_p], wt.BOOL)
        self._bind(self.spool, "ClosePrinter", [wt.HANDLE], wt.BOOL)
        self._bind(self.spool, "DocumentPropertiesW",
                   [wt.HWND, wt.HANDLE, wt.LPWSTR, ct.c_void_p, ct.c_void_p, wt.DWORD], ct.c_long)
        self._bind(self.user, "GetAncestor", [wt.HWND, wt.UINT], wt.HWND)
        self._bind(self.user, "SetWindowTextW", [wt.HWND, wt.LPCWSTR], wt.BOOL)
        self._bind(self.user, "GetDlgItem", [wt.HWND, ct.c_int], wt.HWND)
        # Customize the title with a documented print hook. This also keeps the
        # dialog inside the app on Windows 11 instead of using its external host.
        hook_type = ct.WINFUNCTYPE(ct.c_size_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        @hook_type
        def print_hook(hwnd, message, _wparam, _lparam):
            if message == 0x110:  # WM_INITDIALOG
                self.user.SetWindowTextW(hwnd, "Print label")
                self.user.SetWindowTextW(self.user.GetDlgItem(hwnd, 1), "Print")
            return 0
        self.print_hook = print_hook  # Keep the callback alive while the dialog exists.
        self.dialog.lpfnPrintHook = ct.cast(print_hook, ct.c_void_p).value
        self.ole = ct.WinDLL("ole32", use_last_error=True)
        self._bind(self.ole, "CoInitializeEx", [ct.c_void_p, wt.DWORD], ct.c_long)
        self._bind(self.ole, "CoUninitialize", [], None)
        result = self.ole.CoInitializeEx(None, 6)  # STA, disable obsolete OLE1 DDE
        if result < 0:
            raise OSError(f"Windows printing initialization failed (0x{result & 0xffffffff:08X}).")
        self.com_initialized = True

    @staticmethod
    def _bind(library, name, args, result):
        function = getattr(library, name)
        function.argtypes = args
        function.restype = result

    def owner_handle(self, widget):
        widget.update_idletasks()
        return self.user.GetAncestor(widget.winfo_id(), 2)  # GA_ROOT

    def choose(self, owner):
        """Show the native dialog. Cancel never submits a print job."""
        self.release_dc()
        self.dialog.hwndOwner = owner
        if not self.common.PrintDlgW(ct.byref(self.dialog)):
            error = self.common.CommDlgExtendedError()
            self.release_dc()
            if error:
                raise OSError(f"Windows could not open the print dialog (0x{error:04X}).")
            return False
        if not self.dialog.hDC:
            raise OSError("Windows did not return a printer connection.")
        return True

    def printer_name(self):
        address = self.kernel.GlobalLock(self.dialog.hDevNames)
        if not address:
            raise ct.WinError(ct.get_last_error())
        try:
            names = DevNames.from_address(address)
            return ct.wstring_at(address + names.device * ct.sizeof(wt.WCHAR))
        finally:
            self.kernel.GlobalUnlock(self.dialog.hDevNames)

    def set_label_paper(self):
        """Validate 4x6 portrait through the driver, then apply it to this DC only."""
        address = self.kernel.GlobalLock(self.dialog.hDevMode)
        if not address:
            raise ct.WinError(ct.get_last_error())
        try:
            mode = DevMode.from_address(address)
            if mode.dmSize < ct.sizeof(DevMode):
                raise OSError("This printer returned an unsupported settings format.")
            settings = ct.create_string_buffer(ct.string_at(address, mode.dmSize + mode.dmDriverExtra))
        finally:
            self.kernel.GlobalUnlock(self.dialog.hDevMode)
        requested = DevMode.from_buffer(settings)
        requested.dmFields = (requested.dmFields & ~0x10000) | 0xf  # clear FORMNAME, set paper+orientation
        requested.dmOrientation = 1  # portrait
        requested.dmPaperSize = 0
        requested.dmPaperWidth = 1016  # tenths of a millimeter
        requested.dmPaperLength = 1524
        requested.dmFormName = ""
        name = self.printer_name()
        handle = wt.HANDLE()
        if not self.spool.OpenPrinterW(name, ct.byref(handle), None):
            raise ct.WinError(ct.get_last_error())
        try:
            size = self.spool.DocumentPropertiesW(None, handle, name, None, None, 0)
            if size <= 0:
                raise OSError("Could not read the printer's paper settings.")
            validated = ct.create_string_buffer(max(size, len(settings)))
            if self.spool.DocumentPropertiesW(None, handle, name, validated, settings, 0xa) != 1:
                raise OSError("The printer could not accept 4 x 6 paper. Check Printer Properties.")
            hdc = self.gdi.ResetDCW(self.dialog.hDC, validated)
            if not hdc:
                raise ct.WinError(ct.get_last_error())
            self.dialog.hDC = hdc
        finally:
            self.spool.ClosePrinter(handle)
        return name

    def placement(self):
        caps = lambda index: self.gdi.GetDeviceCaps(self.dialog.hDC, index)
        return label_placement(caps(88), caps(90), caps(110), caps(111), caps(8), caps(10))

    def submit_pdf(self, data, title="Label Fit - 4 x 6 label", output_path=None):
        """Render the actual PDF at device resolution, then submit a single page.

        output_path is for virtual printer verification; normal printing lets
        the selected driver handle its destination.
        """
        if not self.dialog.hDC:
            raise OSError("Choose a printer first.")
        started = False
        try:
            name = self.set_label_paper()
            placement = self.placement()
            with fitz.open(stream=data, filetype="pdf") as doc:
                if len(doc) != 1 or abs(doc[0].rect.width - 288) > .01 or abs(doc[0].rect.height - 432) > .01:
                    raise ValueError("Direct printing expects one 4 x 6 label page.")
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(placement.width / 288,
                                                         placement.height / 432), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            dib = ImageWin.Dib(image)
            info = DocInfo(ct.sizeof(DocInfo), title, output_path, None, 0)
            if self.gdi.StartDocW(self.dialog.hDC, ct.byref(info)) <= 0:
                raise OSError("The printer did not accept the job. Check its connection and queue.")
            started = True
            if self.gdi.StartPage(self.dialog.hDC) <= 0:
                raise OSError("The printer could not start the label page.")
            dib.draw(self.dialog.hDC, (placement.x, placement.y,
                     placement.x + placement.width, placement.y + placement.height))
            if self.gdi.EndPage(self.dialog.hDC) <= 0 or self.gdi.EndDoc(self.dialog.hDC) <= 0:
                raise OSError("Windows could not finish sending the label to the printer.")
            started = False
            return name
        finally:
            if started:
                self.gdi.AbortDoc(self.dialog.hDC)
            self.release_dc()

    def release_dc(self):
        if self.dialog.hDC:
            self.gdi.DeleteDC(self.dialog.hDC)
            self.dialog.hDC = None

    def close(self):
        self.release_dc()
        for attribute in ("hDevMode", "hDevNames"):
            handle = getattr(self.dialog, attribute)
            if handle:
                self.kernel.GlobalFree(handle)
                setattr(self.dialog, attribute, None)
        if self.com_initialized:
            self.ole.CoUninitialize()
            self.com_initialized = False
