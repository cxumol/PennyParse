# CLI Tool System

`pennyparse tool` is the primary tool entrypoint.

## Commands

- `pennyparse tool --list [--scope=previewer|parser|reviewer]`
- `pennyparse tool <toolname> [args...]`
- `pennyparse tool <toolname> --help`
- `pennyparse init tools [--from PATH] [-f]`
- `pennyparse init docs [-f]`
- `pennyparse run [--out-dir DIR] [PATH ...]`
- `pennyparse serve`

## Stdout / Stderr Contract

- `stdout` only carries command results.
- Text tools write plain text to `stdout`.
- JSON tools write serialized JSON to `stdout`.
- Binary tools write raw bytes to `stdout`.
- Logs, progress, and human-readable error descriptions go to `stderr`.
- Full logs are written to `${CWD}/pennyparse.log`.

## Discovery

- Builtin tool specs live in `src/pennyparse/cmd/tool.py`
- User toolbox source: `${HOME}/pennyparse.toolbox_user.txt` (override with `pennyparse init tools --from ...`)
- Generated user runtime: `${HOME}/.pennyparse/user_toolbox.py`

`pennyparse init tools` reads the toolbox TXT and generates `${HOME}/.pennyparse/user_toolbox.py` directly.

User tool discovery reads the generated module, not the source TXT. The module keeps the runtime contract small:

- `TOOL_SPECS` describes cmd/tool attributes: name, scope, cost, description, env vars, and flags.
- `TOOL_HANDLERS` maps each name to an `argv` handler.
- `UNAVAILABLE_TOOLS` stores disabled tool reasons.

If `${HOME}/.pennyparse/user_toolbox.py` is missing or invalid, `pennyparse tool --list` only shows builtin tools.

Programmatic calls may pass an explicit `home` path to discover or run user tools from a temporary state directory. CLI calls use the process home directory.

`pennyparse tool --list` renders one tool per section. `--scope` is parsed by the CLI and passed to the tool command implementation as an explicit filter.

- `<toolname>\tscope: <scope> cost: <cost>\t<desc>`
- each flag on its own line: `\t--<name> <value>`

Availability combines runtime checks:

- declared env vars must exist and be non-empty
- generated user toolbox must be importable
- generated tool specs must be valid
- required handlers must exist
- disabled tools must carry a reason

## Builtin Tools

Current builtin tools:

- `img_metadata_px`
- `img_thumb`
- `pdf_metadata`
- `pdf2txt`
- `pandoc2txt`

The optional PDF and Pandoc tools remain listed even when their dependencies are missing. In that case, the list output and `pennyparse.log` include the unavailability reason.

## Run

`pennyparse run` parses documents and writes one result file per source file under `pennyparse_results/` by default.

- With explicit paths, each file is parsed and directories are walked recursively.
- Without explicit paths, the current directory is walked; `./.pennyparse_memory.txt` is read only as natural-language parser context when present.
- Hidden files, hidden directories, and the output directory are skipped.
- Parser tools are chosen from available `scope=parser` tools that accept `--path`; binary results are skipped.
- The reviewer accepts non-empty local results when no chat model is configured, and asks the configured chat model for stricter review when a model is available. Reviewer truncation affects only audit context; successful output keeps the complete parser text unless regex patches are applied for `minor_revision`.

## Web Shell

`pennyparse serve` only starts a minimal web shell.

- every route returns `501 Not Implemented`
- CLI is the supported tool interface
