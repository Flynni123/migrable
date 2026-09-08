from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from migrable.sources.base import DataSourceError
from migrable.sources.csv_source import CsvDataSource
from migrable.sources.excel_source import ExcelDataSource


class CsvSourceTests(unittest.TestCase):
    def test_rejects_duplicate_headers_before_data_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "people.csv"
            path.write_text("ID,ID\n1,2\n", encoding="utf-8")

            with self.assertRaisesRegex(DataSourceError, "non-empty and unique"):
                CsvDataSource(path).get_schema()
            with self.assertRaisesRegex(DataSourceError, "non-empty and unique"):
                list(CsvDataSource(path).read_rows())


@unittest.skipUnless(importlib.util.find_spec("openpyxl"), "openpyxl is an optional dependency")
class ExcelSourceTests(unittest.TestCase):
    def test_lists_sheets_and_reads_rows_in_batches(self) -> None:
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "people.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "People"
            sheet.append(["ID", "Name"])
            sheet.append([1, "Ada"])
            sheet.append([2, "Linus"])
            workbook.create_sheet("Unused")
            workbook.save(path)

            source = ExcelDataSource(path)
            self.assertEqual(source.list_datasets(), ["People", "Unused"])
            self.assertEqual(source.get_schema("People").column_names(), ("ID", "Name"))
            self.assertEqual(
                list(source.read_rows("People", batch_size=1)),
                [[{"ID": 1, "Name": "Ada"}], [{"ID": 2, "Name": "Linus"}]],
            )
