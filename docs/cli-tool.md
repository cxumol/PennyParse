# CLI Tool System

`pennyparse tool` is the primary tool entrypoint.

## Commands

- `pennyparse tool --list`
- `pennyparse tool <toolname> [args...]`
- `pennyparse tool <toolname> --help`
- `pennyparse init tool`
- `pennyparse serve`

## Stdout / Stderr Contract

- `stdout` only carries command results.
- Text tools write plain text to `stdout`.
- JSON tools write serialized JSON to `stdout`.
- Binary tools write raw bytes to `stdout`.
- Logs, progress, and human-readable error descriptions go to `stderr`.
- Full logs are written to `${CWD}/pennyparse.log`.

## Discovery

Builtin and user tools use the same metadata shape.

- Builtin metadata: `src/pennyparse/pennyparse.toolbox_builtin.toml`
- User metadata input: `${CWD}/pennyparse.toolbox_user.toml`
- User metadata prose fallback: `${CWD}/pennyparse.toolbox_user.txt`
- Generated user runtime: `${HOME}/.pennyparse/user_toolbox.py`

Input precedence:

- if `${CWD}/pennyparse.toolbox_user.toml` exists, PennyParse uses it and ignores `${CWD}/pennyparse.toolbox_user.txt`
- if only `${CWD}/pennyparse.toolbox_user.txt` exists, `pennyparse init tool` tries to infer and write `${CWD}/pennyparse.toolbox_user.toml`

`pennyparse tool --list` renders:

- `ToolName`
- `Scope`
- `Cost`
- `Summary`
- `Params`
- `ResultKind`
- risk notice
- availability and reason

Availability combines metadata checks and runtime checks:

- declared secret env vars must exist and be non-empty
- optional Python modules must be importable
- user toolbox must be importable
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
