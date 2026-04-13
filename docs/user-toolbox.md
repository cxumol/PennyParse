# User Toolbox

`pennyparse init tool` reads `${CWD}/pennyparse.toolbox_user.toml` first. When that file is absent, it falls back to `${CWD}/pennyparse.toolbox_user.txt`, infers TOML through an internal AIGC utility, writes `${CWD}/pennyparse.toolbox_user.toml`, and then generates `${HOME}/.pennyparse/user_toolbox.py`.

## Metadata Shape

User toolbox metadata is TOML, but you can author tools as prose in `${CWD}/pennyparse.toolbox_user.txt` when TOML is not available.

Precedence:

- if TOML and TXT both exist, PennyParse ignores TXT
- if only TXT exists, `init tool` attempts to infer TOML from it
- TXT-to-TOML conversion is an internal step, not a public CLI tool

Top-level fields:

- `schema_version`
- `claim`

Per-tool fields:

- `name`
- `kind = "user"`
- `scope`
- `cost`
- `summary`
- `result_kind`
- `secret`
- `api_reference`
- `notes`
- `[[tool.params]]`

`claim` is a risk statement shown in discovery output and passed into generation prompts.

## Prose Fields

`api_reference` and `notes` are prompt material.

- use them to capture request shapes, response fragments, and API caveats
- keep executable logic out of TOML
- let the generator translate prose into Python handlers

## Secret Fields

`secret` lists required environment variable names.

- PennyParse checks only names, never values
- empty strings count as missing
- missing secrets make the tool unavailable before any LLM generation or runtime call
- the reason is logged to `${CWD}/pennyparse.log`

## Init Flow

`pennyparse init tool` runs a multi-turn loop:

1. read `${CWD}/pennyparse.toolbox_user.toml` if it exists; otherwise operate on `${CWD}/pennyparse.toolbox_user.txt` and infer the corresponding TOML with the internal AIGC utility
2. read `src/pennyparse/pennyparse.prompt.toml`
3. inject the toolbox schema, TOML template, and TXT source into the TXT-to-TOML prompt
4. validate inferred TOML against the schema and run repair turns until it passes or the loop limit is reached
5. assemble builtin metadata, user metadata (generated from TXT inference when necessary), runtime contract, and risk reminders
6. call the configured chat-completions endpoint
7. extract the last fenced markdown code block from the model reply and write it to `${HOME}/.pennyparse/user_toolbox.py`
8. smoke test generated handlers with local demo assets
9. capture stdout, stderr, exit code, and exception details
10. feed failures back into the next repair turn
11. stop when remaining enabled tools pass or the loop limit is reached

The final stdout result is a JSON summary containing:

- enabled tools
- unavailable tools and reasons
- generated file path
- turns used
- log path

## Runtime Contract

The generated module must define:

- `TOOL_HANDLERS`
- `UNAVAILABLE_TOOLS`
- `SMOKE_TEST_ARGS`

Each handler receives `argv: list[str]`, parses its own CLI arguments, and returns data instead of printing it.

The generator prompt requires the model to return the module inside a single fenced Python code block.

## Risk Notice

Generated user tools may execute Python code, call remote APIs, invoke local binaries, and handle credentials.

- review generated code before trusting it
- scope secrets to the smallest possible permission set
- expect third-party APIs and outputs to drift
