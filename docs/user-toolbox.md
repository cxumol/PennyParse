# User Toolbox

`pennyparse.toolbox_user.txt` is the only user-authored source file for user tools. `pennyparse init tools` reads that TXT directly and generates `${HOME}/.pennyparse/user_toolbox.py`.

## Source Text

Write the toolbox as plain technical prose containing only user tool information: tool names, API references, examples, implementation notes, and caveats. Do not add PennyParse metadata overview prose just to satisfy the generator; the prompt template owns that interpretation layer.

Use `src/pennyparse/pennyparse.toolbox_user.example.txt` as a source-text reference.

For each tool, describe:

- tool name
- scope
- cost
- summary
- result kind
- required secrets
- params, including name, type, whether required, and short help
- upstream API shape
- implementation notes and caveats

After editing `${HOME}/pennyparse.toolbox_user.txt` (or your `--from PATH` file), rerun `pennyparse init tools` so the generated runtime stays in sync.

## Init Flow

`pennyparse init tools` runs a multi-turn loop:

1. read `${HOME}/pennyparse.toolbox_user.txt` (or `--from PATH`)
2. read `src/pennyparse/pennyparse.prompt.toml`
3. assemble builtin tool metadata, runtime contract, prompt interpretation rules, example TXT, and the source TXT
4. call the configured chat-completions endpoint
5. extract the final Python module and write it to `${HOME}/.pennyparse/user_toolbox.py`
6. import the generated module
7. load `TOOL_SPECS` from the generated module
8. mark tools unavailable when declared secrets are missing
9. validate that remaining enabled tools expose handlers
10. feed validation failures back into the next repair turn
11. stop when the generated runtime contract is valid or the loop limit is reached

The final stdout result is a JSON summary containing:

- enabled tools
- unavailable tools and reasons
- generated file path
- turns used
- log path
- validation records

## Runtime Contract

The generated module must define:

- `TOOL_SPECS`
- `TOOL_HANDLERS`
- `UNAVAILABLE_TOOLS`

`TOOL_SPECS` drives `pennyparse tool --list` and `pennyparse tool <name> --help`. It must stay faithful to the source TXT.

Each handler receives `argv: list[str]`, parses its own CLI arguments, and returns data instead of printing it.

The generator prompt requires the model to return the module inside a single fenced Python code block.

## Developer Notes

The generator agent loop is implemented in `src/pennyparse/agent/init_tools.py`.

## Risk Notice

Generated user tools may execute Python code, call remote APIs, invoke local binaries, and handle credentials.

- review generated code before trusting it
- scope secrets to the smallest possible permission set
- expect third-party APIs and outputs to drift
