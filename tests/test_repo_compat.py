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
        for command in ("getanswer", "gethints"):
            self.assertEqual(cfg[command]["enableheader"].lower(), "true")
            self.assertEqual(cfg[command]["passauth"].lower(), "true")

    def test_controller_drops_old_dependencies(self):
        text = (ROOT / "appserver" / "controllers" / "scoreboard_controller.py").read_text()
        self.assertNotIn("import httplib2", text)
        self.assertNotIn("import splunklib", text)
        self.assertNotIn("urllib.parse.quote(v.encode", text)

    def test_validate_macro_actually_validates(self):
        text = (ROOT / "default" / "macros.conf").read_text()
        self.assertIn('definition = | validateevents | search Validated="1"', text)
        self.assertNotIn('definition = | eval Validated="1"', text)

    def test_questions_are_read_from_admin_app(self):
        text = (ROOT / "appserver/controllers/scoreboard_controller.py").read_text()
        self.assertIn('ADMIN_APP = "SA-ctf_scoreboard_admin"', text)
        self.assertNotIn('_kv("ctf_questions", caller_key)', text)
        self.assertNotIn('_kv("ctf_questions", session_key)', text)
        self.assertGreaterEqual(text.count('_kv("ctf_questions", privileged, app=ADMIN_APP)'), 3)
        self.assertIn('_kv("ctf_questions", session_key, app=ADMIN_APP)', text)

    def test_scoreboard_does_not_own_questions_collection(self):
        collections = (ROOT / "default/collections.conf").read_text()
        transforms = (ROOT / "default/transforms.conf").read_text()
        self.assertNotIn("[ctf_questions]", collections)
        self.assertNotIn("[ctf_questions]", transforms)
        self.assertNotIn("[ctf_events]", collections)
        self.assertNotIn("[ctf_registrations]", collections)

    def test_participant_owned_collections_survive_overlay_builds(self):
        collections = (ROOT / "default/collections.conf").read_text()
        transforms = (ROOT / "default/transforms.conf").read_text()
        for name in (
            "ctf_hint_entitlements",
            "ctf_badges",
            "ctf_badge_entitlements",
            "ctf_stealth",
            "ctf_eulas",
            "ctf_eulas_accepted",
        ):
            self.assertIn(f"[{name}]", collections)
            self.assertIn(f"[{name}]", transforms)


    def test_question_views_use_card_modal_layout(self):
        questions = (ROOT / "default/data/ui/views/questions.xml").read_text()
        question = (ROOT / "default/data/ui/views/question.xml").read_text()
        self.assertNotIn("custom_table_row_expansion.js", questions)
        self.assertNotIn("custom_table_row_expansion.js", question)
        self.assertIn('challenge_grid.js', questions)
        self.assertIn('id="challengeData"', questions)
        self.assertIn('<refresh>5s</refresh>', questions)
        self.assertIn('id="ctf_challenge_sections"', questions)
        self.assertIn('id="ctf_challenge_modal"', questions)
        self.assertNotIn('<table id="table1">', questions)
        self.assertIn('stylesheet="questions.css,table_decorations.css"', questions)
        self.assertIn('stylesheet="questions.css,table_decorations.css"', question)

    def test_user_info_macros_do_not_require_retired_ctf_users_lookup(self):
        macros = (ROOT / "default/macros.conf").read_text()
        self.assertNotIn("lookup ctf_users", macros)
        self.assertIn("coalesce(DisplayUsername, Username, user)", macros)

    def test_questions_stylesheet_is_tracked_by_overlay(self):
        css = ROOT / "appserver/static/questions.css"
        self.assertTrue(css.exists())
        text = css.read_text()
        self.assertIn(".ctf-challenge-grid", text)
        self.assertIn(".ctf-challenge-card.is-solved", text)
        self.assertIn(".ctf-modal", text)
        self.assertIn("#ctf_progress_row", text)

    def test_challenge_grid_supports_live_team_updates_and_inline_actions(self):
        js_path = ROOT / "appserver/static/challenge_grid.js"
        self.assertTrue(js_path.exists())
        js = js_path.read_text()
        self.assertIn('mvc.Components.get("challengeData")', js)
        self.assertIn('A teammate solved', js)
        self.assertIn('scoreboard_controller/submit_question', js)
        self.assertIn('scoreboard_controller/purchase_hint', js)
        self.assertIn('ajax: "1"', js)

    def test_controller_supports_ajax_question_and_hint_actions(self):
        text = (ROOT / "appserver/controllers/scoreboard_controller.py").read_text()
        self.assertIn("def _wants_json", text)
        self.assertIn("def _json_response", text)
        self.assertGreaterEqual(text.count("if wants_json:"), 2)
        self.assertIn('"result": str(participant.get("Result", ""))', text)
        self.assertIn('"hint": str(hint.get("Hint", ""))', text)


    def test_event_image_is_bound_from_registration_context(self):
        js = (ROOT / "appserver/static/ctf_event_context.js").read_text()
        self.assertIn('function setEventImage', js)
        self.assertIn('selected.image_url', js)
        self.assertIn('/static/app/SA-ctf_scoreboard/ctflogo.png', js)
        self.assertIn('$("#ctflogo")', js)

    def test_modal_hints_use_json_controller_endpoint(self):
        js = (ROOT / "appserver/static/challenge_grid.js").read_text()
        controller = (ROOT / "appserver/controllers/scoreboard_controller.py").read_text()
        self.assertIn('scoreboard_controller/challenge_hints', js)
        self.assertNotIn('new SearchManager', js)
        self.assertIn('def challenge_hints', controller)
        self.assertIn('"hints": rows', controller)

    def test_ajax_actions_return_json_errors_and_allow_no_eula_configuration(self):
        controller = (ROOT / "appserver/controllers/scoreboard_controller.py").read_text()
        self.assertIn('def _json_error', controller)
        self.assertIn('def _submission_eula_fields', controller)
        self.assertIn('if not defaults:', controller)
        self.assertGreaterEqual(controller.count('if wants_json:'), 8)

    def test_simplexml_ids_are_valid_identifiers(self):
        import re
        import xml.etree.ElementTree as ET

        for rel in (
            "default/data/ui/views/questions.xml",
            "default/data/ui/views/question.xml",
        ):
            root = ET.parse(ROOT / rel).getroot()
            for elem in root.iter():
                if elem.tag in {"row", "panel", "table", "search", "chart", "single", "event", "map", "input"}:
                    identifier = elem.attrib.get("id")
                    if identifier is not None:
                        self.assertRegex(
                            identifier,
                            r"^[A-Za-z_][A-Za-z0-9_]*$",
                            msg=f"Invalid Simple XML id {identifier!r} in {rel}",
                        )

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
