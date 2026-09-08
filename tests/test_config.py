from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from migrable.core.config import load_config, save_config
from migrable.core.models import MappingRule, MigrationConfig, SourceConfig, TargetConfig
from migrable.core.schema import ColumnType


@unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is an application dependency")
class ConfigTests(unittest.TestCase):
    def test_yaml_round_trip_resolves_paths_relative_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config" / "migration.yml"
            config = MigrationConfig(
                name="demo",
                source=SourceConfig("csv", Path("input.csv")),
                target=TargetConfig("sqlite", Path("database.db"), "target", "replace"),
                mapping=(MappingRule("id", source="Identifier", type=ColumnType.INTEGER),),
            )
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded.source.path, path.parent / "input.csv")
            self.assertEqual(loaded.target.path, path.parent / "database.db")
            self.assertEqual(loaded.mapping[0].type, ColumnType.INTEGER)
