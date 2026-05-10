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

import httpx
from typer.testing import CliRunner


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
from pennyparse.cmd import run as run_cmd  # noqa: E402
from pennyparse import cli as cli_module  # noqa: E402
from pennyparse.agent import init_tools as init_tools_agent  # noqa: E402
from pennyparse.agent import parser as parser_agent  # noqa: E402
from pennyparse.agent import reviewer as reviewer_agent  # noqa: E402
from pennyparse._client import ChatSession  # noqa: E402
from pennyparse import utils, utils_aigc  # noqa: E402


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


def _write_fake_image_user_toolbox(home: Path) -> None:
    toolbox = home / ".pennyparse" / "user_toolbox.py"
    toolbox.parent.mkdir(parents=True, exist_ok=True)
    toolbox.write_text(
        "\n".join(
            [
                "import os",
                "",
                "TOOL_SPECS = [",
                "    {",
                "        'name': 'fake_ocr',",
                "        'scope': 'parser',",
                "        'cost': 'low',",
                "        'desc': 'Fake image OCR test tool.',",
                "        'flags': {'path': '/path/to/image.png'},",
                "    },",
                "]",
                "UNAVAILABLE_TOOLS = {}",
                "",
                "def tool_fake_ocr(argv):",
                "    path = argv[argv.index('--path') + 1]",
                "    if path.lower().endswith('.pdf'):",
                "        return ''",
                "    return 'OCR ' + os.path.basename(path)",
                "",
                "TOOL_HANDLERS = {'fake_ocr': tool_fake_ocr}",
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


def _write_init_sampling_settings(cwd: Path) -> None:
    (cwd / "pennyparse.settings.toml").write_text(
        "\n".join(
            [
                "[aigc.api.chatcomp]",
                'model = "unit-test-model"',
                "",
                "[init.sampling]",
                'by = "first"',
                "num = 1",
                "pdf_page = 1",
                "pdf_page_total_max = 1",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_parser_batch_settings(cwd: Path, batch_size: int) -> None:
    (cwd / "pennyparse.settings.toml").write_text(
        "\n".join(
            [
                "[output]",
                f"parser_summary_batch = {batch_size}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_ignore_txt_settings(cwd: Path) -> None:
    (cwd / "pennyparse.settings.toml").write_text(
        "\n".join(
            [
                "[init.ignore]",
                'ext = ["txt", "toml"]',
                'folder = ["skipme"]',
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

    def test_run_init_docs_samples_with_low_cost_tool(self) -> None:
        image_asset = _discover_demo_asset(IMAGE_SUFFIXES)

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            fixtures = cwd / "fixtures"
            fixtures.mkdir()
            copied_image = Path(shutil.copy2(image_asset, fixtures / image_asset.name))

            _write_fake_image_user_toolbox(home)
            _write_init_sampling_settings(cwd)

            with (
                mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}),
                mock.patch("pennyparse.cmd.init_docs._group_with_llm", return_value=None),
            ):
                summary = init_docs.run_init_docs(overwrite=False, cwd=cwd, home=home)

            memory = (cwd / ".pennyparse_memory.txt").read_text(encoding="utf-8")
            sampled_files = [
                item
                for group in summary["groups"]
                for item in group["sample"]["files"]
            ]

            self.assertTrue(summary["ok"])
            self.assertIn("Sample check:", memory)
            self.assertIn("fake_ocr: OCR", memory)
            self.assertEqual(sampled_files[0]["path"], copied_image.relative_to(cwd).as_posix())
            self.assertIn("fake_ocr: OCR", sampled_files[0]["observation"])

    def test_sample_tools_skip_path_tools_with_extra_required_flags(self) -> None:
        path_only = tool_cmd.DiscoveredTool(
            spec=tool_cmd.ToolSpec.from_mapping(
                {
                    "name": "pdf2txt",
                    "scope": "parser",
                    "cost": "low",
                    "desc": "PDF text",
                    "flags": {"path": "/tmp/a.pdf"},
                }
            ),
            availability=tool_cmd.ToolAvailability(True),
            source="builtin",
        )
        needs_out_dir = tool_cmd.DiscoveredTool(
            spec=tool_cmd.ToolSpec.from_mapping(
                {
                    "name": "pdf_pages_to_images",
                    "scope": "parser",
                    "cost": "medium",
                    "desc": "Render pages",
                    "flags": {"path": "/tmp/a.pdf", "out-dir": "/tmp/pages"},
                }
            ),
            availability=tool_cmd.ToolAvailability(True),
            source="builtin",
        )

        selected = init_docs._sample_tools_for_ext([needs_out_dir, path_only], "pdf")

        self.assertEqual([item.spec.name for item in selected], ["pdf2txt"])


class PseudoXmlTests(unittest.TestCase):
    def test_extract_pseudo_xml_keeps_legacy_alias(self) -> None:
        text = "<item>first</item>\n<item attr='x'>second</item>"

        self.assertEqual(utils.extract_pseudo_xml(text, "item"), "second")
        self.assertIs(utils.extract_pesudo_xml, utils.extract_pseudo_xml)
        self.assertEqual(utils.extract_pesudo_xml(text, "item"), "second")

    def test_init_tools_agent_declares_pseudo_xml_mode(self) -> None:
        self.assertEqual(init_tools_agent._AGENT_IMPL_MODE, "pseudo_XML")

    def test_init_tools_agent_repairs_from_result_validation_feedback(self) -> None:
        first_module = """
TOOL_SPECS = [
    {
        "name": "demo_ocr",
        "scope": "parser",
        "cost": "low",
        "desc": "Demo OCR.",
        "flags": {"path": "/path/to/image.png"},
    }
]
UNAVAILABLE_TOOLS = {}

def tool_demo_ocr(argv):
    return {"provider_payload": {"blocks": [{"text": "extracted text"}]}}

TOOL_HANDLERS = {"demo_ocr": tool_demo_ocr}
"""
        second_module = """
TOOL_SPECS = [
    {
        "name": "demo_ocr",
        "scope": "parser",
        "cost": "low",
        "desc": "Demo OCR.",
        "flags": {"path": "/path/to/image.png"},
    }
]
UNAVAILABLE_TOOLS = {}

def tool_demo_ocr(argv):
    return "extracted text"

TOOL_HANDLERS = {"demo_ocr": tool_demo_ocr}
"""
        seen_messages: list[str] = []

        class FakeChatClient:
            def __init__(self, **kwargs):
                self.calls = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                pass

            def complete(self, session, **kwargs):
                self.calls += 1
                seen_messages.append(session.messages[-1]["content"])
                code = first_module if self.calls == 1 else second_module
                message = {"role": "assistant", "content": f"```python\n{code}\n```"}
                session.messages.append(message)
                return message

        def result_validator(target_path: Path, specs: list[tool_cmd.ToolSpec]):
            module, module_error = tool_cmd.load_user_toolbox_module(module_path=target_path)
            testcase = self
            testcase.assertIsNone(module_error)
            testcase.assertEqual([spec.name for spec in specs], ["demo_ocr"])
            raw = module.TOOL_HANDLERS["demo_ocr"](["--path", str(DEMO_ASSETS / "vl1.58.png")])
            if raw == "extracted text":
                return [init_tools_agent.ValidationRecord(tool="demo_ocr", ok=True)]
            return [
                init_tools_agent.ValidationRecord(
                    tool="demo_ocr",
                    ok=False,
                    exception="parser result did not expose the extracted text directly",
                    details={"output_excerpt": json.dumps(raw, ensure_ascii=False)},
                )
            ]

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            source = cwd / "pennyparse.toolbox_user.txt"
            target = home / ".pennyparse" / "user_toolbox.py"
            target.parent.mkdir(parents=True)
            source.write_text("Tool: demo_ocr\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.init_tools.ChatClient", FakeChatClient),
            ):
                summary = init_tools_agent.run_init_tools_agent(
                    cwd=cwd,
                    source_path=source,
                    target_path=target,
                    result_validator=result_validator,
                )

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["agent_turns"], 2)
            self.assertIn("output-quality issues", seen_messages[1])
            self.assertIn("parser result did not expose the extracted text directly", seen_messages[1])
            self.assertIn('return "extracted text"', target.read_text(encoding="utf-8"))

    def test_init_tools_default_result_validation_uses_packaged_assets_in_temp_cwd(self) -> None:
        module_code = """
from pathlib import Path
import argparse
import os
import tempfile

TOOL_SPECS = [
    {
        "name": "demo_parser",
        "scope": "parser",
        "cost": "very low",
        "desc": "Demo image parser.",
        "flags": {"path": "/path/to/image.png", "out-dir": "/path/to/output"},
    }
]
UNAVAILABLE_TOOLS = {}

def tool_demo_parser(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--path", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    cwd = Path.cwd()
    tmp = Path(tempfile.gettempdir())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (cwd / "cwd_marker.txt").write_text("ok", encoding="utf-8")
    (tmp / "tmp_marker.txt").write_text("ok", encoding="utf-8")
    return {
        "cwd": str(cwd),
        "tmp": str(tmp),
        "asset": Path(args.path).name,
        "out_dir": str(out_dir),
        "exists": Path(args.path).exists(),
    }

TOOL_HANDLERS = {"demo_parser": tool_demo_parser}
"""

        class FakeChatClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                pass

            def complete(self, session, **kwargs):
                message = {"role": "assistant", "content": f"```python\n{module_code}\n```"}
                session.messages.append(message)
                return message

        temp_roots: list[Path] = []
        original_tempdir = init_tools_agent.tempfile.TemporaryDirectory

        class TrackingTemporaryDirectory:
            def __init__(self, *args, **kwargs):
                self.inner = original_tempdir(*args, **kwargs)

            def __enter__(self):
                path = Path(self.inner.__enter__())
                temp_roots.append(path)
                return str(path)

            def __exit__(self, exc_type, exc_value, traceback):
                return self.inner.__exit__(exc_type, exc_value, traceback)

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            source = cwd / "pennyparse.toolbox_user.txt"
            target = home / ".pennyparse" / "user_toolbox.py"
            target.parent.mkdir(parents=True)
            source.write_text("Tool: demo_parser\n", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.init_tools.ChatClient", FakeChatClient),
                mock.patch("pennyparse.agent.init_tools.tempfile.TemporaryDirectory", TrackingTemporaryDirectory),
            ):
                summary = init_tools_agent.run_init_tools_agent(
                    cwd=cwd,
                    source_path=source,
                    target_path=target,
                )

            self.assertTrue(summary["ok"], summary)
            validation = [item for item in summary["validation"] if item["tool"] == "demo_parser"]
            self.assertEqual(len(validation), 2)
            result_details = [item["details"] for item in validation if "asset" in item.get("details", {})][0]
            self.assertIn(result_details["asset"], {asset.name for asset in init_tools_agent._package_demo_assets()})
            self.assertTrue(temp_roots)
            for root in temp_roots:
                self.assertFalse(root.exists())
            self.assertFalse((cwd / "cwd_marker.txt").exists())

    def test_init_tools_agent_writes_unavailable_fallback_on_chat_network_error(self) -> None:
        class FailingChatClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                pass

            def complete(self, session, **kwargs):
                raise httpx.ConnectError("network is unreachable")

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            source = cwd / "pennyparse.toolbox_user.txt"
            target = home / ".pennyparse" / "user_toolbox.py"
            target.parent.mkdir(parents=True)
            source.write_text(
                "siliconflow_deepseekocr\nAuthorization: Bearer $SILICONFLOW_API_KEY\n",
                encoding="utf-8",
            )

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.init_tools.ChatClient", FailingChatClient),
            ):
                summary = init_tools_agent.run_init_tools_agent(
                    cwd=cwd,
                    source_path=source,
                    target_path=target,
                )

            module, module_error = tool_cmd.load_user_toolbox_module(module_path=target)
            self.assertIsNone(module_error)
            self.assertIsNotNone(module)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["agent_turns"], 0)
            self.assertIn("fallback_reason", summary)
            self.assertEqual(summary["usertools_failed"], ["siliconflow_deepseekocr"])
            self.assertEqual(module.TOOL_SPECS[0]["name"], "siliconflow_deepseekocr")
            self.assertIn("SILICONFLOW_API_KEY", module.TOOL_SPECS[0]["secrets"])
            self.assertIn("siliconflow_deepseekocr", module.UNAVAILABLE_TOOLS)


class InitCliTests(unittest.TestCase):
    def test_init_root_runs_aggregate_with_force_and_toolbox_source(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            source = cwd / "custom.toolbox.txt"
            source.write_text("toolbox\n", encoding="utf-8")
            calls: list[dict[str, object]] = []

            def fake_run_init(**kwargs):
                calls.append(kwargs)
                return {
                    "ok": True,
                    "tools": {
                        "ok": True,
                        "result_file": str(home / ".pennyparse" / "user_toolbox.py"),
                    },
                    "docs": {"ok": True, "result_file": str(cwd / ".pennyparse_memory.txt")},
                }

            def fake_resolve(entrypoint):
                self.assertEqual(entrypoint, cli_module._INIT_ENTRYPOINT)
                return fake_run_init

            old_cwd = Path.cwd()
            os.chdir(cwd)
            try:
                with (
                    mock.patch.dict(
                        os.environ,
                        {"HOME": str(home), "PENNYPARSE_CHAT_MODEL": "unit-test-model"},
                    ),
                    mock.patch.object(cli_module, "resolve_entrypoint", side_effect=fake_resolve),
                ):
                    result = runner.invoke(
                        cli_module.app,
                        ["init", "--force", "--from", str(source)],
                    )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["overwrite_tools"])
        self.assertTrue(calls[0]["overwrite_docs"])
        self.assertEqual(calls[0]["source_path"], source)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_init_tools_subcommand_keeps_specific_entrypoint(self) -> None:
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            source = cwd / "custom.toolbox.txt"
            source.write_text("toolbox\n", encoding="utf-8")
            calls: list[dict[str, object]] = []

            def fake_run_init_tools(**kwargs):
                calls.append(kwargs)
                return {"ok": True, "result_file": str(home / ".pennyparse" / "user_toolbox.py")}

            def fake_resolve(entrypoint):
                self.assertEqual(entrypoint, cli_module._INIT_TOOLS_ENTRYPOINT)
                return fake_run_init_tools

            old_cwd = Path.cwd()
            os.chdir(cwd)
            try:
                with (
                    mock.patch.dict(
                        os.environ,
                        {"HOME": str(home), "PENNYPARSE_CHAT_MODEL": "unit-test-model"},
                    ),
                    mock.patch.object(cli_module, "resolve_entrypoint", side_effect=fake_resolve),
                ):
                    result = runner.invoke(
                        cli_module.app,
                        ["init", "tools", "--force", "--from", str(source)],
                    )
            finally:
                os.chdir(old_cwd)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["overwrite"])
        self.assertEqual(calls[0]["source_path"], source)
        self.assertTrue(json.loads(result.stdout)["ok"])


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

    def test_reviewer_tool_patch_loop_targets_initial_text_each_turn(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            tool_results: list[dict[str, object]] = []
            testcase = self

            class FakeChatClient:
                def __init__(self, **kwargs):
                    self.calls = 0

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc_value, traceback):
                    pass

                def complete(self, session, **kwargs):
                    self.calls += 1
                    if self.calls == 1:
                        return {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "myregexpatch",
                                        "arguments": json.dumps(
                                            {
                                                "message": "first patch",
                                                "before_len": 2,
                                                "after_len": 2,
                                                "patches": [{"pattern": "a", "repl": "b"}],
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    if self.calls == 2:
                        payload = json.loads(session.messages[-1]["content"])
                        tool_results.append(payload)
                        testcase.assertNotIn("revised", payload)
                        return {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {
                                        "name": "myregexpatch",
                                        "arguments": json.dumps(
                                            {
                                                "message": "second patch",
                                                "before_len": 2,
                                                "after_len": 2,
                                                "patches": [{"pattern": "a", "repl": "c"}],
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    payload = json.loads(session.messages[-1]["content"])
                    tool_results.append(payload)
                    return {
                        "role": "assistant",
                        "content": json.dumps(
                            {"status": "minor_revision", "message": "accept patch"}
                        ),
                    }

            with (
                mock.patch.dict(os.environ, {"PENNYPARSE_CHAT_MODEL": "unit-test-model"}),
                mock.patch("pennyparse.agent.reviewer.ChatClient", FakeChatClient),
            ):
                outcome = reviewer_agent.review_text(
                    "aa",
                    cwd=Path(cwd_raw),
                    home=Path(home_raw),
                )

        self.assertEqual(outcome.status, "minor_revision")
        self.assertEqual(outcome.text, "cc")
        self.assertTrue(all(item["ok"] for item in tool_results))
        self.assertEqual(tool_results[-1]["replacement_count"], 2)


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

    def test_parse_pdf_falls_back_to_page_images_and_merges_output(self) -> None:
        if importlib.util.find_spec("pymupdf") is None:
            self.skipTest("pymupdf is not installed")

        import pymupdf

        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            _write_fake_image_user_toolbox(home)

            source = cwd / "blank.pdf"
            document = pymupdf.open()
            document.new_page(width=72, height=72)
            document.new_page(width=72, height=72)
            document.save(source)
            document.close()

            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                result = parser_agent.parse_path(
                    source,
                    cwd=cwd,
                    home=home,
                    out_dir=cwd / "out",
                )

            output_file = Path(result.output_file)
            output_text = output_file.read_text(encoding="utf-8")
            page_dir = cwd / "out" / ".pennyparse_pages" / "blank.pdf"

            self.assertTrue(result.ok)
            self.assertTrue(result.tool.startswith("pdf_pages_to_images"))
            self.assertEqual(output_file.name, "blank.pdf.txt")
            self.assertTrue((page_dir / "page-0001.png").exists())
            self.assertTrue((page_dir / "page-0002.png").exists())
            self.assertIn("## Page 1", output_text)
            self.assertIn("OCR page-0001.png", output_text)
            self.assertIn("## Page 2", output_text)
            self.assertIn("OCR page-0002.png", output_text)


class RunCommandTests(unittest.TestCase):
    def test_run_requires_init_files(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            with self.assertRaisesRegex(RuntimeError, "init tools"):
                run_cmd.run(cwd=Path(cwd_raw), home=Path(home_raw))

            _write_fake_user_toolbox(Path(home_raw))
            with self.assertRaisesRegex(RuntimeError, "init docs"):
                run_cmd.run(cwd=Path(cwd_raw), home=Path(home_raw))

    def test_run_appends_batch_and_final_memory_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            _write_fake_user_toolbox(home)
            _write_parser_batch_settings(cwd, 1)
            memory_path = cwd / ".pennyparse_memory.txt"
            memory_path.write_text("initial memory\n", encoding="utf-8")
            first = cwd / "a.txt"
            second = cwd / "b.txt"
            first.write_text("alpha\n", encoding="utf-8")
            second.write_text("beta\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                summary = run_cmd.run(
                    paths=[first, second],
                    out_dir=cwd / "out",
                    cwd=cwd,
                    home=home,
                )

            memory = memory_path.read_text(encoding="utf-8")
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["parsed_count"], 2)
            self.assertEqual(summary["skipped_count"], 0)
            self.assertEqual(summary["output_stats"]["file_count"], 2)
            self.assertTrue(memory.startswith("initial memory\n"))
            self.assertIn("a.txt等1份:fake_tool", memory)
            self.assertIn("b.txt等1份:fake_tool", memory)
            self.assertIn("Run summary: parsed 2, skipped 0, failed 0, output 2 file(s)", memory)

    def test_run_directory_walk_respects_init_ignore_ext(self) -> None:
        with tempfile.TemporaryDirectory() as cwd_raw, tempfile.TemporaryDirectory() as home_raw:
            cwd = Path(cwd_raw)
            home = Path(home_raw)
            _write_fake_user_toolbox(home)
            _write_ignore_txt_settings(cwd)
            memory_path = cwd / ".pennyparse_memory.txt"
            memory_path.write_text("initial memory\n", encoding="utf-8")
            (cwd / "notes.txt").write_text("ignore me\n", encoding="utf-8")
            (cwd / "report.pdf").write_text("parse me\n", encoding="utf-8")
            skipped_dir = cwd / "skipme"
            skipped_dir.mkdir()
            (skipped_dir / "nested.pdf").write_text("ignore folder\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {key: "" for key in CHAT_ENV_KEYS}):
                summary = run_cmd.run(
                    out_dir=cwd / "out",
                    cwd=cwd,
                    home=home,
                )

            parsed_sources = {item["source_file"] for item in summary["results"]}
            self.assertTrue(summary["ok"])
            self.assertEqual(parsed_sources, {"report.pdf"})
            self.assertEqual(summary["parsed_count"], 1)
            self.assertFalse((cwd / "out" / "notes.txt.txt").exists())
            self.assertFalse((cwd / "out" / "skipme" / "nested.pdf.txt").exists())


class ToolCallsLoopTests(unittest.TestCase):
    def test_tool_calls_loop_returns_tool_exception_to_model(self) -> None:
        session = ChatSession()
        session.user("run")

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, session, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "broken", "arguments": "{\"x\": 1}"},
                            }
                        ],
                    }
                else:
                    message = {"role": "assistant", "content": "done"}
                session.messages.append(message)
                return message

        def broken(args):
            raise ValueError(f"bad {args['x']}")

        result = utils_aigc.run_tool_calls_loop(
            FakeClient(),
            session,
            tools=[],
            tool_handlers={"broken": broken},
            max_iter=2,
            max_retry=1,
        )

        tool_message = session.messages[-2]
        tool_payload = json.loads(tool_message["content"])
        self.assertEqual(result["content"], "done")
        self.assertEqual(tool_message["role"], "tool")
        self.assertFalse(tool_payload["ok"])
        self.assertEqual(tool_payload["error"]["type"], "ValueError")

    def test_tool_calls_loop_retries_chat_completion(self) -> None:
        session = ChatSession()
        session.user("hello")

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def complete(self, session, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary")
                message = {"role": "assistant", "content": "ok"}
                session.messages.append(message)
                return message

        client = FakeClient()
        with mock.patch("pennyparse.utils_aigc.time.sleep"):
            result = utils_aigc.run_tool_calls_loop(
                client,
                session,
                tools=[],
                tool_handlers={},
                max_iter=1,
                max_retry=2,
            )

        self.assertEqual(result["content"], "ok")
        self.assertEqual(client.calls, 2)

    def test_tool_calls_loop_stops_at_max_iter(self) -> None:
        session = ChatSession()
        session.user("loop")

        class FakeClient:
            def complete(self, session, **kwargs):
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "noop", "arguments": "{}"},
                        }
                    ],
                }
                session.messages.append(message)
                return message

        with self.assertRaisesRegex(RuntimeError, "max_iter=1"):
            utils_aigc.run_tool_calls_loop(
                FakeClient(),
                session,
                tools=[],
                tool_handlers={"noop": lambda args: "again"},
                max_iter=1,
                max_retry=1,
            )


if __name__ == "__main__":
    unittest.main()
