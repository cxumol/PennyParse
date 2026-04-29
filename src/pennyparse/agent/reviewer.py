from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Literal

from .._client import ChatClient, ChatSession
from ..config import load_pp_config
from ..logger import get_logger
from ..utils import extract_md_codeblock

ReviewStatus = Literal["pass", "minor_revision", "major_revision"]
_AGENT_IMPL_MODE = "tool_calls"


@dataclass(slots=True)
class ReviewOutcome:
    status: ReviewStatus
    text: str
    message: str

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "minor_revision"}

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "text": self.text,
            "message": self.message,
        }


@dataclass(slots=True)
class _PatchAudit:
    ok: bool
    revised: str
    summary: str
    message: str
    patch_count: int = 0
    replacement_count: int = 0


_REVIEWER_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "myregexpatch",
            "description": (
                "Apply a chain of re.sub patches to the original parser text and "
                "return an audit summary. Every call is evaluated against the "
                "initial text received by this reviewer, not a previous revision."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "before_len": {"type": "integer"},
                    "after_len": {"type": "integer"},
                    "patches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pattern": {"type": "string"},
                                "repl": {"type": "string"},
                                "count": {"type": "integer"},
                                "flags": {"type": ["string", "integer"]},
                            },
                            "required": ["pattern", "repl"],
                        },
                    },
                },
                "required": ["before_len", "after_len", "patches"],
            },
        },
    }
]


def review_text(
    text: str,
    *,
    source_path: Path | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    logger=None,
) -> ReviewOutcome:
    logger = logger or get_logger("agent.reviewer")
    pp_cfg = load_pp_config(cwd=cwd, home=home)
    max_length = _review_max_length(pp_cfg)
    candidate = text[:max_length]

    if not candidate.strip():
        return ReviewOutcome(
            status="major_revision",
            text=text,
            message="The reviewer found current given result need a major revision.",
        )

    chat_settings = _chat_settings(pp_cfg)
    if not chat_settings.get("model"):
        return ReviewOutcome(
            status="pass",
            text=text,
            message="The reviewer found current given result is good.",
        )

    try:
        return _review_with_llm(
            candidate,
            original=text,
            source_path=source_path,
            chat_settings=chat_settings,
            max_iter=_review_max_iter(pp_cfg),
        )
    except Exception as exc:
        logger.info("LLM review skipped: %s", exc)
        return ReviewOutcome(
            status="pass",
            text=text,
            message="The reviewer found current given result is good.",
        )


def _review_max_length(pp_cfg: Mapping[str, Any]) -> int:
    output = _as_mapping(pp_cfg.get("output"))
    reviewer = _as_mapping(pp_cfg.get("reviewer"))
    value = output.get("max_length", reviewer.get("max_length"))
    if value is None:
        raise RuntimeError("reviewer.max_length must be configured")
    return max(1, int(value))


def _review_max_iter(pp_cfg: Mapping[str, Any]) -> int:
    agent = _as_mapping(_as_mapping(pp_cfg.get("aigc")).get("agent"))
    return max(1, int(agent.get("max_iter") or 5))


def _chat_settings(pp_cfg: Mapping[str, Any]) -> dict[str, Any]:
    chat = _as_mapping(_as_mapping(_as_mapping(pp_cfg.get("aigc")).get("api")).get("chatcomp"))
    return {
        "base_url": str(chat.get("base") or "").strip(),
        "api_key": str(chat.get("authkey") or "").strip() or None,
        "model": str(chat.get("model") or "").strip() or None,
    }


def _review_with_llm(
    candidate: str,
    *,
    original: str,
    source_path: Path | None,
    chat_settings: Mapping[str, Any],
    max_iter: int,
) -> ReviewOutcome:
    session = ChatSession()
    session.system(
        "Review one parsed document audit fragment in tool_calls mode. The "
        "supplied text may be a truncated prefix of a longer parser result. "
        "Return one of three decisions: pass, minor_revision, major_revision. "
        "For safe text fixes, call myregexpatch with a re.sub patch chain, "
        "before_len, and after_len. Every myregexpatch call must target the "
        "initial full parser text length, not the result of a previous call. "
        "After a tool audit, continue from the previous patch suggestion and "
        "the audit summary only; do not ask for or return revised full text. "
        "When no more fixes are needed, return JSON only with status and "
        "message. Use major_revision for empty, broken, or obviously "
        "incomplete extraction."
    )
    session.user(
        json.dumps(
            {
                "source_path": str(source_path) if source_path else "",
                "text": candidate,
                "text_length": len(original),
                "prompt_text_length": len(candidate),
                "truncated": len(candidate) < len(original),
            },
            ensure_ascii=False,
        )
    )

    last_audit: _PatchAudit | None = None
    with ChatClient(**dict(chat_settings)) as client:
        for _ in range(max_iter):
            assistant = client.complete(
                session,
                temperature=0,
                tools=_REVIEWER_TOOLS,
                tool_choice="auto",
            )
            _ensure_assistant_recorded(session, assistant)
            tool_calls = assistant.get("tool_calls") or []
            if tool_calls:
                for call in tool_calls:
                    audit = _run_reviewer_tool_call(call, original)
                    if audit.ok:
                        last_audit = audit
                    session.tool(
                        json.dumps(
                            {
                                "ok": audit.ok,
                                "summary": audit.summary,
                                "message": audit.message,
                                "patch_count": audit.patch_count,
                                "replacement_count": audit.replacement_count,
                                "before_len": len(original),
                                "after_len": len(audit.revised) if audit.ok else None,
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id=str(call.get("id") or ""),
                        name=_tool_call_name(call) or "myregexpatch",
                    )
                continue

            return _review_content_outcome(
                assistant.get("content"),
                original=original,
                last_audit=last_audit,
            )

    if last_audit is not None:
        return ReviewOutcome(
            status="minor_revision",
            text=last_audit.revised,
            message=last_audit.message or last_audit.summary,
        )
    return ReviewOutcome(
        status="major_revision",
        text=original,
        message="The reviewer did not reach a final decision.",
    )


def _review_content_outcome(
    content: Any,
    *,
    original: str,
    last_audit: _PatchAudit | None,
) -> ReviewOutcome:
    payload = extract_md_codeblock(content) if isinstance(content, str) else ""
    if not payload and isinstance(content, str):
        payload = content
    data = json.loads(payload)
    status = data.get("status")
    if status not in {"pass", "minor_revision", "major_revision"}:
        raise RuntimeError(f"invalid reviewer status: {status!r}")
    message = str(data.get("message") or "").strip()

    if status == "minor_revision":
        patches = data.get("patches")
        if patches:
            try:
                revised = _apply_regex_patches(original, patches)
            except RuntimeError as exc:
                return ReviewOutcome(
                    status="major_revision",
                    text=original,
                    message=message or str(exc),
                )
            return ReviewOutcome(status="minor_revision", text=revised, message=message)
        if last_audit is not None:
            return ReviewOutcome(
                status="minor_revision",
                text=last_audit.revised,
                message=message or last_audit.message or last_audit.summary,
            )
        return ReviewOutcome(
            status="major_revision",
            text=original,
            message=message or "minor_revision requires a valid myregexpatch",
        )
    if status == "major_revision":
        return ReviewOutcome(
            status="major_revision",
            text=original,
            message=message or "The reviewer found current given result need a major revision.",
        )
    return ReviewOutcome(
        status="pass",
        text=original,
        message=message or "The reviewer found current given result is good.",
    )


def _ensure_assistant_recorded(session: ChatSession, assistant: Mapping[str, Any]) -> None:
    if not session.messages or session.messages[-1] != assistant:
        session.messages.append(dict(assistant))


def _run_reviewer_tool_call(call: Mapping[str, Any], original: str) -> _PatchAudit:
    name = _tool_call_name(call)
    if name != "myregexpatch":
        return _PatchAudit(
            ok=False,
            revised=original,
            summary=f"unknown reviewer tool: {name or '<missing>'}",
            message="Reviewer can only call myregexpatch.",
        )

    arguments, error = _tool_call_arguments(call)
    if error:
        return _PatchAudit(ok=False, revised=original, summary=error, message=error)

    before_len = arguments.get("before_len")
    if before_len != len(original):
        message = f"before_len mismatch: expected {len(original)}, got {before_len!r}"
        return _PatchAudit(ok=False, revised=original, summary=message, message=message)

    try:
        revised, replacement_count = _apply_regex_patches_with_count(original, arguments.get("patches"))
    except RuntimeError as exc:
        message = str(exc)
        return _PatchAudit(ok=False, revised=original, summary=message, message=message)

    after_len = arguments.get("after_len")
    if after_len != len(revised):
        message = f"after_len mismatch: expected {len(revised)}, got {after_len!r}"
        return _PatchAudit(ok=False, revised=original, summary=message, message=message)

    patches = arguments.get("patches")
    patch_count = len(patches) if isinstance(patches, list) else 0
    summary = (
        f"Applied {patch_count} re.sub patch(es) to initial text; "
        f"{replacement_count} replacement(s); length {len(original)} -> {len(revised)}."
    )
    return _PatchAudit(
        ok=True,
        revised=revised,
        summary=summary,
        message=str(arguments.get("message") or "").strip(),
        patch_count=patch_count,
        replacement_count=replacement_count,
    )


def _tool_call_name(call: Mapping[str, Any]) -> str:
    function = _as_mapping(call.get("function"))
    return str(function.get("name") or "").strip()


def _tool_call_arguments(call: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    function = _as_mapping(call.get("function"))
    raw = function.get("arguments") or "{}"
    if isinstance(raw, Mapping):
        return dict(raw), ""
    try:
        data = json.loads(str(raw))
    except Exception as exc:
        return {}, f"invalid myregexpatch arguments JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "myregexpatch arguments must be a JSON object"
    return data, ""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _apply_regex_patches(text: str, patches: Any) -> str:
    return _apply_regex_patches_with_count(text, patches)[0]


def _apply_regex_patches_with_count(text: str, patches: Any) -> tuple[str, int]:
    if not isinstance(patches, list) or not patches:
        raise RuntimeError("minor_revision requires non-empty regex patches")

    revised = text
    total_replacements = 0
    for patch in patches:
        item = _as_mapping(patch)
        pattern = item.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise RuntimeError("minor_revision patch requires pattern")
        repl = item.get("repl")
        if not isinstance(repl, str):
            raise RuntimeError("minor_revision patch requires repl")
        count = int(item.get("count") or 0)
        flags = _regex_flags(item.get("flags"))
        revised, replacements = re.subn(pattern, repl, revised, count=count, flags=flags)
        total_replacements += replacements
    return revised, total_replacements


def _regex_flags(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        flags = 0
        for name in re.split(r"[|,\s]+", value.strip()):
            if not name:
                continue
            attr = name if name.startswith("re.") else f"re.{name}"
            try:
                flags |= int(getattr(re, attr.removeprefix("re.")))
            except AttributeError as exc:
                raise RuntimeError(f"invalid regex flag: {name}") from exc
        return flags
    raise RuntimeError("invalid regex flags")
