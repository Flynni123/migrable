"""Validated, serialisable definitions for a migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from migrable.core.schema import ColumnSchema, ColumnType, TableSchema

WriteMode = Literal["append", "replace", "upsert"]
ErrorPolicy = Literal["stop", "report_and_skip"]


class ConfigError(ValueError):
    """A migration configuration is incomplete or invalid."""


def _required(mapping: dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        raise ConfigError(f"Missing required field: {key}")
    return value


@dataclass(frozen=True, slots=True)
class SourceConfig:
    kind: str
    path: Path
    dataset: str | None = None

    @classmethod
    def from_dict(cls, raw: object, *, section: str) -> SourceConfig:
        if not isinstance(raw, dict):
            raise ConfigError(f"{section} must be an object")
        return cls(
            kind=str(_required(raw, "kind")).lower(),
            path=Path(str(_required(raw, "path"))),
            dataset=str(raw["dataset"]) if raw.get("dataset") is not None else None,
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "path": str(self.path)}
        if self.dataset:
            data["dataset"] = self.dataset
        return data


@dataclass(frozen=True, slots=True)
class TargetConfig(SourceConfig):
    mode: WriteMode = "append"

    @classmethod
    def from_target_dict(cls, raw: object) -> TargetConfig:
        if not isinstance(raw, dict):
            raise ConfigError("target must be an object")
        source = SourceConfig.from_dict(raw, section="target")
        dataset = source.dataset
        if not dataset:
            raise ConfigError("Missing required field: target.dataset")
        mode = str(raw.get("mode", "append"))
        if mode not in {"append", "replace", "upsert"}:
            raise ConfigError("target.mode must be append, replace, or upsert")
        return cls(source.kind, source.path, dataset, cast(WriteMode, mode))

    def as_dict(self) -> dict[str, Any]:
        data = super(TargetConfig, self).as_dict()
        data["mode"] = self.mode
        return data


@dataclass(frozen=True, slots=True)
class MappingRule:
    target: str
    source: str | None = None
    value: object | None = None
    has_value: bool = False
    transforms: tuple[str, ...] = ()
    type: ColumnType = ColumnType.TEXT
    required: bool = False
    primary_key: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MappingRule:
        if not isinstance(raw, dict):
            raise ConfigError("Each mapping rule must be an object")
        source = raw.get("source")
        has_value = "value" in raw
        if source is None and not has_value:
            raise ConfigError("A mapping rule needs either source or value")
        if source is not None and has_value:
            raise ConfigError("A mapping rule cannot have both source and value")
        transforms = raw.get("transforms", [])
        if isinstance(transforms, str):
            transforms = [transforms]
        if not isinstance(transforms, list) or not all(
            isinstance(item, str) for item in transforms
        ):
            raise ConfigError("mapping.transforms must be a list of names")
        try:
            column_type = ColumnType(str(raw.get("type", "text")).lower())
        except ValueError as error:
            options = ", ".join(item.value for item in ColumnType)
            raise ConfigError(f"Unknown mapping type. Choose one of: {options}") from error
        return cls(
            target=str(_required(raw, "target")),
            source=str(source) if source is not None else None,
            value=raw.get("value"),
            has_value=has_value,
            transforms=tuple(transforms),
            type=column_type,
            required=bool(raw.get("required", False)),
            primary_key=bool(raw.get("primary_key", False)),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"target": self.target}
        if self.source is not None:
            data["source"] = self.source
        if self.has_value:
            data["value"] = self.value
        if self.transforms:
            data["transforms"] = list(self.transforms)
        if self.type != ColumnType.TEXT:
            data["type"] = self.type.value
        if self.required:
            data["required"] = True
        if self.primary_key:
            data["primary_key"] = True
        return data


@dataclass(frozen=True, slots=True)
class MigrationOptions:
    batch_size: int = 1_000
    on_error: ErrorPolicy = "stop"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> MigrationOptions:
        raw = raw or {}
        if not isinstance(raw, dict):
            raise ConfigError("options must be an object")
        batch_size = raw.get("batch_size", 1_000)
        if not isinstance(batch_size, int) or batch_size < 1:
            raise ConfigError("options.batch_size must be a positive integer")
        policy = str(raw.get("on_error", "stop"))
        if policy not in {"stop", "report_and_skip"}:
            raise ConfigError("options.on_error must be stop or report_and_skip")
        return cls(batch_size=batch_size, on_error=policy)  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, Any]:
        return {"batch_size": self.batch_size, "on_error": self.on_error}


@dataclass(frozen=True, slots=True)
class MigrationConfig:
    name: str
    source: SourceConfig
    target: TargetConfig
    mapping: tuple[MappingRule, ...]
    options: MigrationOptions = field(default_factory=MigrationOptions)
    version: int = 1

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MigrationConfig:
        if not isinstance(raw, dict):
            raise ConfigError("Configuration root must be an object")
        if raw.get("version", 1) != 1:
            raise ConfigError("Only configuration version 1 is supported")
        mapping_raw = raw.get("mapping")
        if not isinstance(mapping_raw, list) or not mapping_raw:
            raise ConfigError("mapping must contain at least one rule")
        rules = tuple(MappingRule.from_dict(item) for item in mapping_raw)
        targets = [rule.target for rule in rules]
        if len(targets) != len(set(targets)):
            raise ConfigError("Each target column can only be mapped once")
        return cls(
            name=str(_required(raw, "name")),
            source=SourceConfig.from_dict(raw.get("source"), section="source"),
            target=TargetConfig.from_target_dict(raw.get("target")),
            mapping=rules,
            options=MigrationOptions.from_dict(raw.get("options")),
            version=1,
        )

    @property
    def target_schema(self) -> TableSchema:
        return TableSchema(
            self.target.dataset or "target",
            tuple(
                ColumnSchema(
                    rule.target,
                    rule.type,
                    not (rule.required or rule.primary_key),
                    rule.primary_key,
                )
                for rule in self.mapping
            ),
        )

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(rule.target for rule in self.mapping if rule.primary_key)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "source": self.source.as_dict(),
            "target": self.target.as_dict(),
            "mapping": [rule.as_dict() for rule in self.mapping],
            "options": self.options.as_dict(),
        }
