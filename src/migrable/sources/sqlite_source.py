"""SQLite implementation of the common DataSource contract."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from migrable.core.schema import ColumnSchema, ColumnType, TableSchema
from migrable.sources.base import DataSource, DataSourceError, Row


def _quote(identifier: str) -> str:
    if not identifier:
        raise DataSourceError("Dataset and column names must not be empty")
    return '"' + identifier.replace('"', '""') + '"'


def _column_type(sqlite_type: str) -> ColumnType:
    type_name = (sqlite_type or "").upper()
    if "INT" in type_name:
        return ColumnType.INTEGER
    if any(token in type_name for token in ("REAL", "FLOA", "DOUB")):
        return ColumnType.REAL
    if any(token in type_name for token in ("NUM", "DEC")):
        return ColumnType.DECIMAL
    if "DATE" in type_name or "TIME" in type_name:
        return ColumnType.DATETIME if "TIME" in type_name else ColumnType.DATE
    return ColumnType.TEXT


class SQLiteDataSource(DataSource):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._transaction_connection: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as error:
            raise DataSourceError(f"Could not open SQLite database {self.path}: {error}") from error

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        if self._transaction_connection is not None:
            yield self._transaction_connection
            return
        with self._connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Write one migration atomically and keep one connection for all batches."""
        if self._transaction_connection is not None:
            raise DataSourceError("SQLite write transactions cannot be nested")
        with self._connection() as connection:
            self._transaction_connection = connection
            try:
                connection.execute("BEGIN")
                yield
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self._transaction_connection = None

    def list_datasets(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def _exists(self, connection: sqlite3.Connection, dataset: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
                (dataset,),
            ).fetchone()
            is not None
        )

    def get_schema(self, dataset: str | None = None) -> TableSchema:
        if not dataset:
            raise DataSourceError("A SQLite dataset (table) is required")
        with self._connection() as connection:
            return self._schema_from_connection(connection, dataset)

    def _schema_from_connection(self, connection: sqlite3.Connection, dataset: str) -> TableSchema:
        rows = connection.execute(f"PRAGMA table_info({_quote(dataset)})").fetchall()
        if not rows:
            raise DataSourceError(f"SQLite table '{dataset}' does not exist or has no columns")
        return TableSchema(
            dataset,
            tuple(
                ColumnSchema(
                    str(row["name"]),
                    _column_type(str(row["type"])),
                    not bool(row["notnull"]),
                    bool(row["pk"]),
                )
                for row in rows
            ),
        )

    def read_rows(
        self, dataset: str | None = None, *, batch_size: int = 1_000
    ) -> Iterator[list[Row]]:
        if not dataset:
            raise DataSourceError("A SQLite dataset (table) is required")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        def batches() -> Iterator[list[Row]]:
            with self._connection() as connection:
                cursor = connection.execute(f"SELECT * FROM {_quote(dataset)}")
                while rows := cursor.fetchmany(batch_size):
                    yield [dict(row) for row in rows]

        return batches()

    def prepare_dataset(self, dataset: str, schema: TableSchema, *, mode: str) -> None:
        if mode not in {"append", "replace", "upsert"}:
            raise DataSourceError(f"Unknown write mode: {mode}")
        try:
            with self._write_connection() as connection:
                exists = self._exists(connection, dataset)
                if exists and mode == "replace":
                    connection.execute(f"DROP TABLE {_quote(dataset)}")
                    exists = False
                if not exists:
                    definitions = []
                    primary_keys = [column.name for column in schema.columns if column.primary_key]
                    for column in schema.columns:
                        definition = f"{_quote(column.name)} {column.type.sqlite_type}"
                        if not column.nullable:
                            definition += " NOT NULL"
                        definitions.append(definition)
                    if primary_keys:
                        definitions.append(
                            "PRIMARY KEY (" + ", ".join(_quote(key) for key in primary_keys) + ")"
                        )
                    sql = f"CREATE TABLE {_quote(dataset)} (" + ", ".join(definitions) + ")"
                    connection.execute(sql)
                else:
                    actual = set(self._schema_from_connection(connection, dataset).column_names())
                    required = set(schema.column_names())
                    missing = required - actual
                    if missing:
                        raise DataSourceError(
                            f"Target table '{dataset}' is missing mapped columns: {', '.join(sorted(missing))}"
                        )
                    if mode == "upsert" and not self._has_conflict_target(
                        connection,
                        dataset,
                        tuple(column.name for column in schema.columns if column.primary_key),
                    ):
                        raise DataSourceError(
                            f"Target table '{dataset}' needs a PRIMARY KEY or UNIQUE constraint "
                            "matching the configured upsert keys"
                        )
        except sqlite3.Error as error:
            raise DataSourceError(f"Could not prepare table '{dataset}': {error}") from error

    def _has_conflict_target(
        self, connection: sqlite3.Connection, dataset: str, primary_key: tuple[str, ...]
    ) -> bool:
        table_info = connection.execute(f"PRAGMA table_info({_quote(dataset)})").fetchall()
        table_key = tuple(
            str(row["name"])
            for row in sorted(table_info, key=lambda row: int(row["pk"]))
            if row["pk"]
        )
        if table_key == primary_key:
            return True
        indexes = connection.execute(f"PRAGMA index_list({_quote(dataset)})").fetchall()
        for index in indexes:
            if not index["unique"] or index["partial"]:
                continue
            index_name = str(index["name"])
            columns = tuple(
                str(row["name"])
                for row in connection.execute(f"PRAGMA index_info({_quote(index_name)})").fetchall()
            )
            if columns == primary_key:
                return True
        return False

    def write_rows(
        self,
        dataset: str,
        rows: Sequence[Row],
        *,
        mode: str,
        primary_key: tuple[str, ...] = (),
    ) -> None:
        if not rows:
            return
        columns = tuple(rows[0].keys())
        if not columns:
            return
        if any(tuple(row.keys()) != columns for row in rows):
            raise DataSourceError("All rows in a write batch must have the same columns")
        if mode == "upsert" and not primary_key:
            raise DataSourceError("upsert requires at least one mapping column marked primary_key")
        quoted_columns = ", ".join(_quote(column) for column in columns)
        values = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {_quote(dataset)} ({quoted_columns}) VALUES ({values})"
        if mode == "upsert":
            updates = [column for column in columns if column not in primary_key]
            if updates:
                sql += (
                    " ON CONFLICT ("
                    + ", ".join(_quote(key) for key in primary_key)
                    + ") DO UPDATE SET "
                )
                sql += ", ".join(
                    f"{_quote(column)} = excluded.{_quote(column)}" for column in updates
                )
            else:
                sql += (
                    " ON CONFLICT ("
                    + ", ".join(_quote(key) for key in primary_key)
                    + ") DO NOTHING"
                )
        try:
            with self._write_connection() as connection:
                connection.executemany(
                    sql, [tuple(row[column] for column in columns) for row in rows]
                )
        except sqlite3.Error as error:
            raise DataSourceError(f"Could not write to table '{dataset}': {error}") from error
