import contextlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

watchdog_module = types.ModuleType("watchdog")
watchdog_events_module = types.ModuleType("watchdog.events")


class _FileSystemEventHandler:
    pass


watchdog_events_module.FileSystemEventHandler = _FileSystemEventHandler
watchdog_module.events = watchdog_events_module
sys.modules.setdefault("watchdog", watchdog_module)
sys.modules.setdefault("watchdog.events", watchdog_events_module)

yaml_module = types.ModuleType("yaml")
yaml_module.safe_load = lambda text: {}
sys.modules.setdefault("yaml", yaml_module)

from minutemaker import pipeline


DEFAULT_TEMPLATE_CONFIG = {
    "mandatory_sections": [
        {"name": "Welcome & Attendance"},
        {"name": "Updates"},
        {"name": "Discussion Items"},
        {"name": "Action Items"},
        {"name": "Any Other Business"},
        {"name": "Next Meeting"},
    ],
    "optional_sections": [],
}


def _direct_latex_document(body_item: str) -> str:
    return f"""```latex
\\documentclass[11pt]{{article}}
\\input{{header/title_code.tex}}
\\def\\todaydate{{15/04/2026}}
\\def\\chair{{Check Meeting Schedule}}
\\def\\secretary{{Check Meeting Schedule}}
\\begin{{document}}
\\makeminutestitle
\\section{{Welcome \\& Attendance}}
\\begin{{itemize}}
    \\item Welcome was noted.
\\end{{itemize}}
\\section{{Updates}}
\\begin{{itemize}}
    \\item Updates were provided.
\\end{{itemize}}
\\section{{Discussion Items}}
\\begin{{itemize}}
    \\item {body_item}
\\end{{itemize}}
\\section{{Action Items}}
\\begin{{itemize}}
    \\item Action owners were confirmed.
\\end{{itemize}}
\\section{{Any Other Business}}
\\begin{{itemize}}
    \\item Nothing to report.
\\end{{itemize}}
\\section{{Next Meeting}}
\\begin{{itemize}}
    \\item Date: 22/04/2026
    \\item Chair: Check Meeting Schedule
    \\item Secretary: Check Meeting Schedule
\\end{{itemize}}
\\end{{document}}
```"""


class ProcessFileRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompts = {"json": "json prompt", "latex": "latex prompt"}

    def test_process_file_anthropic_uses_direct_latex_route(self) -> None:
        config = {
            "provider": "anthropic",
            "output_dir": "/tmp/output",
            "template_dir": "/tmp/templates/liverpool",
        }
        provider = Mock()
        provider.generate.return_value = _direct_latex_document(
            r"Research \& development updates were shared."
        )

        with (
            patch("minutemaker.pipeline.read_input", return_value="raw notes"),
            patch("minutemaker.pipeline.get_provider", return_value=provider),
            patch("minutemaker.pipeline.ServerManager", side_effect=lambda cfg: contextlib.nullcontext()),
            patch("minutemaker.pipeline.parse_and_validate") as parse_and_validate,
            patch("minutemaker.pipeline.verify_completeness") as verify_completeness,
            patch("minutemaker.pipeline.polish_items") as polish_items,
            patch("minutemaker.pipeline.render_latex") as render_latex,
            patch(
                "minutemaker.pipeline.create_output_bundle",
                return_value=("/tmp/output/minutes_2026_04_15", "minutes_2026_04_15"),
            ) as create_output_bundle,
            patch(
                "minutemaker.pipeline.write_tex",
                return_value="/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex",
            ) as write_tex,
            patch("minutemaker.pipeline.compile_pdf", return_value=True) as compile_pdf,
            patch("minutemaker.pipeline.cleanup_aux_files") as cleanup_aux_files,
        ):
            pipeline.process_file(
                "input/testing_minutes.txt",
                config,
                DEFAULT_TEMPLATE_CONFIG,
                self.prompts,
            )

        provider.generate.assert_called_once_with("latex prompt", unittest.mock.ANY, config)
        parse_and_validate.assert_not_called()
        verify_completeness.assert_not_called()
        polish_items.assert_not_called()
        render_latex.assert_not_called()
        create_output_bundle.assert_called_once_with("/tmp/output", config["template_dir"], "2026_04_15")
        write_tex.assert_called_once()
        rendered_tex = write_tex.call_args.args[0]
        self.assertNotIn("```", rendered_tex)
        self.assertIn("% Generated with MinuteMaker on ", rendered_tex)
        self.assertIn(r"Research \& development updates were shared.", rendered_tex)
        self.assertEqual(write_tex.call_args.args[2], "2026_04_15")
        compile_pdf.assert_called_once_with(
            "/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex",
            "/tmp/output/minutes_2026_04_15",
        )
        cleanup_aux_files.assert_called_once_with(
            "/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex"
        )

    def test_process_file_anthropic_accepts_latex_escapes_without_json_parsing(self) -> None:
        config = {
            "provider": "anthropic",
            "output_dir": "/tmp/output",
            "template_dir": "/tmp/templates/liverpool",
        }
        provider = Mock()
        provider.generate.return_value = _direct_latex_document(
            r"\href{https://example.com}{Example resource} supported Research \& Development."
        )

        with (
            patch("minutemaker.pipeline.read_input", return_value="raw notes"),
            patch("minutemaker.pipeline.get_provider", return_value=provider),
            patch("minutemaker.pipeline.ServerManager", side_effect=lambda cfg: contextlib.nullcontext()),
            patch(
                "minutemaker.pipeline.parse_and_validate",
                side_effect=AssertionError("Anthropic route should not parse JSON"),
            ),
            patch(
                "minutemaker.pipeline.create_output_bundle",
                return_value=("/tmp/output/minutes_2026_04_15", "minutes_2026_04_15"),
            ),
            patch(
                "minutemaker.pipeline.write_tex",
                return_value="/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex",
            ) as write_tex,
            patch("minutemaker.pipeline.compile_pdf", return_value=True),
            patch("minutemaker.pipeline.cleanup_aux_files"),
        ):
            pipeline.process_file(
                "input/testing_minutes.txt",
                config,
                DEFAULT_TEMPLATE_CONFIG,
                self.prompts,
            )

        rendered_tex = write_tex.call_args.args[0]
        self.assertIn(r"\href{https://example.com}{Example resource}", rendered_tex)
        self.assertIn(r"Research \& Development.", rendered_tex)

    def test_process_file_openai_compatible_keeps_json_pipeline_order(self) -> None:
        config = {
            "provider": "openai_compatible",
            "output_dir": "/tmp/output",
            "template_dir": "/tmp/templates/default",
        }
        provider = Mock()
        provider.generate.return_value = '{"meeting_date":"15/04/2026","chair":"A","secretary":"B","sections":[]}'
        parsed = {
            "meeting_date": "15/04/2026",
            "chair": "A",
            "secretary": "B",
            "sections": [],
        }
        verified = dict(parsed)
        polished = dict(parsed)
        calls = []

        def record_parse(raw_response: str) -> dict:
            calls.append("parse")
            self.assertEqual(raw_response, provider.generate.return_value)
            return parsed

        def record_verify(data: dict, raw_text: str, provider_arg, config_arg: dict, template_config_arg: dict) -> dict:
            calls.append("verify")
            self.assertIs(data, parsed)
            self.assertEqual(raw_text, "raw notes")
            self.assertIs(provider_arg, provider)
            self.assertIs(config_arg, config)
            self.assertIs(template_config_arg, DEFAULT_TEMPLATE_CONFIG)
            return verified

        def record_polish(data: dict, provider_arg, config_arg: dict, prompt_rules: str) -> dict:
            calls.append("polish")
            self.assertIs(data, verified)
            self.assertIs(provider_arg, provider)
            self.assertIs(config_arg, config)
            self.assertEqual(prompt_rules, "prompt rules")
            return polished

        def record_render(data: dict, template_config_arg: dict) -> str:
            calls.append("render")
            self.assertIs(data, polished)
            self.assertIs(template_config_arg, DEFAULT_TEMPLATE_CONFIG)
            return "\\documentclass[11pt]{article}"

        with (
            patch("minutemaker.pipeline.read_input", return_value="raw notes"),
            patch("minutemaker.pipeline.get_provider", return_value=provider),
            patch("minutemaker.pipeline.ServerManager", side_effect=lambda cfg: contextlib.nullcontext()),
            patch("minutemaker.pipeline.load_prompt_rules", return_value="prompt rules"),
            patch("minutemaker.pipeline.parse_and_validate", side_effect=record_parse),
            patch("minutemaker.pipeline.verify_completeness", side_effect=record_verify),
            patch("minutemaker.pipeline.polish_items", side_effect=record_polish),
            patch("minutemaker.pipeline.render_latex", side_effect=record_render),
            patch(
                "minutemaker.pipeline.create_output_bundle",
                return_value=("/tmp/output/minutes_2026_04_15", "minutes_2026_04_15"),
            ) as create_output_bundle,
            patch(
                "minutemaker.pipeline.write_tex",
                return_value="/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex",
            ) as write_tex,
            patch("minutemaker.pipeline.compile_pdf", return_value=True) as compile_pdf,
            patch("minutemaker.pipeline.cleanup_aux_files") as cleanup_aux_files,
        ):
            pipeline.process_file(
                "input/testing_minutes.txt",
                config,
                DEFAULT_TEMPLATE_CONFIG,
                self.prompts,
            )

        provider.generate.assert_called_once_with("json prompt", unittest.mock.ANY, config)
        self.assertEqual(calls, ["parse", "verify", "polish", "render"])
        create_output_bundle.assert_called_once_with("/tmp/output", config["template_dir"], "2026_04_15")
        self.assertEqual(write_tex.call_args.args[0], "\\documentclass[11pt]{article}")
        self.assertEqual(write_tex.call_args.args[2], "2026_04_15")
        compile_pdf.assert_called_once_with(
            "/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex",
            "/tmp/output/minutes_2026_04_15",
        )
        cleanup_aux_files.assert_called_once_with(
            "/tmp/output/minutes_2026_04_15/minutes_2026_04_15.tex"
        )

    def test_create_output_bundle_copies_header_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            template_dir = root / "templates" / "demo"
            header_dir = template_dir / "header"
            header_dir.mkdir(parents=True)
            (header_dir / "title_code.tex").write_text("\\newcommand{\\makeminutestitle}{}", encoding="utf-8")
            (header_dir / "logo.png").write_text("png", encoding="utf-8")

            bundle_dir, bundle_name = pipeline.create_output_bundle(
                str(output_dir),
                str(template_dir),
                "2026_04_15",
            )

            self.assertEqual(bundle_name, "minutes_2026_04_15")
            self.assertEqual(Path(bundle_dir), output_dir / "minutes_2026_04_15")
            self.assertTrue((Path(bundle_dir) / "header" / "title_code.tex").is_file())
            self.assertTrue((Path(bundle_dir) / "header" / "logo.png").is_file())


if __name__ == "__main__":
    unittest.main()
