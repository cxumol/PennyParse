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
                "        'kind': 'user',",
                "        'scope': 'parser',",
                "        'cost': 'very low',",
                "        'summary': 'Fake test tool.',",
                "        'result_kind': 'text',",
                "    },",
                "]",
                "UNAVAILABLE_TOOLS = {}",
                "",
                "def tool_fake_tool(argv):",
                "    return ''",
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
            copied_pdf = shutil.copy2(pdf_asset, fixtures / pdf_asset.name)
            copied_image = shutil.copy2(image_asset, fixtures / image_asset.name)

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
            memory = json.loads(result_file.read_text(encoding="utf-8"))
            rel_pdf = copied_pdf.relative_to(cwd).as_posix()
            rel_image = copied_image.relative_to(cwd).as_posix()
            records = {item["path"]: item for item in memory["files"]}

            self.assertTrue(summary["ok"])
            self.assertEqual(summary["result_file"], str(result_file))
            self.assertEqual(memory["cwd"], str(cwd.resolve()))
            self.assertIn(rel_pdf, records)
            self.assertIn(rel_image, records)
            self.assertEqual(records[rel_image]["meta"]["image"]["width"], tool_cmd.img_metadata_px(["--path", str(copied_image)])["width"])

            if importlib.util.find_spec("pymupdf") is not None:
                self.assertGreaterEqual(records[rel_pdf]["meta"]["pdf"]["page_count"], 1)


if __name__ == "__main__":
    unittest.main()
