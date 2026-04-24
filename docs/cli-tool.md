# CLI Tool System

`pennyparse tool` is the primary tool entrypoint.

## Commands

- `pennyparse tool --list [--scope=previewer|parser|reviewer]`
- `pennyparse tool <toolname> [args...]`
- `pennyparse tool <toolname> --help`
- `pennyparse init tools [--from PATH] [-f]`
- `pennyparse init docs [-f]`
- `pennyparse serve`

## Stdout / Stderr Contract

- `stdout` only carries command results.
- Text tools write plain text to `stdout`.
- JSON tools write serialized JSON to `stdout`.
- Binary tools write raw bytes to `stdout`.
- Logs, progress, and human-readable error descriptions go to `stderr`.
- Full logs are written to `${CWD}/pennyparse.log`.

## Discovery

- Builtin metadata: `src/pennyparse/pennyparse.toolbox_builtin.toml`
- User toolbox source: `${HOME}/pennyparse.toolbox_user.txt` (override with `pennyparse init tools --from ...`)
- Generated user runtime: `${HOME}/.pennyparse/user_toolbox.py`

`pennyparse init tools` reads the toolbox TXT and generates `${HOME}/.pennyparse/user_toolbox.py` directly.

User tool discovery reads the generated module, not the source TXT. The module must export:

- `TOOL_SPECS`
- `TOOL_HANDLERS`
- `UNAVAILABLE_TOOLS`
- `SMOKE_TEST_ARGS`

If `${HOME}/.pennyparse/user_toolbox.py` is missing or invalid, `pennyparse tool --list` only shows builtin tools.

`pennyparse tool --list` renders one tool per section:

- `<toolname>\tscope: <scope> cost: <cost>\t<desc>`
- each flag on its own line: `\t--<name> <value>`

Availability combines metadata checks and runtime checks:

- declared secret env vars must exist and be non-empty
- generated user toolbox must be importable
- generated `TOOL_SPECS` must be valid
- required handlers must exist
- LLM-disabled tools must carry a reason

## Builtin Tools

Current builtin tools:

- `img_metadata_px`
- `img_thumb`
- `pdf_metadata`
- `pdf2txt`
- `pandoc2txt`

The optional PDF and Pandoc tools remain listed even when their dependencies are missing. In that case, the list output and `pennyparse.log` include the unavailability reason.

## Web Shell

`pennyparse serve` only starts a minimal web shell.

- every route returns `501 Not Implemented`
- CLI is the supported tool interface
