from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import httpx

from .._client import ChatClient, ChatSession
from ..config import (
    get_chat_settings,
    get_prompt_text,
    get_user_toolbox_example_text,
    inject_prompt_context,
    pp_config,
)
from ..logger import get_logger
from ..utils import extract_md_codeblock, extract_pseudo_xml
from ..cmd.tool import (
    SAMPLE_DYNAMIC_IMPORT,
    SAMPLE_GENERATED_USER_TOOLBOX,
    ToolSpec,
    load_user_specs,
    load_user_toolbox_module,
    prompt_builtin_contract_json,
)

_AGENT_IMPL_MODE = "pseudo_XML"


@dataclass(slots=True)
class ValidationRecord:
    tool: str
    ok: bool
    exception: str = ""
    unavailable_reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "tool": self.tool,
            "ok": self.ok,
            "exception": self.exception,
            "unavailable_reason": self.unavailable_reason,
        }
        if self.details:
            data["details"] = self.details
        return data


ResultValidator = Callable[[Path, list[ToolSpec]], Iterable[ValidationRecord]]


def run_init_tools_agent(
    *,
    cwd: Path,
    source_path: Path,
    target_path: Path,
    result_validator: ResultValidator | None = None,
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
            try:
                assistant = client.complete(session)
            except httpx.RequestError as exc:
                logger.warning("Chat request failed while generating user toolbox: %s", exc)
                return _write_static_fallback_toolbox(
                    source_path=source_path,
                    target_path=target_path,
                    reason=f"chat request failed during init tools: {exc}",
                    logger=logger,
                )
            code = _extract_python_code(assistant.get("content"))
            target_path.write_text(code, encoding="utf-8")
            logger.info("Wrote generated toolbox to %s", target_path)

            validation = _validate_user_tools(
                target_path=target_path,
                result_validator=result_validator,
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


def _write_static_fallback_toolbox(
    *,
    source_path: Path,
    target_path: Path,
    reason: str,
    logger,
) -> dict[str, Any]:
    specs = _fallback_specs(source_path.read_text(encoding="utf-8"))
    code = _fallback_module_code(specs, reason=reason)
    target_path.write_text(code, encoding="utf-8")
    logger.warning("Wrote unavailable fallback toolbox to %s", target_path)
    validation = _validate_user_tools(
        target_path=target_path,
        result_validator=None,
        logger=logger,
    )
    summary = _build_summary(target_path=target_path, turn=0, validation=validation)
    summary["fallback_reason"] = reason
    return summary


def _fallback_specs(source_text: str) -> list[dict[str, Any]]:
    names = _fallback_tool_names(source_text)
    return [
        {
            "name": name,
            "scope": "parser",
            "cost": "medium",
            "desc": f"Unavailable user parser generated from toolbox entry {name!r}.",
            "secrets": _fallback_secrets_for_entry(source_text, name),
            "flags": {"path": "/path/to/file"},
        }
        for name in names
    ]


def _fallback_tool_names(source_text: str) -> list[str]:
    names: list[str] = []
    for line in source_text.splitlines():
        text = line.strip()
        if not text or text.startswith(("-", "#")):
            continue
        lowered = text.lower()
        if lowered in {"example", "examples", "例如", "使用示例"}:
            continue
        if (
            "://" in text
            or ":" in text
            or text.startswith(("POST ", "GET ", "curl ", "import ", "def ", "BASE_URL"))
        ):
            continue
        candidate = text.split()[0].strip("`：:，,。.;；()[]{}")
        candidate = _normalize_fallback_name(candidate)
        if candidate and candidate not in names:
            names.append(candidate)
    if not names:
        names.append("user_parser")
    return names[:8]


def _normalize_fallback_name(value: str) -> str:
    name = re.sub(r"\W+", "_", value.strip().lower(), flags=re.ASCII).strip("_")
    if not name:
        return ""
    if name[0].isdigit():
        name = f"tool_{name}"
    return name


def _fallback_secrets_for_entry(source_text: str, name: str) -> list[str]:
    secrets = sorted(set(re.findall(r"\b[A-Z][A-Z0-9_]*(?:API_KEY|AUTHKEY|TOKEN|SECRET|KEY)\b", source_text)))
    if name == "siliconflow_deepseekocr" and "SILICONFLOW_API_KEY" not in secrets:
        secrets.append("SILICONFLOW_API_KEY")
    return secrets


def _fallback_module_code(specs: list[dict[str, Any]], *, reason: str) -> str:
    unavailable = {str(spec["name"]): reason for spec in specs}
    return (
        "TOOL_SPECS = "
        + json.dumps(specs, ensure_ascii=False, indent=4)
        + "\n\nUNAVAILABLE_TOOLS = "
        + json.dumps(unavailable, ensure_ascii=False, indent=4)
        + "\n\nTOOL_HANDLERS = {}\n"
    )


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
        "cmd/tool.py source:",
        _cmd_tool_source(),
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
        "Return exactly one <full_file_code> tag containing one ```python fenced code block with the full module.\n"
        "End tool-request turns with: please run the tool and paste the results below:\n"
        "When the generated module is accepted, respond with <status>mission_complete</status>.\n\n"
        + _runtime_contract_header()
    )


def _runtime_contract_header() -> str:
    return (
        "The generated file must define TOOL_SPECS, TOOL_HANDLERS, and UNAVAILABLE_TOOLS.\n"
        "TOOL_SPECS must faithfully describe each tool in the cmd/tool shape: name, scope, cost, desc, secrets, flags.\n"
        "Use the provided sample module and ToolSpec parser as the exact internal schema.\n"
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

    text = extract_pseudo_xml(text, "full_file_code") or text
    text = extract_md_codeblock(text) or text
    if not text:
        raise RuntimeError("generated user toolbox is empty")
    return text + "\n"


def _cmd_tool_source() -> str:
    return Path(__file__).resolve().parents[1].joinpath("cmd", "tool.py").read_text(encoding="utf-8")


def _program_unavailable_reasons(tool_specs: list[ToolSpec]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for spec in tool_specs:
        missing = [name for name in spec.secrets if not os.getenv(name)]
        if missing:
            reasons[spec.name] = f"missing required env vars: {', '.join(missing)}"
    return reasons


def _validate_user_tools(
    *,
    target_path: Path,
    result_validator: ResultValidator | None = None,
    logger,
) -> dict[str, Any]:
    module, module_error = load_user_toolbox_module(module_path=target_path)
    failures: list[ValidationRecord] = []
    records: list[ValidationRecord] = []
    enabled: list[str] = []
    enabled_specs: list[ToolSpec] = []
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
        enabled_specs.append(spec)
        logger.info("Generated toolbox validation passed for %s", spec.name)
        records.append(record)

    if not failures and result_validator is not None:
        try:
            result_records = list(result_validator(target_path, enabled_specs))
        except Exception as exc:
            result_records = [
                ValidationRecord(
                    tool="__result_validation__",
                    ok=False,
                    exception=f"result validation failed to run: {exc!r}",
                )
            ]

        for record in result_records:
            records.append(record)
            if record.ok:
                logger.info("Generated toolbox result validation passed for %s", record.tool)
                continue
            failures.append(record)
            logger.error(
                "Generated toolbox result validation failed for %s: %s",
                record.tool,
                record.exception or record.details,
            )

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
        "The generated file failed validation. Return a full replacement for user_toolbox.py inside exactly one ```python fenced code block.\n\n"
        "Validation may report structural errors, unavailable tools, execution failures, or output-quality issues from parser results.\n"
        "Choose the smallest coherent code change that makes the generated tools satisfy the reported target.\n"
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
