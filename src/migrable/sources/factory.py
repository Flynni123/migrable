"""Construct concrete DataSource instances from configuration kinds."""

from __future__ import annotations

from pathlib import Path

from migrable.sources.base import DataSource, DataSourceError
from migrable.sources.csv_source import CsvDataSource
from migrable.sources.excel_source import ExcelDataSource
from migrable.sources.sqlite_source import SQLiteDataSource


def create_source(kind: str, path: str | Path) -> DataSource:
    normalized = kind.lower()
    if normalized == "csv":
        return CsvDataSource(path)
    if normalized in {"excel", "xlsx", "xlsm"}:
        return ExcelDataSource(path)
    if normalized in {"sqlite", "sqlite3", "db"}:
        return SQLiteDataSource(path)
    raise DataSourceError(f"Unsupported data source kind '{kind}'. Supported: csv, excel, sqlite")
