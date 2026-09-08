"""Command-line entry points for interactive and repeatable migrations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from migrable.core.config import load_config
from migrable.core.migration import MigrationReport, MigrationRunner, validate_config
from migrable.sources.factory import create_source


def _report_as_dict(report: MigrationReport) -> dict[str, object]:
    return {
        "name": report.name,
        "rows_read": report.rows_read,
        "rows_written": report.rows_written,
        "rows_skipped": report.rows_skipped,
        "errors": [
            {"row_number": error.row_number, "message": error.message} for error in report.errors
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrable", description="Repeatable tabular data migrations to SQLite."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tui", help="Open the interactive migration builder")

    run = commands.add_parser("run", help="Run a saved YAML migration")
    run.add_argument("config", type=Path)
    run.add_argument("--json", action="store_true", help="Emit the execution report as JSON")

    validate = commands.add_parser("validate", help="Check a migration and source columns")
    validate.add_argument("config", type=Path)

    inspect = commands.add_parser("inspect", help="Inspect available datasets and columns")
    inspect.add_argument("kind", choices=("csv", "excel", "sqlite"))
    inspect.add_argument("path", type=Path)
    inspect.add_argument("--dataset", help="Worksheet or SQLite table to inspect")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "tui":
            from migrable.tui.app import run_tui

            run_tui()
            return
        if args.command == "inspect":
            source = create_source(args.kind, args.path)
            datasets = source.list_datasets()
            payload: dict[str, object] = {"datasets": datasets}
            if args.dataset:
                schema = source.get_schema(args.dataset)
                payload["schema"] = [
                    {"name": column.name, "type": column.type.value} for column in schema.columns
                ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        config = load_config(args.config)
        if args.command == "validate":
            validated_schema = validate_config(config)
            assert validated_schema is not None
            print(f"Valid: {config.name} ({len(validated_schema.columns)} source columns)")
            return
        report = MigrationRunner(config).run()
        if args.json:
            print(json.dumps(_report_as_dict(report), ensure_ascii=False, indent=2))
        else:
            print(
                f"Completed {report.name}: {report.rows_written}/{report.rows_read} rows written"
                + (f", {report.rows_skipped} skipped" if report.rows_skipped else "")
            )
            for error in report.errors[:10]:
                print(f"  row {error.row_number}: {error.message}", file=sys.stderr)
            if len(report.errors) > 10:
                print(f"  …and {len(report.errors) - 10} more errors", file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
