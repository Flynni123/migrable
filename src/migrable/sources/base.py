"""The common adapter contract for files and databases."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from migrable.core.schema import TableSchema

Row = dict[str, object]


class DataSourceError(RuntimeError):
    """A source could not be inspected, read, or written."""


class DataSource(ABC):
    """A tabular data endpoint, regardless of whether it is a file or database.

    A *dataset* is a CSV file, an Excel worksheet, or a database table. Read-only
    sources leave the write methods unimplemented, which keeps the migration
    engine independent from concrete input/output types.
    """

    @abstractmethod
    def list_datasets(self) -> list[str]:
        """Return selectable worksheets, files, or tables."""

    @abstractmethod
    def get_schema(self, dataset: str | None = None) -> TableSchema:
        """Return the dataset's columns using neutral type names."""

    @abstractmethod
    def read_rows(
        self, dataset: str | None = None, *, batch_size: int = 1_000
    ) -> Iterator[list[Row]]:
        """Yield records in bounded batches."""

    def prepare_dataset(self, dataset: str, schema: TableSchema, *, mode: str) -> None:
        raise DataSourceError(f"{type(self).__name__} cannot write datasets")

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Group a migration's target writes when the backend supports transactions.

        Read-only and simple test adapters retain the no-op implementation. Writable
        backends should override it to provide their native atomicity guarantees.
        """
        yield

    def write_rows(
        self,
        dataset: str,
        rows: Sequence[Row],
        *,
        mode: str,
        primary_key: tuple[str, ...] = (),
    ) -> None:
        raise DataSourceError(f"{type(self).__name__} cannot write datasets")
