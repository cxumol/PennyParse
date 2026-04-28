from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable, Mapping

from ..config import (
    get_builtin_toolbox_metadata,
    get_user_toolbox_path,
)
from ..logger import get_logger

USER_TOOLBOX_RUNTIME_CONTRACT = """
Generate a single Python file at ${HOME}/.pennyparse/user_toolbox.py.

The file must expose:

- TOOL_SPECS: list[dict[str, object]]
  Discovery metadata for the generated user tools.
- TOOL_HANDLERS: dict[str, callable]
  Each callable receives argv: list[str].
- UNAVAILABLE_TOOLS: dict[str, str]
  When the model decides a tool should stay disabled, write the reason here.
Handler return contract:

- str for text results
- bytes for binary results
- dict/list/scalar JSON values for json results
- or a tuple: (result_kind, value)

Constraints:

- never print business output to stdout
- log only to stderr when needed
- never hardcode secrets
- read secrets from environment variables named in the tool metadata
- prefer httpx for HTTP
- prefer subprocess for local CLI calls
- parse CLI args inside each handler with argparse
""".strip()

SAMPLE_GENERATED_USER_TOOLBOX = """import argparse
import os

import httpx

TOOL_SPECS = [
    {
        "name": "example_tool",
        "kind": "user",
        "scope": "parser",
        "cost": "medium",
        "summary": "OCR a local image through the example HTTP API.",
        "result_kind": "text",
        "secret": ["EXAMPLE_API_KEY"],
        "params": [
            {"name": "path", "type": "path", "required": True, "help": "Path to a local image file."},
            {"name": "prompt_text", "type": "string", "help": "Prompt text sent to the upstream API."},
        ],
        "api_reference": "POST https://example.invalid/ocr",
        "notes": "Return only the OCR text.",
    },
]
UNAVAILABLE_TOOLS = {}


def tool_example_tool(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(prog="pennyparse tool example_tool", add_help=False)
    parser.add_argument("--path", required=True)
    parser.add_argument("--prompt-text", default="OCR this image.")
    args = parser.parse_args(argv)

    api_key = os.environ["EXAMPLE_API_KEY"]
    payload = {"path": args.path, "prompt": args.prompt_text}
    headers = {"authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=30.0) as client:
        response = client.post("https://example.invalid/ocr", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    return data["text"]


TOOL_HANDLERS = {
    "example_tool": tool_example_tool,
}
"""

SAMPLE_DYNAMIC_IMPORT = """import importlib

def resolve_entrypoint(entrypoint: str):
    module_name, separator, attr_name = entrypoint.partition(":")
    if not separator or not module_name or not attr_name:
        raise ValueError(f"invalid entrypoint: {entrypoint!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)
"""

_RESULT_KINDS = {"text", "json", "binary"}
_TOOL_COST_LEVELS = ("very low", "low", "medium", "high", "very high")
_TOOL_SCOPES = ("previewer", "parser", "reviewer")
_DEFAULT_USER_RISK = (
    "User-defined tools may execute generated Python code and call third-party services. "
    "Review code, secrets, and upstream APIs before use."
)


class ToolError(RuntimeError):
    pass


class ToolUsageError(ToolError):
    pass


class ToolUnavailableError(ToolError):
    pass


def _normalize_cost(value: str) -> str:
    text = value.strip().lower().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    aliases = {
        "verylow": "very low",
        "vlow": "very low",
        "veryhigh": "very high",
        "vhigh": "very high",
    }
    text = aliases.get(text, text)
    if text in _TOOL_COST_LEVELS:
        return text
    raise ValueError(f"invalid cost {value!r}; expected one of: {', '.join(_TOOL_COST_LEVELS)}")


def _normalize_scope(value: str) -> str:
    text = value.strip().lower().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    aliases = {
        "planner": "previewer",
        "planning": "previewer",
        "metadata": "previewer",
        "preview": "previewer",
        "review": "reviewer",
        "parser": "parser",
    }
    text = aliases.get(text, text)
    if text in _TOOL_SCOPES:
        return text
    raise ValueError(f"invalid scope {value!r}; expected one of: {', '.join(_TOOL_SCOPES)}")


@dataclass(slots=True)
class ToolParam:
    name: str
    type: str = "string"
    required: bool = False
    help: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ToolParam":
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("param name must be a non-empty string")
        return cls(
            name=name,
            type=str(data.get("type", "string")),
            required=bool(data.get("required", False)),
            help=str(data.get("help", "")),
        )

    def flag(self) -> str:
        return f"--{self.name.replace('_', '-')}"


@dataclass(slots=True)
class ToolSpec:
    name: str
    kind: str
    scope: str
    cost: str
    summary: str
    result_kind: str
    entrypoint: str = ""
    availability: str = "always"
    availability_value: str = ""
    risk_notice: str = ""
    api_reference: str = ""
    notes: str = ""
    secret: list[str] = field(default_factory=list)
    params: list[ToolParam] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, default_risk: str = "") -> "ToolSpec":
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("tool name must be a non-empty string")

        kind = str(data.get("kind", "")).strip()
        if kind not in {"builtin", "user"}:
            raise ValueError(f"tool {name!r} has invalid kind {kind!r}")

        raw_scope = str(data.get("scope", "")).strip()
        if not raw_scope:
            raise ValueError(f"tool {name!r} is missing scope")
        scope = _normalize_scope(raw_scope)

        raw_cost = str(data.get("cost", "")).strip()
        if not raw_cost:
            raise ValueError(f"tool {name!r} is missing cost")
        cost = _normalize_cost(raw_cost)

        summary = str(data.get("summary") or data.get("desc") or "").strip()
        if not summary:
            raise ValueError(f"tool {name!r} is missing summary")

        result_kind = str(data.get("result_kind", "")).strip()
        if result_kind not in _RESULT_KINDS:
            raise ValueError(f"tool {name!r} has invalid result_kind {result_kind!r}")

        params = [ToolParam.from_mapping(item) for item in data.get("params", []) or []]
        secret = [str(item) for item in (data.get("secret") or data.get("secrets") or [])]
        return cls(
            name=name,
            kind=kind,
            scope=scope,
            cost=cost,
            summary=summary,
            result_kind=result_kind,
            entrypoint=str(data.get("entrypoint", "")),
            availability=str(data.get("availability", "always")),
            availability_value=str(data.get("availability_value", "")),
            risk_notice=str(data.get("risk_notice", "") or default_risk or _DEFAULT_USER_RISK),
            api_reference=str(data.get("api_reference", "")),
            notes=str(data.get("notes", "")),
            secret=secret,
            params=params,
        )

    def usage(self) -> str:
        parts = [f"pennyparse tool {self.name}"]
        for param in self.params:
            token = f"{param.flag()} VALUE" if param.type != "bool" else param.flag()
            if param.required:
                parts.append(token)
            else:
                parts.append(f"[{token}]")
        return " ".join(parts)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "scope": self.scope,
            "cost": self.cost,
            "summary": self.summary,
            "result_kind": self.result_kind,
            "secret": list(self.secret),
            "params": [
                {
                    "name": param.name,
                    "type": param.type,
                    "required": param.required,
                    "help": param.help,
                }
                for param in self.params
            ],
            "api_reference": self.api_reference,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ToolAvailability:
    available: bool
    reason: str = ""
    source: str = "runtime"


@dataclass(slots=True)
class DiscoveredTool:
    spec: ToolSpec
    availability: ToolAvailability


@dataclass(slots=True)
class ToolInstance:
    name: str
    enabled: bool
    disable_reason: str
    cost: str
    scope: str
    desc: str
    secrets: list[str]
    flags: dict[str, str]

    @property
    def __name__(self) -> str:
        return self.name


@dataclass(slots=True)
class ToolExecutionResult:
    kind: str
    value: Any


def load_builtin_specs() -> list[ToolSpec]:
    catalog = get_builtin_toolbox_metadata()
    default_risk = str(catalog.get("claim", "")).strip()
    return [ToolSpec.from_mapping(item, default_risk=default_risk) for item in catalog.get("tool", []) or []]


def load_user_specs(
    *,
    module: ModuleType | None = None,
    module_path: Path | None = None,
) -> tuple[list[ToolSpec], str | None]:
    owned_module = module
    if owned_module is None:
        owned_module, module_error = load_user_toolbox_module(module_path=module_path)
        if module_error:
            return [], module_error

    assert owned_module is not None
    raw_specs = getattr(owned_module, "TOOL_SPECS", None)
    if raw_specs is None:
        return [], "user toolbox does not expose TOOL_SPECS"
    if not isinstance(raw_specs, list) or not raw_specs:
        return [], "user toolbox TOOL_SPECS must be a non-empty list"

    raw_risk = getattr(owned_module, "TOOLBOX_RISK_NOTICE", "")
    default_risk = str(raw_risk).strip() or _DEFAULT_USER_RISK
    specs: list[ToolSpec] = []
    for index, item in enumerate(raw_specs):
        if not isinstance(item, Mapping):
            return [], f"user toolbox TOOL_SPECS[{index}] must be a mapping"
        try:
            specs.append(ToolSpec.from_mapping(item, default_risk=default_risk))
        except ValueError as exc:
            return [], f"user toolbox TOOL_SPECS[{index}] is invalid: {exc}"
    return specs, None


def load_user_toolbox_module(*, module_path: Path | None = None) -> tuple[ModuleType | None, str | None]:
    path = module_path or get_user_toolbox_path()
    if not path.exists():
        return None, f"{path} not found"

    spec = importlib.util.spec_from_file_location("pennyparse_user_toolbox", path)
    if spec is None or spec.loader is None:
        return None, f"failed to load module spec from {path}"

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - import failures depend on generated user code
        return None, f"failed to import {path}: {exc!r}"
    return module, None


def discover_builtin_tools(*, logger=None) -> list[DiscoveredTool]:
    logger = logger or get_logger("cmd.tool")
    discovered: list[DiscoveredTool] = []
    for spec in load_builtin_specs():
        availability = _check_builtin_availability(spec)
        discovered.append(DiscoveredTool(spec=spec, availability=availability))
        _log_unavailable(logger, spec, availability)
    return discovered


def discover_user_tools(*, cwd: Path | None = None, logger=None) -> list[DiscoveredTool]:
    logger = logger or get_logger("cmd.tool")
    module, module_error = load_user_toolbox_module()
    if module_error:
        logger.debug("Skipping user tool discovery: %s", module_error)
        return []

    assert module is not None
    specs, specs_error = load_user_specs(module=module)
    if specs_error:
        logger.warning("Skipping user tool discovery: %s", specs_error)
        return []

    discovered: list[DiscoveredTool] = []
    for spec in specs:
        availability = _check_user_availability(spec, module=module, module_error=module_error)
        discovered.append(DiscoveredTool(spec=spec, availability=availability))
        _log_unavailable(logger, spec, availability)
    return discovered


def list_tools(*, cwd: Path | None = None, logger=None, scope: str | None = None) -> str:
    logger = logger or get_logger("cmd.tool")
    scope_filter = scope or _read_scope_filter(sys.argv[1:])
    if scope_filter is not None:
        try:
            scope_filter = _normalize_scope(scope_filter)
        except ValueError:
            return f"Invalid --scope {scope_filter!r}. Expected: {', '.join(_TOOL_SCOPES)}\n"

    discovered = [*discover_builtin_tools(logger=logger), *discover_user_tools(cwd=cwd, logger=logger)]
    tools = [_tool_instance(item) for item in discovered]
    if scope_filter is not None:
        tools = [tool for tool in tools if tool.scope == scope_filter]

    lines: list[str] = []
    for tool in tools:
        if not tool.enabled:
            continue
        header = f"{tool.name}\tscope: {tool.scope} cost: {tool.cost}\t{tool.desc}"
        if tool.flags:
            flag_lines = [
                f"\t--{key} {value}".rstrip()
                for key, value in tool.flags.items()
            ]
            lines.append(header + "\n" + "\n".join(flag_lines))
        else:
            lines.append(header)
    return "\n\n".join(lines)


def describe_tool(name: str, *, cwd: Path | None = None, logger=None) -> str:
    discovered = _find_tool(name, cwd=cwd, logger=logger)
    return _format_tool_help(discovered)


def run_tool(name: str, argv: list[str], *, cwd: Path | None = None, logger=None) -> ToolExecutionResult:
    logger = logger or get_logger("cmd.tool")
    discovered = _find_tool(name, cwd=cwd, logger=logger)
    if _wants_help(argv):
        return ToolExecutionResult(kind="text", value=_format_tool_help(discovered))

    if not discovered.availability.available:
        raise ToolUnavailableError(
            f"{discovered.spec.name} is unavailable: {discovered.availability.reason or 'unknown reason'}"
        )

    if discovered.spec.kind == "builtin":
        handler = _builtin_handler(discovered.spec.name)
        raw_result = handler(argv)
    else:
        raw_result = _run_user_tool(discovered.spec, argv)
    return coerce_tool_result(raw_result, expected_kind=discovered.spec.result_kind, tool_name=name)


def coerce_tool_result(result: Any, *, expected_kind: str | None = None, tool_name: str = "") -> ToolExecutionResult:
    kind: str
    value: Any

    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], str)
        and result[0] in _RESULT_KINDS
    ):
        kind = result[0]
        value = result[1]
    elif hasattr(result, "kind") and hasattr(result, "value"):
        kind = getattr(result, "kind")
        value = getattr(result, "value")
    elif isinstance(result, (bytes, bytearray, memoryview)):
        kind = "binary"
        value = bytes(result)
    elif isinstance(result, str):
        kind = "text"
        value = result
    elif isinstance(result, (dict, list, int, float, bool)) or result is None:
        kind = "json"
        value = result
    else:
        raise ToolUsageError(f"{tool_name or 'tool'} returned unsupported result type: {type(result).__name__}")

    if expected_kind and kind != expected_kind:
        raise ToolUsageError(
            f"{tool_name or 'tool'} returned {kind}, but metadata declares {expected_kind}"
        )
    return ToolExecutionResult(kind=kind, value=value)


def _find_tool(name: str, *, cwd: Path | None = None, logger=None) -> DiscoveredTool:
    logger = logger or get_logger("cmd.tool")
    for discovered in [*discover_builtin_tools(logger=logger), *discover_user_tools(cwd=cwd, logger=logger)]:
        if discovered.spec.name == name:
            return discovered
    raise ToolUsageError(f"unknown tool: {name}")


def _format_param(param: ToolParam) -> str:
    token = f"{param.flag()} <{param.type}>"
    return token if param.required else f"[{token}]"


def _read_scope_filter(argv: list[str]) -> str | None:
    key = "--scope"
    prefix = f"{key}="
    for idx, token in enumerate(argv):
        if token == key:
            if idx + 1 < len(argv):
                return argv[idx + 1]
            return ""
        if token.startswith(prefix):
            return token[len(prefix) :]
    return None


def _tool_instance(discovered: DiscoveredTool) -> ToolInstance:
    spec = discovered.spec
    return ToolInstance(
        name=spec.name,
        enabled=discovered.availability.available,
        disable_reason=discovered.availability.reason or "",
        cost=spec.cost,
        scope=spec.scope,
        desc=spec.summary,
        secrets=list(spec.secret),
        flags=_tool_flags(spec),
    )


def _tool_flags(spec: ToolSpec) -> dict[str, str]:
    flags: dict[str, str] = {}
    for param in spec.params:
        key = param.flag().lstrip("-")
        flags[key] = _flag_value_example(param.type, tool_name=spec.name)
    return flags


def _flag_value_example(param_type: str, *, tool_name: str) -> str:
    param_type = param_type.strip().lower()
    if param_type == "bool":
        return ""
    if param_type == "path":
        suffix = ""
        lowered = tool_name.lower()
        if "pdf" in lowered:
            suffix = ".pdf"
        elif "img" in lowered or "image" in lowered:
            suffix = ".png"
        return f"/path/to/file{suffix}"
    if param_type == "int":
        return "0"
    if param_type == "float":
        return "0.0"
    return "<value>"


def _format_tool_help(discovered: DiscoveredTool) -> str:
    spec = discovered.spec
    availability = "yes" if discovered.availability.available else "no"
    params = spec.params or []
    lines = [
        f"ToolName: {spec.name}",
        f"Usage: {spec.usage()}",
        f"Kind: {spec.kind}",
        f"Scope: {spec.scope or '-'}",
        f"Cost: {spec.cost or '-'}",
        f"Summary: {spec.summary or '-'}",
        f"ResultKind: {spec.result_kind}",
        f"Risk: {spec.risk_notice or '-'}",
        f"Available: {availability}",
    ]
    if discovered.availability.reason:
        lines.append(f"UnavailableReason: {discovered.availability.reason}")
    if params:
        lines.append("Params:")
        for param in params:
            required = "required" if param.required else "optional"
            lines.append(f"  {param.flag()} ({param.type}, {required}) {param.help}".rstrip())
    if spec.secret:
        lines.append(f"Secrets: {', '.join(spec.secret)}")
    return "\n".join(lines) + "\n"


def _wants_help(argv: Iterable[str]) -> bool:
    return any(arg in {"-h", "--help"} for arg in argv)


def _log_unavailable(logger, spec: ToolSpec, availability: ToolAvailability) -> None:
    if availability.available or not availability.reason:
        return
    logger.warning(
        "Tool %s is unavailable (%s): %s",
        spec.name,
        availability.source,
        availability.reason,
    )


def _missing_secrets(spec: ToolSpec) -> list[str]:
    return [name for name in spec.secret if not os.getenv(name)]


def _check_builtin_availability(spec: ToolSpec) -> ToolAvailability:
    missing = _missing_secrets(spec)
    if missing:
        return ToolAvailability(False, f"missing required env vars: {', '.join(missing)}", "program_rule")

    if spec.availability == "python_module" and spec.availability_value:
        if importlib.util.find_spec(spec.availability_value) is None:
            return ToolAvailability(
                False,
                f"python module {spec.availability_value!r} is not importable",
                "runtime",
            )
    return ToolAvailability(True)


def _check_user_availability(
    spec: ToolSpec,
    *,
    module: ModuleType | None,
    module_error: str | None,
) -> ToolAvailability:
    missing = _missing_secrets(spec)
    if missing:
        return ToolAvailability(False, f"missing required env vars: {', '.join(missing)}", "program_rule")

    if module_error:
        return ToolAvailability(False, module_error, "runtime")

    assert module is not None
    unavailable = getattr(module, "UNAVAILABLE_TOOLS", {})
    if isinstance(unavailable, Mapping):
        reason = unavailable.get(spec.name)
        if isinstance(reason, str) and reason.strip():
            return ToolAvailability(False, reason.strip(), "llm")

    handler = _resolve_user_handler(module, spec.name)
    if handler is None:
        return ToolAvailability(
            False,
            f"user toolbox does not expose a handler for {spec.name}",
            "runtime",
        )
    return ToolAvailability(True)


def _builtin_handler(name: str) -> Callable[[list[str]], Any]:
    handlers: dict[str, Callable[[list[str]], Any]] = {
        "img_metadata_px": img_metadata_px,
        "img_thumb": img_thumb,
        "pdf_metadata": pdf_metadata,
        "pdf2txt": pdf2txt,
        "pandoc2txt": pandoc2txt,
    }
    try:
        return handlers[name]
    except KeyError as exc:  # pragma: no cover - metadata/handler drift
        raise ToolUsageError(f"builtin tool handler missing for {name}") from exc


def _run_user_tool(spec: ToolSpec, argv: list[str]) -> Any:
    module, module_error = load_user_toolbox_module()
    if module_error:
        raise ToolUnavailableError(module_error)
    assert module is not None
    handler = _resolve_user_handler(module, spec.name)
    if handler is None:
        raise ToolUnavailableError(f"user toolbox handler missing for {spec.name}")
    return handler(argv)


def _resolve_user_handler(module: ModuleType, tool_name: str) -> Callable[[list[str]], Any] | None:
    handlers = getattr(module, "TOOL_HANDLERS", None)
    if isinstance(handlers, Mapping):
        handler = handlers.get(tool_name)
        if callable(handler):
            return handler
    return None


def _read_image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return image.width, image.height


def img_metadata_px(argv: list[str]) -> dict[str, int]:
    parser = argparse.ArgumentParser(prog="pennyparse tool img_metadata_px", add_help=False)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().resolve()
    width, height = _read_image_size(path)
    return {"width": width, "height": height}


def img_thumb(argv: list[str]) -> bytes:
    parser = argparse.ArgumentParser(prog="pennyparse tool img_thumb", add_help=False)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().resolve()

    from PIL import Image

    with Image.open(path) as image:
        thumb = image.copy()
        thumb.thumbnail((360, 360))
        buffer = io.BytesIO()
        thumb.save(buffer, format="PNG")
        return buffer.getvalue()


def pdf_metadata(argv: list[str]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(prog="pennyparse tool pdf_metadata", add_help=False)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().resolve()

    import pymupdf

    with pymupdf.open(path) as document:
        return {
            "page_count": document.page_count,
            "word_count": sum(len(page.get_text("words")) for page in document),
            "toc": document.get_toc(),
        }


def pdf2txt(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(prog="pennyparse tool pdf2txt", add_help=False)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().resolve()

    import pymupdf

    with pymupdf.open(path) as document:
        return chr(12).join(page.get_text() for page in document)


def pandoc2txt(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(prog="pennyparse tool pandoc2txt", add_help=False)
    parser.add_argument("--path", required=True)
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().resolve()

    import pypandoc

    return pypandoc.convert_file(str(path), to="plain")

def prompt_builtin_contract_json() -> str:
    return json.dumps([spec.to_prompt_dict() for spec in load_builtin_specs()], ensure_ascii=False, indent=2)
