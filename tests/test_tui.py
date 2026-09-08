from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec("textual"), "Textual is an application dependency")
class TuiTests(unittest.TestCase):
    def test_analyze_and_suggest_mapping(self) -> None:
        from migrable.tui.app import MigrationApp

        async def exercise() -> None:
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "people.csv"
                path.write_text("ID,Full Name\n1,Ada\n", encoding="utf-8")
                app = MigrationApp()
                async with app.run_test() as pilot:
                    app.query_one("#source-path").value = str(path)
                    app._analyze()
                    app._suggest_mapping()
                    self.assertEqual([rule.target for rule in app.rules], ["id", "full_name"])
                    self.assertEqual(len(app.query_one("#mapping-table").columns), 6)
                    await pilot.pause()

        asyncio.run(exercise())
