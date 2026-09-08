"""Apply declarative column mappings without evaluating arbitrary code."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from migrable.core.models import MappingRule
from migrable.core.schema import ColumnType


class MappingError(ValueError):
    def __init__(self, column: str, message: str) -> None:
        super().__init__(f"{column}: {message}")
        self.column = column


def _empty(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "ja"}:
            return True
        if normalized in {"false", "0", "no", "n", "nein"}:
            return False
    raise ValueError("expected a boolean value")


def _parse_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value).strip()).isoformat()


def _parse_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).isoformat()


TRANSFORMS: dict[str, Callable[[object], object]] = {
    "trim": lambda value: str(value).strip(),
    "lowercase": lambda value: str(value).lower(),
    "uppercase": lambda value: str(value).upper(),
    "integer": lambda value: int(str(value).strip()),
    "real": lambda value: float(str(value).strip()),
    "decimal": lambda value: str(Decimal(str(value).strip())),
    "boolean": _as_bool,
    "date": _parse_date,
    "datetime": _parse_datetime,
    "json": lambda value: (
        json.dumps(value, ensure_ascii=False)
        if not isinstance(value, str)
        else json.dumps(json.loads(value), ensure_ascii=False)
    ),
}


def cast(value: object, type_: ColumnType) -> object:
    if _empty(value):
        return None
    try:
        if type_ == ColumnType.TEXT:
            return str(value)
        if type_ == ColumnType.INTEGER:
            return int(str(value).strip())
        if type_ == ColumnType.REAL:
            return float(str(value).strip())
        if type_ == ColumnType.DECIMAL:
            return str(Decimal(str(value).strip()))
        if type_ == ColumnType.BOOLEAN:
            return int(_as_bool(value))
        if type_ == ColumnType.DATE:
            return _parse_date(value)
        if type_ == ColumnType.DATETIME:
            return _parse_datetime(value)
        if type_ == ColumnType.JSON:
            return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except (TypeError, ValueError, InvalidOperation) as error:
        raise ValueError(f"cannot convert {value!r} to {type_.value}") from error
    raise AssertionError(f"Unhandled column type: {type_}")


class RowMapper:
    def __init__(self, rules: tuple[MappingRule, ...]) -> None:
        self.rules = rules
        self._transforms: tuple[tuple[Callable[[object], object], ...], ...] = tuple(
            self._compile_transforms(rule) for rule in rules
        )

    @staticmethod
    def _compile_transforms(rule: MappingRule) -> tuple[Callable[[object], object], ...]:
        try:
            return tuple(TRANSFORMS[name] for name in rule.transforms)
        except KeyError as error:
            raise MappingError(rule.target, f"unknown transform '{error.args[0]}'") from error

    def map_row(self, row: dict[str, object]) -> dict[str, object]:
        mapped: dict[str, object] = {}
        for rule, transforms in zip(self.rules, self._transforms, strict=True):
            value = rule.value if rule.has_value else row.get(rule.source or "")
            try:
                for transform in transforms:
                    if not _empty(value):
                        value = transform(value)
                value = cast(value, rule.type)
            except (TypeError, ValueError, InvalidOperation) as error:
                raise MappingError(rule.target, str(error)) from error
            if rule.required or rule.primary_key:
                if value is None:
                    raise MappingError(rule.target, "value is required")
            mapped[rule.target] = value
        return mapped
