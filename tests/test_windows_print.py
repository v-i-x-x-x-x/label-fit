# SPDX-License-Identifier: AGPL-3.0-only
import ctypes as ct
from ctypes import wintypes as wt
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pymupdf as fitz

from windows_print import DevMode, DevNames, PrintDialog, PrintPlacement, WindowsPrinter, label_placement


def test_label():
    with fitz.open() as doc:
        page = doc.new_page(width=288, height=432)
        page.insert_text((30, 40), "PRINT TEST - DO NOT SHIP", fontsize=12)
        page.draw_rect((15, 15, 273, 417), color=(0, 0, 0))
        for i in range(45):
            x = 30 + i * 5
            page.draw_rect((x, 280, x + 2, 370), color=None, fill=(0, 0, 0))
        return doc.tobytes()


class PlacementTests(unittest.TestCase):
    def test_203_dpi_thermal_label(self):
        self.assertEqual(label_placement(203, 203, 812, 1218, 812, 1218),
                         PrintPlacement(0, 0, 812, 1218))

    def test_hardware_margins_do_not_clip(self):
        result = label_placement(300, 300, 1200, 1800, 1164, 1764)
        self.assertLessEqual(result.x + result.width, 1164)
        self.assertLessEqual(result.y + result.height, 1764)
        self.assertAlmostEqual(result.width / result.height, 2 / 3, places=3)

    def test_100_by_150_mm_label(self):
        result = label_placement(203, 203, 799, 1199, 799, 1199)
        self.assertLessEqual(result.width, 799)
        self.assertLessEqual(result.height, 1199)

    def test_non_square_device_pixels_keep_physical_proportions(self):
        result = label_placement(300, 600, 1200, 3600, 1150, 3450)
        self.assertAlmostEqual((result.width / 300) / (result.height / 600), 2 / 3, places=3)

    def test_letter_and_landscape_rejected(self):
        for w, h in ((2550, 3300), (1800, 1200)):
            with self.assertRaisesRegex(ValueError, "Printer Properties"):
                label_placement(300, 300, w, h, w, h)
        with self.assertRaises(ValueError):
            label_placement(0, 300, 1200, 1800, 1200, 1800)


class PrintLifecycleTests(unittest.TestCase):
    def fake_printer(self):
        printer = object.__new__(WindowsPrinter)
        printer.dialog = PrintDialog()
        printer.dialog.hDC = 123
        printer.gdi = Mock()
        printer.gdi.StartDocW.return_value = 1
        printer.gdi.StartPage.return_value = 1
        printer.gdi.EndPage.return_value = 1
        printer.gdi.EndDoc.return_value = 1
        printer.set_label_paper = Mock(return_value="Test label printer")
        printer.placement = Mock(return_value=PrintPlacement(0, 0, 812, 1218))
        printer.common = Mock()
        return printer

    def test_cancel_never_starts_a_job(self):
        printer = self.fake_printer()
        printer.common.PrintDlgW.return_value = False
        printer.common.CommDlgExtendedError.return_value = 0
        self.assertFalse(printer.choose(999))
        printer.gdi.StartDocW.assert_not_called()
        self.assertIsNone(printer.dialog.hDC)

    def test_print_action_returns_selected_connection(self):
        printer = self.fake_printer()
        def dialog_result(pointer):
            pointer._obj.hDC = 456
            return True
        printer.common.PrintDlgW.side_effect = dialog_result
        self.assertTrue(printer.choose(999))
        self.assertEqual(printer.dialog.hDC, 456)
        printer.gdi.StartDocW.assert_not_called()

    def test_draw_failure_aborts_job_and_releases_dc(self):
        printer = self.fake_printer()
        with patch("windows_print.ImageWin.Dib") as dib:
            dib.return_value.draw.side_effect = OSError("rendering failed")
            with self.assertRaises(OSError):
                printer.submit_pdf(test_label())
        printer.gdi.AbortDoc.assert_called_once_with(123)
        printer.gdi.DeleteDC.assert_called_once_with(123)
        self.assertIsNone(printer.dialog.hDC)

    def test_driver_handles_copies_with_only_one_submission(self):
        printer = self.fake_printer()
        with patch("windows_print.ImageWin.Dib") as dib:
            self.assertEqual(printer.submit_pdf(test_label()), "Test label printer")
            self.assertEqual(dib.call_args.args[0].size, (812, 1218))
        printer.gdi.StartDocW.assert_called_once()
        printer.gdi.StartPage.assert_called_once()
        printer.gdi.EndDoc.assert_called_once()
        printer.gdi.AbortDoc.assert_not_called()
        printer.gdi.DeleteDC.assert_called_once()

    def test_wrong_paper_prevents_submission(self):
        printer = self.fake_printer()
        printer.placement.side_effect = ValueError("wrong paper")
        with self.assertRaises(ValueError):
            printer.submit_pdf(test_label())
        printer.gdi.StartDocW.assert_not_called()
        printer.gdi.DeleteDC.assert_called_once()


def select_test_printer(printer, name):
    """Create only local settings/DCs. Never modify printer-wide preferences."""
    printer._bind(printer.kernel, "GlobalAlloc", [wt.UINT, ct.c_size_t], wt.HGLOBAL)
    printer._bind(printer.gdi, "CreateDCW",
                  [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ct.c_void_p], wt.HDC)
    handle = wt.HANDLE()
    if not printer.spool.OpenPrinterW(name, ct.byref(handle), None):
        raise ct.WinError(ct.get_last_error())
    try:
        size = printer.spool.DocumentPropertiesW(None, handle, name, None, None, 0)
        if size < ct.sizeof(DevMode):
            raise ValueError("Printer settings unavailable")
        settings = ct.create_string_buffer(size)
        if printer.spool.DocumentPropertiesW(None, handle, name, settings, None, 2) != 1:
            raise ValueError("Could not read driver settings")
    finally:
        printer.spool.ClosePrinter(handle)

    def global_copy(data):
        memory = printer.kernel.GlobalAlloc(0x42, len(data))
        if not memory:
            raise MemoryError("Could not allocate print settings")
        address = printer.kernel.GlobalLock(memory)
        try:
            ct.memmove(address, data, len(data))
        finally:
            printer.kernel.GlobalUnlock(memory)
        return memory

    printer.dialog.hDevMode = global_copy(settings.raw)
    names = DevNames(4, 4 + len("WINSPOOL") + 1, 4 + len("WINSPOOL") + len(name) + 2, 0)
    strings = ct.create_unicode_buffer(f"WINSPOOL\0{name}\0PORTPROMPT:\0")
    printer.dialog.hDevNames = global_copy(bytes(names) + bytes(strings))
    printer.dialog.hDC = printer.gdi.CreateDCW("WINSPOOL", name, None, settings)
    if not printer.dialog.hDC:
        raise ct.WinError(ct.get_last_error())


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("LABEL_FIT_PRINT_TESTS") == "1",
                     "Set LABEL_FIT_PRINT_TESTS=1 to verify the Microsoft PDF driver; no paper is used")
class VirtualPrinterTests(unittest.TestCase):
    def test_native_print_to_pdf(self):
        printer = WindowsPrinter()
        try:
            select_test_printer(printer, "Microsoft Print to PDF")
            with tempfile.TemporaryDirectory() as directory:
                output = str(Path(directory) / "printed-label.pdf")
                self.assertEqual(printer.submit_pdf(test_label(), output_path=output), "Microsoft Print to PDF")
                with fitz.open(output) as printed:
                    self.assertEqual(len(printed), 1)
                    self.assertAlmostEqual(printed[0].rect.width, 288, delta=1)
                    self.assertAlmostEqual(printed[0].rect.height, 432, delta=1)
                    pix = printed[0].get_pixmap(alpha=False)
                    self.assertLess(min(pix.samples), 100)
        finally:
            printer.close()


if __name__ == "__main__":
    unittest.main()
