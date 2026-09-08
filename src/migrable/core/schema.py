"""Neutral schema types shared by all data sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ColumnType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    REAL = "real"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    JSON = "json"

    @property
    def sqlite_type(self) -> str:
        return {
            ColumnType.TEXT: "TEXT",
            ColumnType.INTEGER: "INTEGER",
            ColumnType.REAL: "REAL",
            ColumnType.DECIMAL: "NUMERIC",
            ColumnType.BOOLEAN: "INTEGER",
            ColumnType.DATE: "TEXT",
            ColumnType.DATETIME: "TEXT",
            ColumnType.JSON: "TEXT",
        }[self]

    @classmethod
    def from_value(cls, value: object) -> ColumnType:
        if isinstance(value, bool):
            return cls.BOOLEAN
        if isinstance(value, int):
            return cls.INTEGER
        if isinstance(value, float):
            return cls.REAL
        return cls.TEXT


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    type: ColumnType = ColumnType.TEXT
    nullable: bool = True
    primary_key: bool = False


@dataclass(frozen=True, slots=True)
class TableSchema:
    name: str
    columns: tuple[ColumnSchema, ...] = field(default_factory=tuple)

    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def get(self, name: str) -> ColumnSchema | None:
        return next((column for column in self.columns if column.name == name), None)
