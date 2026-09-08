"""Small, dependency-free schema inference helpers."""

from __future__ import annotations

from collections.abc import Iterable

from migrable.core.schema import ColumnSchema, ColumnType, TableSchema


def infer_type(values: Iterable[object]) -> ColumnType:
    seen: set[ColumnType] = set()
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            seen.add(ColumnType.BOOLEAN)
        elif isinstance(value, int):
            seen.add(ColumnType.INTEGER)
        elif isinstance(value, float):
            seen.add(ColumnType.REAL)
        else:
            text = str(value).strip()
            try:
                int(text)
                seen.add(ColumnType.INTEGER)
            except ValueError:
                try:
                    float(text)
                    seen.add(ColumnType.REAL)
                except ValueError:
                    return ColumnType.TEXT
    if not seen:
        return ColumnType.TEXT
    if ColumnType.TEXT in seen:
        return ColumnType.TEXT
    if ColumnType.REAL in seen:
        return ColumnType.REAL
    if ColumnType.INTEGER in seen and ColumnType.BOOLEAN in seen:
        return ColumnType.INTEGER
    return next(iter(seen))


def schema_from_rows(
    name: str, headers: list[str], rows: Iterable[dict[str, object]]
) -> TableSchema:
    sampled = list(rows)
    return TableSchema(
        name,
        tuple(
            ColumnSchema(header, infer_type(row.get(header) for row in sampled))
            for header in headers
        ),
    )
