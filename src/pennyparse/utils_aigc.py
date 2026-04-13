from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ._client import ChatClient, ChatSession
from .config import get_chat_settings, get_prompt_text, inject_prompt_context, pp_config, read_package_text
from .logger import get_logger
from .utils import extract_md_codeblock

USER_TOOLBOX_SCHEMA = {
    "schema_version": {"type": "int", "required": True, "const": 1},
    "claim": {"type": "str", "required": False},
    "tool": {
        "type": "list[table]",
        "required": True,
        "item_schema": {
            "name": {"type": "str", "required": True},
            "kind": {"type": "str", "required": True, "enum": ["user"]},
            "scope": {"type": "str", "required": True},
            "cost": {"type": "str", "required": True},
            "summary": {"type": "str", "required": True},
            "result_kind": {"type": "str", "required": True, "enum": ["text", "json", "binary"]},
            "secret": {"type": "list[str]", "required": False},
            "api_reference": {"type": "str", "required": False},
            "notes": {"type": "str", "required": False},
            "params": {
                "type": "list[table]",
                "required": False,
                "item_schema": {
                    "name": {"type": "str", "required": True},
                    "type": {"type": "str", "required": True},
                    "required": {"type": "bool", "required": False},
                    "help": {"type": "str", "required": False},
                },
            },
        },
    },
}


class AigcError(RuntimeError):
    pass


class Txt2TomlError(AigcError):
    pass


@dataclass(slots=True)
class Txt2TomlValidationError:
    path: str
    message: str


def infer_user_toolbox_toml_from_text(
    source_text: str,
    *,
    logger=None,
    max_turns: int | None = None,
) -> str:
    logger = logger or get_logger("utils_aigc")
    chat_settings = get_chat_settings()
    if not chat_settings.get("model"):
        raise Txt2TomlError("toolbox TXT inference requires a configured chat model")

    turns = max_turns or int(pp_config["aigc.agent"]["loop_turns_max"])
    base_prompt = inject_prompt_context(
        get_prompt_text("to_toml"),
        {
            "__toml_template__": read_package_text("pennyparse.toolbox_user.example.toml").strip(),
            "__toolbox_txt__": source_text.strip(),
            "__toolbox_schema__": json.dumps(USER_TOOLBOX_SCHEMA, ensure_ascii=False, indent=2),
        },
    )

    session = ChatSession()
    session.system(base_prompt)

    with ChatClient(**chat_settings) as client:
        last_error = "TXT to TOML inference did not produce usable output"
        for turn in range(1, turns + 1):
            logger.info("Inferring toolbox TOML from TXT, turn %s/%s", turn, turns)
            session.user(_repair_or_initial_prompt(turn=turn))
            message = client.complete(session)
            rendered = _extract_model_text(message.get("content"))
            try:
                validated = validate_user_toolbox_toml(rendered)
            except Txt2TomlError as exc:
                last_error = str(exc)
                logger.warning("TXT to TOML validation failed on turn %s: %s", turn, exc)
                session.user(_repair_feedback(rendered, str(exc)))
                continue
            return validated

    raise Txt2TomlError(last_error)


def validate_user_toolbox_toml(toml_text: str) -> str:
    try:
        payload = tomllib.loads(toml_text)
    except tomllib.TOMLDecodeError as exc:
        raise Txt2TomlError(f"model returned invalid toolbox TOML: {exc}") from exc

    errors = _validate_top_level(payload)
    if errors:
        error_text = "; ".join(f"{error.path}: {error.message}" for error in errors)
        raise Txt2TomlError(f"toolbox TOML schema validation failed: {error_text}")
    return toml_text + ("\n" if not toml_text.endswith("\n") else "")


def write_inferred_user_toolbox_toml(
    txt_path: Path,
    toml_path: Path,
    *,
    logger=None,
    max_turns: int | None = None,
) -> Path:
    logger = logger or get_logger("utils_aigc")
    source_text = txt_path.read_text(encoding="utf-8")
    inferred = infer_user_toolbox_toml_from_text(source_text, logger=logger, max_turns=max_turns)
    toml_path.write_text(inferred, encoding="utf-8")
    logger.info("Wrote inferred toolbox metadata to %s", toml_path)
    return toml_path


def _extract_model_text(content: Any) -> str:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            str(part.get("text", "")) if isinstance(part, Mapping) else str(part)
            for part in content
        ).strip()
    else:
        raise Txt2TomlError("chat completion did not return textual content")

    text = extract_md_codeblock(text) or text
    if not text:
        raise Txt2TomlError("chat completion returned empty content")
    return text


def _repair_or_initial_prompt(*, turn: int) -> str:
    if turn == 1:
        return "Convert the provided toolbox TXT into PennyParse toolbox TOML. Return TOML only."
    return "Return a full corrected toolbox TOML replacement. Return TOML only."


def _repair_feedback(previous_toml: str, error_text: str) -> str:
    return (
        "The previous toolbox TOML failed schema validation.\n\n"
        f"Validation errors:\n{error_text}\n\n"
        "Previous TOML output:\n"
        f"{previous_toml}\n"
    )


def _validate_top_level(payload: Mapping[str, Any]) -> list[Txt2TomlValidationError]:
    errors: list[Txt2TomlValidationError] = []

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        errors.append(Txt2TomlValidationError("schema_version", "must equal 1"))

    claim = payload.get("claim")
    if claim is not None and not isinstance(claim, str):
        errors.append(Txt2TomlValidationError("claim", "must be a string when provided"))

    tools = payload.get("tool")
    if not isinstance(tools, list) or not tools:
        errors.append(Txt2TomlValidationError("tool", "must be a non-empty array of tables"))
        return errors

    for index, tool in enumerate(tools):
        if not isinstance(tool, Mapping):
            errors.append(Txt2TomlValidationError(f"tool[{index}]", "must be a table"))
            continue
        errors.extend(_validate_tool(tool, index=index))
    return errors


def _validate_tool(tool: Mapping[str, Any], *, index: int) -> list[Txt2TomlValidationError]:
    prefix = f"tool[{index}]"
    errors: list[Txt2TomlValidationError] = []

    for key in ("name", "kind", "scope", "cost", "summary", "result_kind"):
        if not isinstance(tool.get(key), str) or not str(tool.get(key)).strip():
            errors.append(Txt2TomlValidationError(f"{prefix}.{key}", "must be a non-empty string"))

    if tool.get("kind") != "user":
        errors.append(Txt2TomlValidationError(f"{prefix}.kind", "must equal 'user'"))

    if tool.get("result_kind") not in {"text", "json", "binary"}:
        errors.append(Txt2TomlValidationError(f"{prefix}.result_kind", "must be one of text/json/binary"))

    for key in ("api_reference", "notes"):
        value = tool.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(Txt2TomlValidationError(f"{prefix}.{key}", "must be a string when provided"))

    secrets = tool.get("secret")
    if secrets is not None:
        if not isinstance(secrets, list) or not all(isinstance(item, str) and item.strip() for item in secrets):
            errors.append(Txt2TomlValidationError(f"{prefix}.secret", "must be a list of non-empty strings"))

    params = tool.get("params")
    if params is not None:
        if not isinstance(params, list):
            errors.append(Txt2TomlValidationError(f"{prefix}.params", "must be an array of tables"))
        else:
            for param_index, param in enumerate(params):
                if not isinstance(param, Mapping):
                    errors.append(Txt2TomlValidationError(f"{prefix}.params[{param_index}]", "must be a table"))
                    continue
                errors.extend(_validate_param(param, tool_index=index, param_index=param_index))
    return errors


def _validate_param(param: Mapping[str, Any], *, tool_index: int, param_index: int) -> list[Txt2TomlValidationError]:
    prefix = f"tool[{tool_index}].params[{param_index}]"
    errors: list[Txt2TomlValidationError] = []

    for key in ("name", "type"):
        if not isinstance(param.get(key), str) or not str(param.get(key)).strip():
            errors.append(Txt2TomlValidationError(f"{prefix}.{key}", "must be a non-empty string"))

    required = param.get("required")
    if required is not None and not isinstance(required, bool):
        errors.append(Txt2TomlValidationError(f"{prefix}.required", "must be a boolean when provided"))

    help_text = param.get("help")
    if help_text is not None and not isinstance(help_text, str):
        errors.append(Txt2TomlValidationError(f"{prefix}.help", "must be a string when provided"))

    return errors
