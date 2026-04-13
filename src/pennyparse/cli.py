from __future__ import annotations

import importlib
import json
import sys
from typing import Any

import typer
from typing_extensions import Annotated

from .config import PENNYPARSE_HOST, PENNYPARSE_PORT, get_user_toolbox_path
from .logger import configure_logging, get_logger

app = typer.Typer(name="pennyparse", help="PennyParse CLI", no_args_is_help=True)
init_app = typer.Typer(name="init", help="Initialize generated assets")
app.add_typer(init_app, name="init")

_INIT_TOOL_ENTRYPOINT = "pennyparse.cmd.init:run_init_tool"
_LIST_TOOLS_ENTRYPOINT = "pennyparse.cmd.tool:list_tools"
_RUN_TOOL_ENTRYPOINT = "pennyparse.cmd.tool:run_tool"
_TOOL_USAGE_ERROR_ENTRYPOINT = "pennyparse.cmd.tool:ToolUsageError"
_TOOL_UNAVAILABLE_ERROR_ENTRYPOINT = "pennyparse.cmd.tool:ToolUnavailableError"
_WEB_SERVE_ENTRYPOINT = "pennyparse.web:serve"

_TOOL_COMMAND_HELP = (
    "Usage:\n"
    "  pennyparse tool --list\n"
    "  pennyparse tool <toolname> [args...]\n"
    "  pennyparse tool <toolname> --help\n"
)


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


@init_app.command("tool")
def init_tool(
    force: Annotated[bool, typer.Option("--force", help="Overwrite ~/.pennyparse/user_toolbox.py without prompting.")] = False,
):
    """Generate ~/.pennyparse/user_toolbox.py from pennyparse.toolbox_user.toml."""
    configure_logging()
    logger = get_logger("cli")
    target_path = get_user_toolbox_path()
    overwrite = force
    if target_path.exists() and not force:
        if sys.stdin.isatty():
            overwrite = typer.confirm(f"Overwrite {target_path}?", default=True)
        else:
            overwrite = True

    run_init_tool = resolve_entrypoint(_INIT_TOOL_ENTRYPOINT)
    try:
        summary = run_init_tool(overwrite=overwrite, logger=logger)
        _write_result("json", summary)
    except Exception as exc:
        logger.exception("init tool failed: %s", exc)
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
):
    """List tools or execute a specific tool."""
    configure_logging()
    logger = get_logger("cli")
    extra_args = list(ctx.args)
    list_tools = resolve_entrypoint(_LIST_TOOLS_ENTRYPOINT)

    if list_only:
        _write_result("text", list_tools(logger=logger))
        return

    if tool_name is None:
        wants_help = any(arg in {"-h", "--help"} for arg in extra_args)
        result = _TOOL_COMMAND_HELP if wants_help or not extra_args else list_tools(logger=logger)
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


@app.command("serve")
def serve(
    port: Annotated[int, typer.Option(help="Port to bind the web shell to.")] = PENNYPARSE_PORT,
):
    """Start the minimal web shell."""
    configure_logging()
    resolve_entrypoint(_WEB_SERVE_ENTRYPOINT)(host=PENNYPARSE_HOST, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
