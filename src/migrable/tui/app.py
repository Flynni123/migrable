"""A lightweight Textual wizard for composing a migration configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from migrable.core.config import save_config
from migrable.core.mapping import RowMapper
from migrable.core.migration import MigrationRunner
from migrable.core.models import (
    MappingRule,
    MigrationConfig,
    MigrationOptions,
    SourceConfig,
    TargetConfig,
    WriteMode,
)
from migrable.core.schema import ColumnType, TableSchema
from migrable.sources.factory import create_source


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return value.strip("_") or "column"


def run_tui() -> None:
    if MigrationApp is None:  # pragma: no cover - dependency problem
        raise RuntimeError("The TUI requires Textual. Run `pip install -e .` first.")
    try:
        MigrationApp().run()
    except ImportError as error:  # pragma: no cover - dependency problem
        raise RuntimeError("The TUI requires Textual. Run `pip install -e .` first.") from error


try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, VerticalScroll
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        Select,
        Static,
    )
except ImportError:  # Import stays optional for headless CLI users.
    MigrationApp = None
else:

    class MigrationApp(App[None]):  # type: ignore[no-redef]
        """Build and run simple source-to-SQLite mappings without leaving the terminal."""

        TITLE = "migrable"
        SUB_TITLE = "Tabular data → SQLite"
        CSS = """
        Screen { layout: vertical; }
        #body { height: 1fr; padding: 1 2; }
        .section { border: round $primary; padding: 1; margin-bottom: 1; }
        .section-title { color: $accent; text-style: bold; margin-bottom: 1; }
        Input, Select { width: 1fr; margin-right: 1; }
        Button { margin-right: 1; }
        #mapping-table { height: 11; }
        #status { min-height: 4; border: round $secondary; padding: 1; }
        #mapping-controls { height: auto; }
        """

        def __init__(self) -> None:
            super().__init__()
            self.source_schema: TableSchema | None = None
            self.rules: list[MappingRule] = []

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with VerticalScroll(id="body"):
                with Container(classes="section"):
                    yield Label("1. Quelle analysieren", classes="section-title")
                    with Horizontal():
                        yield Select(
                            [("CSV", "csv"), ("Excel", "excel"), ("SQLite", "sqlite")],
                            value="csv",
                            id="source-kind",
                            allow_blank=False,
                        )
                        yield Input(placeholder="Pfad zur Datei oder Datenbank", id="source-path")
                        yield Input(placeholder="Blatt / Tabelle (optional)", id="source-dataset")
                        yield Button("Analysieren", id="analyze", variant="primary")
                with Container(classes="section"):
                    yield Label("2. Ziel festlegen", classes="section-title")
                    with Horizontal():
                        yield Input(placeholder="SQLite-Datei", id="target-path")
                        yield Input(placeholder="Zieltabelle", id="target-dataset")
                        yield Select(
                            [("Anhängen", "append"), ("Ersetzen", "replace"), ("Upsert", "upsert")],
                            value="append",
                            id="target-mode",
                            allow_blank=False,
                        )
                with Container(classes="section"):
                    yield Label("3. Spalten zuordnen", classes="section-title")
                    with Horizontal(id="mapping-controls"):
                        yield Select([], prompt="Quellspalte", id="mapping-source")
                        yield Input(placeholder="Zielspalte", id="mapping-target")
                        yield Select(
                            [(item.value, item.value) for item in ColumnType],
                            value="text",
                            id="mapping-type",
                            allow_blank=False,
                        )
                        yield Input(
                            placeholder="Transformationen: trim, lowercase", id="mapping-transforms"
                        )
                        yield Checkbox("Pflichtfeld", id="mapping-required")
                        yield Checkbox("Schlüssel", id="mapping-primary-key")
                    with Horizontal():
                        yield Button("Spalte hinzufügen", id="add-mapping")
                        yield Button("Automatisch zuordnen", id="suggest-mapping")
                        yield Input(placeholder="Zielspalte entfernen", id="remove-target")
                        yield Button("Entfernen", id="remove-mapping", variant="warning")
                    yield DataTable(id="mapping-table")
                with Container(classes="section"):
                    yield Label("4. Prüfen, speichern oder ausführen", classes="section-title")
                    with Horizontal():
                        yield Input(value="migration.yml", id="config-path")
                        yield Button("Vorschau", id="preview")
                        yield Button("Konfiguration speichern", id="save")
                        yield Button("Migration ausführen", id="run", variant="success")
                yield Static("Wähle eine Quelle und klicke auf „Analysieren“.", id="status")
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#mapping-table", DataTable)
            table.add_columns("Quelle", "Ziel", "Typ", "Transformationen", "Pflicht", "Schlüssel")

        def _value(self, selector: str) -> str:
            widget = self.query_one(selector)
            value = getattr(widget, "value", "")
            return value if isinstance(value, str) else ""

        def _status(self, message: str) -> None:
            self.query_one("#status", Static).update(message)

        def _config(self) -> MigrationConfig:
            source_path = self._value("#source-path").strip()
            target_path = self._value("#target-path").strip()
            target_dataset = self._value("#target-dataset").strip()
            if not source_path or not target_path or not target_dataset:
                raise ValueError("Quelle, SQLite-Zieldatei und Zieltabelle sind erforderlich.")
            if not self.rules:
                raise ValueError("Füge mindestens eine Spaltenzuordnung hinzu.")
            source_dataset = self._value("#source-dataset").strip() or None
            return MigrationConfig(
                name=f"import-{target_dataset}",
                source=SourceConfig(self._value("#source-kind"), Path(source_path), source_dataset),
                target=TargetConfig(
                    "sqlite",
                    Path(target_path),
                    target_dataset,
                    cast(WriteMode, self._value("#target-mode")),
                ),
                mapping=tuple(self.rules),
                options=MigrationOptions(on_error="report_and_skip"),
            )

        def _refresh_rules(self) -> None:
            table = self.query_one("#mapping-table", DataTable)
            table.clear()
            for rule in self.rules:
                table.add_row(
                    rule.source or "<Default>",
                    rule.target,
                    rule.type.value,
                    ", ".join(rule.transforms),
                    "✓" if rule.required else "",
                    "✓" if rule.primary_key else "",
                )

        def _add_rule(self, rule: MappingRule) -> None:
            self.rules = [existing for existing in self.rules if existing.target != rule.target]
            self.rules.append(rule)
            self._refresh_rules()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            try:
                if event.button.id == "analyze":
                    self._analyze()
                elif event.button.id == "add-mapping":
                    self._add_mapping()
                elif event.button.id == "suggest-mapping":
                    self._suggest_mapping()
                elif event.button.id == "remove-mapping":
                    target = self._value("#remove-target").strip()
                    self.rules = [rule for rule in self.rules if rule.target != target]
                    self._refresh_rules()
                    self._status(f"Mapping für „{target}“ entfernt.")
                elif event.button.id == "preview":
                    self._preview()
                elif event.button.id == "save":
                    config_path = self._value("#config-path").strip()
                    save_config(self._config(), config_path)
                    self._status(f"Konfiguration gespeichert: {config_path}")
                elif event.button.id == "run":
                    report = MigrationRunner(self._config()).run()
                    self._status(
                        f"Fertig: {report.rows_written}/{report.rows_read} Zeilen geschrieben"
                        + (f", {report.rows_skipped} übersprungen." if report.rows_skipped else ".")
                    )
            except Exception as error:  # UI boundary: retain a usable app after an invalid input.
                self._status(f"[bold red]Fehler:[/] {error}")

        def _analyze(self) -> None:
            path = self._value("#source-path").strip()
            if not path:
                raise ValueError("Gib einen Quellpfad an.")
            source = create_source(self._value("#source-kind"), path)
            requested_dataset = self._value("#source-dataset").strip() or None
            datasets = source.list_datasets()
            if requested_dataset is None:
                requested_dataset = datasets[0] if datasets else None
                if requested_dataset:
                    self.query_one("#source-dataset", Input).value = requested_dataset
            self.source_schema = source.get_schema(requested_dataset)
            choices = [(column.name, column.name) for column in self.source_schema.columns]
            self.query_one("#mapping-source", Select).set_options(choices)
            self._status(
                f"Quelle bereit: {self.source_schema.name} mit {len(self.source_schema.columns)} Spalten."
            )

        def _add_mapping(self) -> None:
            source = self._value("#mapping-source")
            target = self._value("#mapping-target").strip()
            if not source or not target:
                raise ValueError("Wähle eine Quellspalte und gib eine Zielspalte an.")
            transforms = tuple(
                item.strip()
                for item in self._value("#mapping-transforms").split(",")
                if item.strip()
            )
            rule = MappingRule(
                target=target,
                source=source,
                transforms=transforms,
                type=ColumnType(self._value("#mapping-type")),
                required=self.query_one("#mapping-required", Checkbox).value,
                primary_key=self.query_one("#mapping-primary-key", Checkbox).value,
            )
            self._add_rule(rule)
            self._status(f"„{source}“ wird nach „{target}“ geschrieben.")

        def _suggest_mapping(self) -> None:
            if not self.source_schema:
                raise ValueError("Analysiere zuerst eine Quelle.")
            self.rules = [
                MappingRule(target=_slugify(column.name), source=column.name, type=column.type)
                for column in self.source_schema.columns
            ]
            self._refresh_rules()
            self._status(
                "Spalten wurden automatisch mit bereinigten Namen zugeordnet. Prüfe Typen und Schlüssel."
            )

        def _preview(self) -> None:
            config = self._config()
            source = create_source(config.source.kind, config.source.path)
            batch = next(source.read_rows(config.source.dataset, batch_size=5), [])
            mapper = RowMapper(config.mapping)
            preview = [mapper.map_row(row) for row in batch]
            self._status(
                "Vorschau der ersten fünf Zeilen:\n"
                + json.dumps(preview, ensure_ascii=False, indent=2, default=str)
            )
