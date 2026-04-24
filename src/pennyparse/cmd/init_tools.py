from __future__ import annotations

import base64
import json
import mimetypes
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

from .._client import ChatClient, ChatSession
from ..config import (
    ensure_user_state_dir,
    get_chat_settings,
    get_prompt_text,
    get_user_toolbox_example_text,
    get_user_toolbox_path,
    inject_prompt_context,
    pp_config,
)
from ..logger import get_logger
from ..utils import extract_md_codeblock
from .tool import (
    SAMPLE_DYNAMIC_IMPORT,
    SAMPLE_GENERATED_USER_TOOLBOX,
    ToolSpec,
    coerce_tool_result,
    load_user_specs,
    load_user_toolbox_module,
    normalize_tool_identifier,
    prompt_builtin_contract_json,
)


@dataclass(slots=True)
class SmokeTestRecord:
    tool: str
    ok: bool
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    exception: str = ""
    traceback: str = ""
    unavailable_reason: str = ""
    result_kind: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exception": self.exception,
            "traceback": self.traceback,
            "unavailable_reason": self.unavailable_reason,
            "result_kind": self.result_kind,
        }


def run_init_tools(
    *,
    overwrite: bool,
    source_path: Path | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> dict[str, Any]:
    cwd = cwd or Path.cwd()
    home = home or Path.home()
    logger = logger or get_logger("cmd.init_tools")
    ensure_user_state_dir(home=home)

    resolved_source = source_path or (home / "pennyparse.toolbox_user.txt")
    if not resolved_source.exists():
        raise FileNotFoundError(f"{resolved_source} not found")

    target_path = get_user_toolbox_path(home=home)
    if target_path.exists() and not overwrite:
        raise RuntimeError(f"refused to overwrite existing {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    static_prompt = inject_prompt_context(
        get_prompt_text("generate_user_tools_cli"),
        {
            "__sample_generated_module__": SAMPLE_GENERATED_USER_TOOLBOX.strip(),
            "__sample_dynamic_import__": SAMPLE_DYNAMIC_IMPORT.strip(),
        },
    )
    turn_limit = int(pp_config["aigc"]["agent"]["max_iter"])

    session = ChatSession()
    session.system(static_prompt)
    session.user(
        _build_initial_prompt(
            cwd=cwd,
            target_path=target_path,
            source_path=resolved_source,
        )
    )

    chat_settings = get_chat_settings()
    if not chat_settings.get("model"):
        raise RuntimeError("chat model is not configured")

    summary: dict[str, Any] | None = None
    with ChatClient(**chat_settings) as client:
        for turn in range(1, turn_limit + 1):
            logger.info("Generating user toolbox, turn %s/%s", turn, turn_limit)
            assistant = client.complete(session)
            code = _extract_python_code(assistant.get("content"))
            target_path.write_text(code, encoding="utf-8")
            logger.info("Wrote generated toolbox to %s", target_path)

            smoke = _smoke_test_user_tools(
                target_path=target_path,
                logger=logger,
            )
            summary = _build_summary(
                target_path=target_path,
                turn=turn,
                smoke=smoke,
            )

            if not smoke["failures"]:
                break

            session.user(_build_repair_feedback(smoke))
        else:
            logger.warning("Reached loop limit %s while generating user toolbox", turn_limit)

    assert summary is not None
    return summary


def _build_initial_prompt(
    *,
    cwd: Path,
    target_path: Path,
    source_path: Path,
) -> str:
    prompt_sections = [
        f"Generate the Python file at: {target_path}",
        f"Working directory: {cwd}",
        f"User toolbox TXT file: {source_path}",
        "",
        "Builtin tool contract metadata:",
        prompt_builtin_contract_json(),
        "",
        "User toolbox runtime contract:",
        _runtime_contract_text(),
        "",
        "Example user toolbox TXT style:",
        get_user_toolbox_example_text().strip(),
        "",
        "Original user toolbox TXT:",
        source_path.read_text(encoding="utf-8"),
    ]
    return "\n".join(prompt_sections).strip()


def _runtime_contract_text() -> str:
    demo_assets = _demo_assets()
    asset_lines = "\n".join(
        [
            f"- image_path: {demo_assets['image']}",
            f"- pdf_path: {demo_assets['pdf']}",
            f"- image_data_url: {_build_data_url(demo_assets['image'])[:120]}...",
            f"- pdf_data_url: {_build_data_url(demo_assets['pdf'])[:120]}...",
        ]
    )
    return (
        "Return exactly one ```python fenced code block containing the full module, with no prose before or after it.\n\n"
        + _runtime_contract_header()
        + "\n\nAvailable weak-acceptance demo assets:\n"
        + asset_lines
    )


def _runtime_contract_header() -> str:
    return (
        "The generated file must define TOOL_SPECS, TOOL_HANDLERS, UNAVAILABLE_TOOLS, and SMOKE_TEST_ARGS.\n"
        "TOOL_SPECS must be a non-empty list of dicts that faithfully describes the generated user tools.\n"
        "Each TOOL_SPECS item must include name, kind='user', scope, cost, summary, result_kind, secret, params, api_reference, and notes.\n"
        "Every handler receives argv: list[str], parses args with argparse, and returns a result instead of printing it.\n"
        "Do not print business output to stdout. Do not hardcode secrets. Read required env vars lazily inside handlers.\n"
        "When a tool is intentionally disabled, record the reason in UNAVAILABLE_TOOLS.\n"
        "Prefer httpx for HTTP requests. Prefer subprocess for local CLI calls.\n"
        "SMOKE_TEST_ARGS should give each tool a local demo argv when feasible."
    )


def _extract_python_code(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(part.get("text", "")) if isinstance(part, Mapping) else str(part)
            for part in content
        ).strip()
    else:
        raise RuntimeError("chat completion did not return textual content")

    text = extract_md_codeblock(text) or text
    if not text:
        raise RuntimeError("generated user toolbox is empty")
    return text + "\n"


def _program_unavailable_reasons(tool_specs: list[ToolSpec]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for spec in tool_specs:
        missing = [name for name in spec.secret if not __import__("os").getenv(name)]
        if missing:
            reasons[spec.name] = f"missing required env vars: {', '.join(missing)}"
    return reasons


def _smoke_test_user_tools(
    *,
    target_path: Path,
    logger,
) -> dict[str, Any]:
    module, module_error = load_user_toolbox_module(module_path=target_path)
    failures: list[SmokeTestRecord] = []
    records: list[SmokeTestRecord] = []
    enabled: list[str] = []
    unavailable: dict[str, str] = {}

    if module_error:
        logger.error("Failed to import generated toolbox: %s", module_error)
        record = SmokeTestRecord(
            tool="__module__",
            ok=False,
            argv=[],
            exit_code=1,
            stdout="",
            stderr="",
            exception=module_error,
        )
        records.append(record)
        failures.append(record)
        return {
            "records": records,
            "failures": failures,
            "enabled": enabled,
            "unavailable": unavailable,
        }

    assert module is not None
    tool_specs, specs_error = load_user_specs(module=module)
    if specs_error:
        logger.error("Generated toolbox manifest is invalid: %s", specs_error)
        record = SmokeTestRecord(
            tool="__tool_specs__",
            ok=False,
            argv=[],
            exit_code=1,
            stdout="",
            stderr="",
            exception=specs_error,
        )
        records.append(record)
        failures.append(record)
        return {
            "records": records,
            "failures": failures,
            "enabled": enabled,
            "unavailable": unavailable,
        }

    program_unavailable = _program_unavailable_reasons(tool_specs)
    unavailable.update(program_unavailable)
    for tool_name, reason in program_unavailable.items():
        logger.warning("Tool %s is unavailable (program_rule): %s", tool_name, reason)

    llm_unavailable = getattr(module, "UNAVAILABLE_TOOLS", {})
    if isinstance(llm_unavailable, Mapping):
        for name, reason in llm_unavailable.items():
            if name not in unavailable and isinstance(reason, str) and reason.strip():
                unavailable[name] = reason.strip()
                logger.warning("Tool %s is unavailable (llm): %s", name, reason.strip())

    smoke_args = _resolve_smoke_test_args(module, tool_specs)
    handlers = getattr(module, "TOOL_HANDLERS", {})
    if not isinstance(handlers, Mapping):
        handlers = {}

    for spec in tool_specs:
        if spec.name in unavailable:
            records.append(
                SmokeTestRecord(
                    tool=spec.name,
                    ok=True,
                    argv=[],
                    exit_code=0,
                    stdout="",
                    stderr="",
                    unavailable_reason=unavailable[spec.name],
                )
            )
            continue

        handler = handlers.get(spec.name)
        if handler is None:
            handler = getattr(module, f"tool_{normalize_tool_identifier(spec.name)}", None)
        if handler is None:
            record = SmokeTestRecord(
                tool=spec.name,
                ok=False,
                argv=[],
                exit_code=1,
                stdout="",
                stderr="",
                exception=f"generated toolbox has no handler for {spec.name}",
            )
            records.append(record)
            failures.append(record)
            logger.error("Smoke test failed for %s: missing handler", spec.name)
            continue

        argv = smoke_args.get(spec.name) or []
        stdout_buffer = StringIO()
        stderr_buffer = StringIO()
        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                result = handler(list(argv))
            coerced = coerce_tool_result(result, expected_kind=spec.result_kind, tool_name=spec.name)
            record = SmokeTestRecord(
                tool=spec.name,
                ok=not stdout_buffer.getvalue(),
                argv=list(argv),
                exit_code=0 if not stdout_buffer.getvalue() else 1,
                stdout=stdout_buffer.getvalue(),
                stderr=stderr_buffer.getvalue(),
                result_kind=coerced.kind,
                exception="stdout pollution" if stdout_buffer.getvalue() else "",
            )
            if record.ok:
                enabled.append(spec.name)
                logger.info("Smoke test passed for %s", spec.name)
            else:
                failures.append(record)
                logger.error("Smoke test failed for %s: stdout pollution", spec.name)
        except BaseException as exc:
            exit_code = 1
            if isinstance(exc, SystemExit):
                exit_code = int(exc.code) if isinstance(exc.code, int) else 1
            record = SmokeTestRecord(
                tool=spec.name,
                ok=False,
                argv=list(argv),
                exit_code=exit_code,
                stdout=stdout_buffer.getvalue(),
                stderr=stderr_buffer.getvalue(),
                exception=repr(exc),
                traceback=traceback.format_exc(),
            )
            failures.append(record)
            logger.error("Smoke test failed for %s: %s", spec.name, exc)
        records.append(record)

    return {
        "records": records,
        "failures": failures,
        "enabled": enabled,
        "unavailable": unavailable,
    }


def _resolve_smoke_test_args(module: Any, tool_specs: list[ToolSpec]) -> dict[str, list[str]]:
    declared = getattr(module, "SMOKE_TEST_ARGS", {})
    resolved: dict[str, list[str]] = {}
    if isinstance(declared, Mapping):
        for name, argv in declared.items():
            if isinstance(name, str) and isinstance(argv, list) and all(isinstance(item, str) for item in argv):
                resolved[name] = list(argv)

    for spec in tool_specs:
        resolved.setdefault(spec.name, _default_smoke_test_args(spec))
    return resolved


def _default_smoke_test_args(spec: ToolSpec) -> list[str]:
    assets = _demo_assets()
    prefer_pdf = _prefers_pdf(spec)
    argv: list[str] = []
    for param in spec.params:
        if param.type == "bool":
            if param.required:
                argv.append(param.flag())
            continue

        value = _demo_value_for_param(spec, param.name, prefer_pdf, assets)
        if value is None:
            continue
        argv.extend([param.flag(), value])
    return argv


def _prefers_pdf(spec: ToolSpec) -> bool:
    text = " ".join([spec.name, spec.summary, spec.notes, spec.api_reference]).lower()
    pdf_hits = ["pdf", "document", "markdown", "mineru", "page"]
    image_hits = ["image", "ocr", "vision", "figure", "photo", "png", "jpeg"]
    return sum(token in text for token in pdf_hits) >= sum(token in text for token in image_hits)


def _demo_value_for_param(
    spec: ToolSpec,
    param_name: str,
    prefer_pdf: bool,
    assets: Mapping[str, Path],
) -> str | None:
    name = param_name.lower()
    if "prompt" in name or "instruction" in name or "query" in name or name.endswith("_text"):
        return "Convert the document to markdown." if prefer_pdf else "OCR this image."
    if "pdf_url" in name:
        return _build_data_url(assets["pdf"])
    if "image_url" in name or (name.endswith("url") and not prefer_pdf):
        return _build_data_url(assets["image"])
    if name.endswith("url"):
        return _build_data_url(assets["pdf"] if prefer_pdf else assets["image"])
    if "pdf" in name:
        return str(assets["pdf"])
    if "image" in name or "img" in name:
        return str(assets["image"])
    if "path" in name or "file" in name:
        return str(assets["pdf"] if prefer_pdf else assets["image"])
    if name in {"mode", "format"}:
        return "markdown"
    if name in {"lang", "language"}:
        return "en"
    if name in {"page_range"}:
        return "1-1"
    if name in {"model"}:
        return ""
    if any(token in spec.name.lower() for token in {"ocr", "vl", "image"}) and not prefer_pdf:
        return str(assets["image"])
    return None


def _demo_assets() -> dict[str, Path]:
    base = Path(__file__).resolve().parent.parent / "_demo_assets"
    return {
        "image": base / "vl1.58.png",
        "image_alt": base / "vl1_5_8.png",
        "pdf": base / "3small.pdf",
    }


def _build_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _build_repair_feedback(smoke: Mapping[str, Any]) -> str:
    failures = [record.as_dict() for record in smoke["failures"]]
    unavailable = smoke["unavailable"]
    return (
        "The generated file failed the smoke tests. Return a full replacement for user_toolbox.py inside exactly one ```python fenced code block.\n\n"
        "Keep tools listed in UNAVAILABLE_TOOLS disabled only when you cannot make them safe and callable.\n"
        "Do not print business output to stdout.\n\n"
        "Current unavailable tools:\n"
        + json.dumps(unavailable, ensure_ascii=False, indent=2)
        + "\n\nSmoke test failures:\n"
        + json.dumps(failures, ensure_ascii=False, indent=2)
    )


def _build_summary(
    *,
    target_path: Path,
    turn: int,
    smoke: Mapping[str, Any],
) -> dict[str, Any]:
    failures = smoke["failures"]
    valid = list(smoke["enabled"])
    unavailable = dict(smoke["unavailable"])
    failed = sorted({record.tool for record in failures}.union(unavailable.keys()))
    return {
        "ok": not failures,
        "usertools_valid": valid,
        "usertools_failed": failed,
        "agent_turns": turn,
        "result_file": str(target_path),
        "unavailable_tools": unavailable,
        "log_path": str(Path.cwd() / "pennyparse.log"),
        "smoke_test": [record.as_dict() for record in smoke["records"]],
    }

