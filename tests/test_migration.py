from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from migrable.core.migration import MigrationError, MigrationRunner, validate_config
from migrable.core.models import (
    MappingRule,
    MigrationConfig,
    MigrationOptions,
    SourceConfig,
    TargetConfig,
)
from migrable.core.schema import ColumnType
from migrable.sources.csv_source import CsvDataSource


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.csv_path = self.directory / "people.csv"
        self.db_path = self.directory / "application.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def config(self, *, mode: str = "replace", error_policy: str = "stop") -> MigrationConfig:
        return MigrationConfig(
            name="people-import",
            source=SourceConfig("csv", self.csv_path),
            target=TargetConfig("sqlite", self.db_path, "people", mode),  # type: ignore[arg-type]
            mapping=(
                MappingRule("id", source="ID", type=ColumnType.INTEGER, primary_key=True),
                MappingRule("name", source="Name", transforms=("trim",)),
                MappingRule("email", source="Email", transforms=("trim", "lowercase")),
                MappingRule("active", source="Active", type=ColumnType.BOOLEAN),
            ),
            options=MigrationOptions(batch_size=1, on_error=error_policy),  # type: ignore[arg-type]
        )

    def test_csv_schema_and_replace_then_upsert(self) -> None:
        self.csv_path.write_text(
            "ID,Name,Email,Active\n1, Ada ,ADA@EXAMPLE.COM,yes\n2,Linus,linus@example.com,0\n",
            encoding="utf-8",
        )
        schema = CsvDataSource(self.csv_path).get_schema()
        self.assertEqual(schema.column_names(), ("ID", "Name", "Email", "Active"))
        self.assertEqual(validate_config(self.config()), schema)

        first = MigrationRunner(self.config()).run()
        self.assertEqual((first.rows_read, first.rows_written, first.rows_skipped), (2, 2, 0))

        self.csv_path.write_text(
            "ID,Name,Email,Active\n1,Ada Lovelace,ada@example.com,true\n",
            encoding="utf-8",
        )
        second = MigrationRunner(self.config(mode="upsert")).run()
        self.assertEqual(second.rows_written, 1)
        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute(
                "SELECT id, name, email, active FROM people ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            rows, [(1, "Ada Lovelace", "ada@example.com", 1), (2, "Linus", "linus@example.com", 0)]
        )

    def test_report_and_skip_keeps_valid_rows(self) -> None:
        self.csv_path.write_text(
            "ID,Name,Email,Active\n1,Ada,ada@example.com,true\nnot-a-number,Oops,x@example.com,false\n",
            encoding="utf-8",
        )
        report = MigrationRunner(self.config(error_policy="report_and_skip")).run()
        self.assertEqual((report.rows_read, report.rows_written, report.rows_skipped), (2, 1, 1))
        self.assertIn("id", report.errors[0].message)

    def test_upsert_needs_key(self) -> None:
        self.csv_path.write_text("Name\nAda\n", encoding="utf-8")
        config = MigrationConfig(
            name="invalid",
            source=SourceConfig("csv", self.csv_path),
            target=TargetConfig("sqlite", self.db_path, "people", "upsert"),
            mapping=(MappingRule("name", source="Name"),),
        )
        with self.assertRaisesRegex(ValueError, "primary_key"):
            validate_config(config, check_source=False)

    def test_replace_rolls_back_if_a_row_cannot_be_mapped(self) -> None:
        self.csv_path.write_text("ID\nnot-an-integer\n", encoding="utf-8")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("CREATE TABLE people (id INTEGER, name TEXT)")
            connection.execute("INSERT INTO people VALUES (1, 'preserve me')")
            connection.commit()
        finally:
            connection.close()

        config = MigrationConfig(
            name="people-import",
            source=SourceConfig("csv", self.csv_path),
            target=TargetConfig("sqlite", self.db_path, "people", "replace"),
            mapping=(MappingRule("id", source="ID", type=ColumnType.INTEGER),),
        )

        with self.assertRaisesRegex(MigrationError, "could not be mapped"):
            MigrationRunner(config).run()

        connection = sqlite3.connect(self.db_path)
        try:
            rows = connection.execute("SELECT id, name FROM people").fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [(1, "preserve me")])

    def test_primary_key_is_required_and_rejects_null_values(self) -> None:
        self.csv_path.write_text("ID,Name\n,Ada\n", encoding="utf-8")
        config = MigrationConfig(
            name="people-import",
            source=SourceConfig("csv", self.csv_path),
            target=TargetConfig("sqlite", self.db_path, "people", "upsert"),
            mapping=(
                MappingRule("id", source="ID", primary_key=True),
                MappingRule("name", source="Name"),
            ),
        )

        self.assertFalse(config.target_schema.columns[0].nullable)
        with self.assertRaisesRegex(MigrationError, "id: value is required"):
            MigrationRunner(config).run()

    def test_upsert_requires_a_matching_existing_constraint(self) -> None:
        self.csv_path.write_text("ID,Name\n1,Ada\n", encoding="utf-8")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("CREATE TABLE people (id INTEGER, name TEXT)")
            connection.commit()
        finally:
            connection.close()

        config = MigrationConfig(
            name="people-import",
            source=SourceConfig("csv", self.csv_path),
            target=TargetConfig("sqlite", self.db_path, "people", "upsert"),
            mapping=(
                MappingRule("id", source="ID", type=ColumnType.INTEGER, primary_key=True),
                MappingRule("name", source="Name"),
            ),
        )

        with self.assertRaisesRegex(MigrationError, "PRIMARY KEY or UNIQUE"):
            MigrationRunner(config).run()
