"""Validation and batched execution of a saved migration."""

from __future__ import annotations

from dataclasses import dataclass, field

from migrable.core.mapping import TRANSFORMS, MappingError, RowMapper
from migrable.core.models import ConfigError, MigrationConfig
from migrable.core.schema import TableSchema
from migrable.sources.base import DataSource, DataSourceError
from migrable.sources.factory import create_source


class MigrationError(RuntimeError):
    """A migration could not be completed safely."""


@dataclass(frozen=True, slots=True)
class RowError:
    row_number: int
    message: str


@dataclass(slots=True)
class MigrationReport:
    name: str
    rows_read: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    errors: list[RowError] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return not self.errors


def validate_config(
    config: MigrationConfig, *, source: DataSource | None = None, check_source: bool = True
) -> TableSchema | None:
    """Validate static rules and, optionally, mapped columns against a source."""
    if config.target.mode == "upsert" and not config.primary_key_columns:
        raise ConfigError("target.mode 'upsert' requires at least one primary_key mapping")
    if config.source.kind not in {"csv", "excel", "xlsx", "xlsm", "sqlite", "sqlite3", "db"}:
        raise ConfigError(f"Unsupported source kind: {config.source.kind}")
    if config.target.kind not in {"sqlite", "sqlite3", "db"}:
        raise ConfigError("The first version supports SQLite as a writable target")
    unknown_transforms = sorted(
        {transform for rule in config.mapping for transform in rule.transforms} - set(TRANSFORMS)
    )
    if unknown_transforms:
        raise ConfigError("Unknown transforms: " + ", ".join(unknown_transforms))
    if not check_source:
        return None
    source = source or create_source(config.source.kind, config.source.path)
    schema = source.get_schema(config.source.dataset)
    available = set(schema.column_names())
    missing = sorted(
        rule.source
        for rule in config.mapping
        if rule.source is not None and rule.source not in available
    )
    if missing:
        raise ConfigError("Mapped source columns do not exist: " + ", ".join(missing))
    return schema


class MigrationRunner:
    """Coordinates DataSources while keeping transformation logic backend-neutral."""

    def __init__(self, config: MigrationConfig) -> None:
        self.config = config

    def run(
        self,
        *,
        source: DataSource | None = None,
        target: DataSource | None = None,
    ) -> MigrationReport:
        source = source or create_source(self.config.source.kind, self.config.source.path)
        target = target or create_source(self.config.target.kind, self.config.target.path)
        validate_config(self.config, source=source)
        mapper = RowMapper(self.config.mapping)
        report = MigrationReport(self.config.name)
        try:
            with target.write_transaction():
                target.prepare_dataset(
                    self.config.target.dataset or "",
                    self.config.target_schema,
                    mode=self.config.target.mode,
                )
                for batch in source.read_rows(
                    self.config.source.dataset, batch_size=self.config.options.batch_size
                ):
                    converted: list[dict[str, object]] = []
                    for row in batch:
                        report.rows_read += 1
                        try:
                            converted.append(mapper.map_row(row))
                        except MappingError as error:
                            if self.config.options.on_error == "stop":
                                raise MigrationError(
                                    f"Row {report.rows_read} could not be mapped: {error}"
                                ) from error
                            report.rows_skipped += 1
                            report.errors.append(RowError(report.rows_read, str(error)))
                    target.write_rows(
                        self.config.target.dataset or "",
                        converted,
                        mode=self.config.target.mode,
                        primary_key=self.config.primary_key_columns,
                    )
                    report.rows_written += len(converted)
        except (DataSourceError, ConfigError) as error:
            raise MigrationError(str(error)) from error
        return report
