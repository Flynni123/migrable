"""YAML persistence for repeatable migration definitions."""

from __future__ import annotations

from pathlib import Path

from migrable.core.models import ConfigError, MigrationConfig


def _yaml():
    try:
        import yaml
    except ImportError as error:  # pragma: no cover - dependency problem
        raise RuntimeError("PyYAML is required. Install migrable's dependencies first.") from error
    return yaml


def load_config(path: str | Path) -> MigrationConfig:
    config_path = Path(path)
    try:
        raw = _yaml().safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ConfigError(f"Could not read {config_path}: {error}") from error
    except Exception as error:
        raise ConfigError(f"Could not parse {config_path}: {error}") from error
    config = MigrationConfig.from_dict(raw)
    return resolve_relative_paths(config, config_path.parent)


def save_config(config: MigrationConfig, path: str | Path) -> None:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        _yaml().safe_dump(config.as_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def resolve_relative_paths(config: MigrationConfig, directory: Path) -> MigrationConfig:
    """Make data paths deterministic relative to their YAML file."""
    source_path = config.source.path
    target_path = config.target.path
    source = config.source
    target = config.target
    if not source_path.is_absolute():
        source = type(source)(source.kind, directory / source_path, source.dataset)
    if not target_path.is_absolute():
        target = type(target)(target.kind, directory / target_path, target.dataset, target.mode)
    return MigrationConfig(
        config.name, source, target, config.mapping, config.options, config.version
    )
