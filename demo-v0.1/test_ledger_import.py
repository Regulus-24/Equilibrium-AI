import io
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from ledger import Ledger
from ledger_import import preview_bytes


class LedgerImportTests(unittest.TestCase):
    def test_csv_preview_and_atomic_import(self):
        raw = "日期,收支类型,金额,分类,交易对方,备注\n2026-10-01,支出,25.10,餐饮,午餐,工作日\n2026-10-02,收入,100,工资,公司,十月\n".encode("utf-8")
        preview = preview_bytes("账单.csv", raw)
        self.assertEqual(preview["total_rows"], 2)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp))
            current = ledger.public()["version"]
            result = ledger.import_rows({"version": current, "rows": preview["rows"], "confirm": True})
            self.assertEqual(result["imported"], 2)
            self.assertEqual(len(ledger.public()["entries"]), 2)

    def test_import_rejects_invalid_row_before_write(self):
        raw = "日期,收支类型,金额,分类\n2026-10-01,支出,-1,餐饮\n".encode("utf-8")
        preview = preview_bytes("账单.csv", raw)
        self.assertEqual(preview["total_rows"], 0)
        self.assertEqual(preview["errors"][0]["line"], 2)

    def test_preview_skips_existing_and_file_duplicates(self):
        raw = ("日期,收支类型,金额,分类,交易对方\n"
               "2026-10-01,支出,25.10,餐饮,午餐\n"
               "2026-10-01,支出,25.10,餐饮,午餐\n"
               "2026-10-02,收入,100,工资,公司\n").encode("utf-8")
        first = preview_bytes("账单.csv", raw)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp))
            ledger.import_rows({"version": ledger.public()["version"], "rows": first["rows"], "confirm": True})
            second = preview_bytes("账单.csv", raw, ledger.public()["entries"])
            self.assertEqual(second["total_rows"], 0)
            self.assertEqual(second["duplicate_count"], 3)
            self.assertIn("账本中已有", second["duplicates"][0]["reason"])

    def test_xlsx_first_sheet_preview(self):
        rows = [["日期", "收支类型", "金额", "分类"], ["2026-10-03", "支出", "12.5", "交通"]]
        sheet = "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>"
        for ri, row in enumerate(rows, 1):
            cells = "".join(f"<c r='{chr(64+ci)}{ri}' t='inlineStr'><is><t>{escape(str(v))}</t></is></c>" for ci, v in enumerate(row, 1))
            sheet += f"<row r='{ri}'>{cells}</row>"
        sheet += "</sheetData></worksheet>"
        workbook = "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets><sheet name='Sheet1' sheetId='1' r:id='rId1'/></sheets></workbook>"
        rels = "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='worksheets/sheet1.xml' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet'/></Relationships>"
        out = io.BytesIO()
        with ZipFile(out, "w", ZIP_DEFLATED) as z:
            z.writestr("xl/workbook.xml", workbook)
            z.writestr("xl/_rels/workbook.xml.rels", rels)
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        self.assertEqual(preview_bytes("账单.xlsx", out.getvalue())["total_rows"], 1)


if __name__ == "__main__":
    unittest.main()
