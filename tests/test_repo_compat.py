from pathlib import Path
import configparser
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepoCompatibilityTests(unittest.TestCase):
    def test_commands_use_legacy_builtin_protocol(self):
        cfg = configparser.ConfigParser()
        cfg.read(ROOT / "default" / "commands.conf")
        for command in ("getanswer", "gethints", "validateevents"):
            self.assertEqual(cfg[command]["chunked"].lower(), "false")
            self.assertEqual(cfg[command]["python.required"].replace(" ", ""), "3.9,3.13")

    def test_controller_drops_old_dependencies(self):
        text = (ROOT / "appserver" / "controllers" / "scoreboard_controller.py").read_text()
        self.assertNotIn("import httplib2", text)
        self.assertNotIn("import splunklib", text)
        self.assertNotIn("urllib.parse.quote(v.encode", text)

    def test_validate_macro_actually_validates(self):
        text = (ROOT / "default" / "macros.conf").read_text()
        self.assertIn('definition = | validateevents | search Validated="1"', text)
        self.assertNotIn('definition = | eval Validated="1"', text)

    def test_xml_patcher_adds_version_1_1(self):
        spec = importlib.util.spec_from_file_location("builder", ROOT / "tools" / "build_from_upstream.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            views = root / "default" / "data" / "ui" / "views"
            views.mkdir(parents=True)
            (views / "a.xml").write_text('<dashboard theme="dark"><label>x</label></dashboard>')
            (views / "b.xml").write_text('<form><label>y</label></form>')
            self.assertEqual(builder.patch_xml(root), 2)
            self.assertIn('version="1.1"', (views / "a.xml").read_text())
            self.assertIn('version="1.1"', (views / "b.xml").read_text())


if __name__ == "__main__":
    unittest.main()
