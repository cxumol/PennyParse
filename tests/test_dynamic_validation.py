from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DEMO_ASSETS = REPO_ROOT / "demo_assets"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
CHAT_ENV_KEYS = (
    "PENNYPARSE_CHAT_BASE",
    "PENNYPARSE_CHAT_AUTHKEY",
    "PENNYPARSE_CHAT_MODEL",
    "OPENAI_API_KEY",
)

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pennyparse.cmd import init_docs, tool as tool_cmd  # noqa: E402
from pennyparse.agent import parser as parser_agent  # noqa: E402
from pennyparse.agent import reviewer as reviewer_agent  # noqa: E402


def _discover_demo_asset(suffixes: set[str]) -> Path:
    for path in sorted(DEMO_ASSETS.iterdir()):
        if path.is_file() and path.suffix.lower() in suffixes:
            return path
    suffix_list = ", ".join(sorted(suffixes))
    raise AssertionError(f"no demo asset found for suffixes: {suffix_list}")


def _write_fake_user_toolbox(home: Path) -> None:
    toolbox = home / ".pennyparse" / "user_toolbox.py"
    toolbox.parent.mkdir(parents=True, exist_ok=True)
    toolbox.write_text(
        "\n".join(
            [
                "TOOL_SPECS = [",
                "    {",
                "        'name': 'fake_tool',",
                "        'scope': 'parser',",
                "        'cost': 'very low',",
                "        'desc': 'Fake test tool.',",
                "        'flags': {'path': '/path/to/file'},",
                "    },",
                "]",
                "UNAVAILABLE_TOOLS = {}",
                "",
                "def tool_fake_tool(argv):",
                "    path = argv[argv.index('--path') + 1]",
                "    with open(path, encoding='utf-8') as handle:",
                "        return handle.read()",
                "",
                "TOOL_HANDLERS = {'fake_tool': tool_fake_tool}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_fake_settings(home: Path) -> None:
    settings = home / ".pennyparse" / "pennyparse.settings.toml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        "\n".join(
            [
                "[aigc.api.chatcomp]",
                'model = "unit-test-model"',
                "",
                "[init.sampling]",
                'by = "none"',
                "num = 0",
                "",
            ]
        ),
        encoding="utf-8",
    )


class BuiltinMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf_asset = _discover_demo_asset({".pdf"})
        cls.image_asset = _discover_demo_asset(IMAGE_SUFFIXES)

    def test_img_metadata_px_reads_discovered_image(self) -> None:
        result = tool_cmd.img_metadata_px(["--path", str(self.image_asset)])

        self.assertGreater(result["width"], 0)
        self.assertGreater(result["height"], 0)

    def test_pdf_metadata_reads_discovered_pdf(self) -> None:
        if importlib.util.find_spec("pymupdf") is None:
            self.skipTest("pymupdf is not installed")

        result = tool_cmd.pdf_metadata(["--path", str(self.pdf_asset)])

        self.assertGreaterEqual(result["page_count"], 1)
        self.assertIsInstance(result["word_count"], int)
        self.assertIsInstance(result["toc"], list)


class InitDocsTests(unittest.TestCase):
    def test_run_init_docs_writes_memory_from_fake_cwd_and_home(self) -> None:
        pdf_asset = _discover_demo_asset({".pdf"})
        image_asset = _discover_demo_asset(IMAGE_SUFFIXES)

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            fixtures = cwd / "fixtures"
            fixtures.mkdir()
            copied_pdf = Path(shutil.copy2(pdf_asset, fixtures / pdf_asset.name))
            copied_image = Path(shutil.copy2(image_asset, fixtures / image_asset.name))
            (cwd / "pennyparse.log").write_text("runtime log\n", encoding="utf-8")

            _write_fake_user_toolbox(home)
            _write_fake_settings(home)
            module, module_error = tool_cmd.load_user_toolbox_module(
                module_path=home / ".pennyparse" / "user_toolbox.py"
            )
            self.assertIsNone(module_error)
            self.assertIsNotNone(module)

            env_without_chat = {key: "" for key in CHAT_ENV_KEYS}
            with (
                mock.patch.dict(os.environ, env_without_chat),
                mock.patch("pennyparse.cmd.init_docs._group_with_llm", return_value=None),
            ):
                summary = init_docs.run_init_docs(overwrite=False, cwd=cwd, home=home)

            result_file = cwd / ".pennyparse_memory.txt"
            memory = result_file.read_text(encoding="utf-8")
            rel_pdf = copied_pdf.relative_to(cwd).as_posix()
            rel_image = copied_image.relative_to(cwd).as_posix()

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["result_file"], str(result_file))
            self.assertRaises(json.JSONDecodeError, json.loads, memory)
            self.assertIn("Overall, this folder has", memory)
            self.assertIn("start from", memory)
            self.assertIn(rel_pdf, memory)
            self.assertIn(rel_image, memory)
            self.assertNotIn("pennyparse.log", memory)

            if importlib.util.find_spec("pymupdf") is not None:
                self.assertIn("pdf", memory.lower())


class ReviewerTests(unittest.TestCase):
    def test_reviewer_rejects_empty_text_without_chat_model(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                outcome = reviewer_agent.review_text("", cwd=Path(cwd_raw), home=Path(home_raw))

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, "major_revision")

    def test_reviewer_accepts_non_empty_text_without_chat_model(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                outcome = reviewer_agent.review_text("usable text", cwd=Path(cwd_raw), home=Path(home_raw))

        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, "pass")

    def test_reviewer_pass_preserves_full_text_after_truncated_audit(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            (cwd / "pennyparse.settings.toml").write_text(
                "[reviewer]\nmax_length = 5\n",
                encoding="utf-8",
            )
            seen: list[str] = []

            class FakeChatClient:
                def __init__(self, **kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    pass

                def complete(self, session, **kwargs):
                    seen.append(json.loads(session.messages[-1]["content"])["text"])
                    return {
                        "content": json.dumps(
                            {"status": "pass", "message": "ok", "patches": []}
                        )
                    }

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.reviewer.ChatClient", FakeChatClient),
            ):
                outcome = reviewer_agent.review_text(
                    "abcdeFULL_SUFFIX",
                    cwd=cwd,
                    home=Path(home_raw),
                )

        self.assertEqual(seen, ["abcde"])
        self.assertEqual(outcome.status, "pass")
        self.assertEqual(outcome.text, "abcdeFULL_SUFFIX")

    def test_reviewer_minor_revision_applies_patch_to_full_text(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            (cwd / "pennyparse.settings.toml").write_text(
                "[reviewer]\nmax_length = 8\n",
                encoding="utf-8",
            )

            class FakeChatClient:
                def __init__(self, **kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    pass

                def complete(self, session, **kwargs):
                    return {
                        "content": json.dumps(
                            {
                                "status": "minor_revision",
                                "message": "fixed typo",
                                "patches": [
                                    {
                                        "pattern": "teh",
                                        "repl": "the",
                                        "count": 1,
                                    }
                                ],
                            }
                        )
                    }

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.reviewer.ChatClient", FakeChatClient),
            ):
                outcome = reviewer_agent.review_text(
                    "teh head\nbody beyond audit limit\n",
                    cwd=cwd,
                    home=Path(home_raw),
                )

        self.assertEqual(outcome.status, "minor_revision")
        self.assertEqual(outcome.text, "the head\nbody beyond audit limit\n")

    def test_reviewer_minor_revision_without_patch_is_major_revision(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            class FakeChatClient:
                def __init__(self, **kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    pass

                def complete(self, session, **kwargs):
                    return {
                        "content": json.dumps(
                            {"status": "minor_revision", "message": "", "text": "trimmed"}
                        )
                    }

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.reviewer.ChatClient", FakeChatClient),
            ):
                outcome = reviewer_agent.review_text(
                    "complete parser text",
                    cwd=Path(cwd_raw),
                    home=Path(home_raw),
                )

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, "major_revision")
        self.assertEqual(outcome.text, "complete parser text")


class ParserTests(unittest.TestCase):
    def test_cost_baseline_reads_natural_language_memory(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw:
            cwd = Path(cwd_raw)
            source = cwd / "invoice.pdf"
            source.write_text("body\n", encoding="utf-8")
            memory = "\n".join(
                [
                    "PDF scan group contains 1 file(s) such as invoice.pdf; start from high cost parsing.",
                    "Overall, this folder has 1 file(s); start from medium cost parsing as the overall baseline.",
                ]
            )

            baseline = parser_agent._cost_baseline(source, cwd=cwd, memory=memory)

            self.assertEqual(baseline, "high")
            self.assertEqual(parser_agent._cost_from_text("start from very low cost parsing"), "very low")

    def test_parse_path_writes_output_with_user_parser_from_injected_home(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            _write_fake_user_toolbox(home)
            source = cwd / "sample.txt"
            source.write_text("parsed body\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                result = parser_agent.parse_path(
                    source,
                    cwd=cwd,
                    home=home,
                    out_dir=cwd / "out",
                )

            output_file = Path(result.output_file)
            self.assertTrue(result.ok)
            self.assertEqual(result.tool, "fake_tool")
            self.assertTrue(output_file.exists())
            self.assertEqual(output_file.name, "sample.txt.txt")
            self.assertEqual(output_file.read_text(encoding="utf-8"), "parsed body\n")


if __name__ == "__main__":
    unittest.main()
