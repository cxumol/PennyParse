from __future__ import annotations

import importlib
import json
import threading
import sys
from pathlib import Path
from typing import Any

import typer
from typing_extensions import Annotated

from .config import (
    PENNYPARSE_CHAT_ENV_REMINDER,
    PENNYPARSE_HOST,
    PENNYPARSE_PORT,
    get_user_toolbox_path,
    has_pennyparse_chat_env,
    pp_config,
)
from .logger import configure_logging, get_logger

app = typer.Typer(name="pennyparse", help="PennyParse CLI", no_args_is_help=True)
init_app = typer.Typer(name="init", help="Initialize generated assets")
app.add_typer(init_app, name="init")

_INIT_TOOLS_ENTRYPOINT = "pennyparse.cmd.init_tools:run_init_tools"
_INIT_DOCS_ENTRYPOINT = "pennyparse.cmd.init_docs:run_init_docs"
_LIST_TOOLS_ENTRYPOINT = "pennyparse.cmd.tool:list_tools"
_RUN_TOOL_ENTRYPOINT = "pennyparse.cmd.tool:run_tool"
_RUN_ENTRYPOINT = "pennyparse.cmd.run:run"
_TOOL_USAGE_ERROR_ENTRYPOINT = "pennyparse.cmd.tool:ToolUsageError"
_TOOL_UNAVAILABLE_ERROR_ENTRYPOINT = "pennyparse.cmd.tool:ToolUnavailableError"
_WEB_SERVE_ENTRYPOINT = "pennyparse.web:serve"

_TOOL_COMMAND_HELP = (
    "Usage:\n"
    "  pennyparse tool --list [--scope=previewer|parser|reviewer]\n"
    "  pennyparse tool <toolname> [args...]\n"
    "  pennyparse tool <toolname> --help\n"
)
_CHAT_ENV_REMINDER_SHOWN = False


def resolve_entrypoint(entrypoint: str) -> Any:
    module_name, separator, attr_name = entrypoint.partition(":")
    if not separator or not module_name or not attr_name:
        raise ValueError(f"invalid entrypoint: {entrypoint!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _write_result(kind: str, value: Any) -> None:
    if kind == "binary":
        sys.stdout.buffer.write(value)
        sys.stdout.buffer.flush()
        return

    if kind == "json":
        sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    text = str(value)
    sys.stdout.write(text)
    sys.stdout.flush()


def _warn_missing_chat_env(logger) -> None:
    global _CHAT_ENV_REMINDER_SHOWN
    if _CHAT_ENV_REMINDER_SHOWN or has_pennyparse_chat_env():
        return
    logger.warning(PENNYPARSE_CHAT_ENV_REMINDER)
    _CHAT_ENV_REMINDER_SHOWN = True


def _readline_with_timeout(prompt: str, *, timeout_s: int) -> str | None:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    if timeout_s <= 0:
        return sys.stdin.readline().strip()

    holder: dict[str, str | None] = {"line": None}

    def _reader() -> None:
        try:
            holder["line"] = sys.stdin.readline()
        except Exception:
            holder["line"] = ""

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return None
    return (holder["line"] or "").strip()


def _confirm_overwrite(path: Path) -> bool:
    if not sys.stdin.isatty():
        return False
    timeout_s = int(pp_config.get("cli", {}).get("timeout") or 0)
    answer = _readline_with_timeout(f"Overwrite {path}? [y/N] ", timeout_s=timeout_s)
    if answer is None:
        return False
    answer = answer.strip().lower()
    if not answer:
        return False
    return answer in {"y", "yes"}


@init_app.command("tools")
def init_tools(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite ~/.pennyparse/user_toolbox.py without prompting."),
    ] = False,
    source_path: Annotated[
        Path,
        typer.Option(
            "--from",
            help="Path to pennyparse.toolbox_user.txt (default: $HOME/pennyparse.toolbox_user.txt).",
        ),
    ] = Path.home() / "pennyparse.toolbox_user.txt",
):
    """Generate ~/.pennyparse/user_toolbox.py from a toolbox TXT file."""
    configure_logging()
    logger = get_logger("cli")
    _warn_missing_chat_env(logger)
    target_path = get_user_toolbox_path()
    overwrite = force or (not target_path.exists()) or _confirm_overwrite(target_path)
    if target_path.exists() and not overwrite:
        logger.error("Refusing to overwrite existing %s (use --force to override).", target_path)
        raise typer.Exit(code=1)

    run_init_tools = resolve_entrypoint(_INIT_TOOLS_ENTRYPOINT)
    try:
        summary = run_init_tools(overwrite=overwrite, source_path=source_path, logger=logger)
        _write_result("json", summary)
        logger.warning("Review %s for security before running user tools.", summary.get("result_file") or target_path)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception("init tool failed: %s", exc)
        raise typer.Exit(code=1)


@init_app.command("docs")
def init_docs(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite ./.pennyparse_memory.txt without prompting."),
    ] = False,
):
    """Initialize ./.pennyparse_memory.txt for the current docs directory."""
    configure_logging()
    logger = get_logger("cli")
    _warn_missing_chat_env(logger)
    target_path = Path.cwd() / ".pennyparse_memory.txt"
    overwrite = force or (not target_path.exists()) or _confirm_overwrite(target_path)
    if target_path.exists() and not overwrite:
        logger.error("Refusing to overwrite existing %s (use --force to override).", target_path)
        raise typer.Exit(code=1)
    run_init_docs = resolve_entrypoint(_INIT_DOCS_ENTRYPOINT)
    try:
        summary = run_init_docs(overwrite=overwrite, logger=logger)
        _write_result("json", summary)
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.exception("init docs failed: %s", exc)
        raise typer.Exit(code=1)


@app.command(
    "tool",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    add_help_option=False,
)
def tool_command(
    ctx: typer.Context,
    tool_name: Annotated[str | None, typer.Argument()] = None,
    list_only: Annotated[bool, typer.Option("--list", help="List builtin and user tools.")] = False,
    scope: Annotated[
        str | None,
        typer.Option("--scope", help="Filter --list output by previewer, parser, or reviewer."),
    ] = None,
):
    """List tools or execute a specific tool."""
    configure_logging()
    logger = get_logger("cli")
    _warn_missing_chat_env(logger)
    extra_args = list(ctx.args)
    list_tools = resolve_entrypoint(_LIST_TOOLS_ENTRYPOINT)

    if list_only:
        _write_result("text", list_tools(logger=logger, scope=scope))
        return

    if tool_name is None:
        wants_help = any(arg in {"-h", "--help"} for arg in extra_args)
        result = _TOOL_COMMAND_HELP if wants_help or not extra_args else list_tools(logger=logger, scope=scope)
        _write_result("text", result)
        return

    run_tool = resolve_entrypoint(_RUN_TOOL_ENTRYPOINT)
    ToolUsageError = resolve_entrypoint(_TOOL_USAGE_ERROR_ENTRYPOINT)
    ToolUnavailableError = resolve_entrypoint(_TOOL_UNAVAILABLE_ERROR_ENTRYPOINT)
    try:
        result = run_tool(tool_name, extra_args, logger=logger)
        _write_result(result.kind, result.value)
    except ToolUsageError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=2)
    except ToolUnavailableError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    except Exception as exc:  # pragma: no cover - command boundary
        logger.exception("tool command failed: %s", exc)
        raise typer.Exit(code=1)


@app.command("run")
def run_command(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="Files or directories to parse. Defaults to walking the current directory."),
    ] = None,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="Directory for parsed output files."),
    ] = Path("pennyparse_results"),
):
    """Parse documents into the output directory."""
    configure_logging()
    logger = get_logger("cli")
    _warn_missing_chat_env(logger)
    run = resolve_entrypoint(_RUN_ENTRYPOINT)
    try:
        summary = run(paths=paths, out_dir=out_dir, logger=logger)
        _write_result("json", summary)
    except Exception as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)


@app.command("serve")
def serve(
    port: Annotated[int, typer.Option(help="Port to bind the web shell to.")] = PENNYPARSE_PORT,
):
    """Start the minimal web shell."""
    configure_logging()
    _warn_missing_chat_env(get_logger("cli"))
    resolve_entrypoint(_WEB_SERVE_ENTRYPOINT)(host=PENNYPARSE_HOST, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
