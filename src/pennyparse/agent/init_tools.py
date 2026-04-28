from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .._client import ChatClient, ChatSession
from ..config import (
    get_chat_settings,
    get_prompt_text,
    get_user_toolbox_example_text,
    inject_prompt_context,
    pp_config,
)
from ..logger import get_logger
from ..utils import extract_md_codeblock
from ..cmd.tool import (
    SAMPLE_DYNAMIC_IMPORT,
    SAMPLE_GENERATED_USER_TOOLBOX,
    ToolSpec,
    load_user_specs,
    load_user_toolbox_module,
    prompt_builtin_contract_json,
)


@dataclass(slots=True)
class ValidationRecord:
    tool: str
    ok: bool
    exception: str = ""
    unavailable_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "exception": self.exception,
            "unavailable_reason": self.unavailable_reason,
        }


def run_init_tools_agent(
    *,
    cwd: Path,
    source_path: Path,
    target_path: Path,
    logger=None,
) -> dict[str, Any]:
    logger = logger or get_logger("agent.init_tools")
    if not source_path.exists():
        raise FileNotFoundError(f"{source_path} not found")

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
            source_path=source_path,
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

            validation = _validate_user_tools(
                target_path=target_path,
                logger=logger,
            )
            summary = _build_summary(
                target_path=target_path,
                turn=turn,
                validation=validation,
            )

            if not validation["failures"]:
                break

            session.user(_build_repair_feedback(validation))
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
    return (
        "Return exactly one ```python fenced code block containing the full module, with no prose before or after it.\n\n"
        + _runtime_contract_header()
    )


def _runtime_contract_header() -> str:
    return (
        "The generated file must define TOOL_SPECS, TOOL_HANDLERS, and UNAVAILABLE_TOOLS.\n"
        "TOOL_SPECS must be a non-empty list of dicts that faithfully describes the generated user tools.\n"
        "Each TOOL_SPECS item must include name, kind='user', scope, cost, summary, result_kind, secret, params, api_reference, and notes.\n"
        "Every handler receives argv: list[str], parses args with argparse, and returns a result instead of printing it.\n"
        "Do not print business output to stdout. Do not hardcode secrets. Read required env vars lazily inside handlers.\n"
        "When a tool is intentionally disabled, record the reason in UNAVAILABLE_TOOLS.\n"
        "Prefer httpx for HTTP requests. Prefer subprocess for local CLI calls.\n"
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
        missing = [name for name in spec.secret if not os.getenv(name)]
        if missing:
            reasons[spec.name] = f"missing required env vars: {', '.join(missing)}"
    return reasons


def _validate_user_tools(
    *,
    target_path: Path,
    logger,
) -> dict[str, Any]:
    module, module_error = load_user_toolbox_module(module_path=target_path)
    failures: list[ValidationRecord] = []
    records: list[ValidationRecord] = []
    enabled: list[str] = []
    unavailable: dict[str, str] = {}

    if module_error:
        logger.error("Failed to import generated toolbox: %s", module_error)
        record = ValidationRecord(
            tool="__module__",
            ok=False,
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
        record = ValidationRecord(
            tool="__tool_specs__",
            ok=False,
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

    handlers = getattr(module, "TOOL_HANDLERS", {})
    if not isinstance(handlers, Mapping):
        record = ValidationRecord(
            tool="__tool_handlers__",
            ok=False,
            exception="generated toolbox TOOL_HANDLERS must be a mapping",
        )
        records.append(record)
        failures.append(record)
        handlers = {}

    for spec in tool_specs:
        if spec.name in unavailable:
            records.append(
                ValidationRecord(
                    tool=spec.name,
                    ok=True,
                    unavailable_reason=unavailable[spec.name],
                )
            )
            continue

        handler = handlers.get(spec.name)
        if handler is None or not callable(handler):
            error = (
                f"generated toolbox TOOL_HANDLERS has no handler for {spec.name}"
                if handler is None
                else f"generated toolbox TOOL_HANDLERS handler for {spec.name} is not callable"
            )
            record = ValidationRecord(
                tool=spec.name,
                ok=False,
                exception=error,
            )
            records.append(record)
            failures.append(record)
            logger.error("Generated toolbox validation failed for %s: %s", spec.name, error)
            continue

        record = ValidationRecord(tool=spec.name, ok=True)
        enabled.append(spec.name)
        logger.info("Generated toolbox validation passed for %s", spec.name)
        records.append(record)

    return {
        "records": records,
        "failures": failures,
        "enabled": enabled,
        "unavailable": unavailable,
    }


def _build_repair_feedback(validation: Mapping[str, Any]) -> str:
    failures = [record.as_dict() for record in validation["failures"]]
    unavailable = validation["unavailable"]
    return (
        "The generated file failed runtime-contract validation. Return a full replacement for user_toolbox.py inside exactly one ```python fenced code block.\n\n"
        "Keep tools listed in UNAVAILABLE_TOOLS disabled only when you cannot make them safe and callable.\n"
        "Do not print business output to stdout.\n\n"
        "Current unavailable tools:\n"
        + json.dumps(unavailable, ensure_ascii=False, indent=2)
        + "\n\nValidation failures:\n"
        + json.dumps(failures, ensure_ascii=False, indent=2)
    )


def _build_summary(
    *,
    target_path: Path,
    turn: int,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    failures = validation["failures"]
    valid = list(validation["enabled"])
    unavailable = dict(validation["unavailable"])
    failed = sorted({record.tool for record in failures}.union(unavailable.keys()))
    return {
        "ok": not failures,
        "usertools_valid": valid,
        "usertools_failed": failed,
        "agent_turns": turn,
        "result_file": str(target_path),
        "unavailable_tools": unavailable,
        "log_path": str(Path.cwd() / "pennyparse.log"),
        "validation": [record.as_dict() for record in validation["records"]],
    }
