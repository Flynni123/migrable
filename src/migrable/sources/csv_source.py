"""CSV adapter using only Python's standard library."""

from __future__ import annotations

import csv
from collections.abc import Iterator, Sequence
from pathlib import Path

from migrable.core.schema import TableSchema
from migrable.sources.base import DataSource, DataSourceError, Row
from migrable.sources.inspection import schema_from_rows


class CsvDataSource(DataSource):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def dataset_name(self) -> str:
        return self.path.stem

    def _check_dataset(self, dataset: str | None) -> None:
        if dataset and dataset != self.dataset_name:
            raise DataSourceError(f"CSV source has one dataset named '{self.dataset_name}'")
        if not self.path.is_file():
            raise DataSourceError(f"CSV file not found: {self.path}")

    def list_datasets(self) -> list[str]:
        self._check_dataset(None)
        return [self.dataset_name]

    def _dialect(self) -> type[csv.Dialect]:
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(8_192)
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            return csv.excel

    def _headers(self, fieldnames: Sequence[str] | None) -> list[str]:
        if not fieldnames:
            raise DataSourceError(f"CSV file has no header: {self.path}")
        if any(not name.strip() for name in fieldnames) or len(fieldnames) != len(set(fieldnames)):
            raise DataSourceError("CSV headers must be non-empty and unique")
        return list(fieldnames)

    def get_schema(self, dataset: str | None = None) -> TableSchema:
        self._check_dataset(dataset)
        dialect = self._dialect()
        with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, dialect=dialect)
            headers = self._headers(reader.fieldnames)
            rows = [dict(row) for _, row in zip(range(100), reader, strict=False)]
        return schema_from_rows(self.dataset_name, headers, rows)

    def read_rows(
        self, dataset: str | None = None, *, batch_size: int = 1_000
    ) -> Iterator[list[Row]]:
        self._check_dataset(dataset)
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        dialect = self._dialect()

        def batches() -> Iterator[list[Row]]:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, dialect=dialect)
                self._headers(reader.fieldnames)
                batch: list[Row] = []
                for row in reader:
                    batch.append({name: value for name, value in row.items() if name is not None})
                    if len(batch) >= batch_size:
                        yield batch
                        batch = []
                if batch:
                    yield batch

        return batches()
