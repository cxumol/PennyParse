# User Toolbox

`pennyparse.toolbox_user.txt` is the only user-authored source file for user tools. `pennyparse init tool` reads that TXT directly and generates `${HOME}/.pennyparse/user_toolbox.py`.

## Source Text

Write the toolbox as plain technical prose. A strict template is not required, but the text should state the tool contract clearly enough that the generator can turn it into code.

Use `src/pennyparse/pennyparse.toolbox_user.example.txt` as the style reference.

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

After editing `${CWD}/pennyparse.toolbox_user.txt`, rerun `pennyparse init tool` so the generated runtime stays in sync.

## Init Flow

`pennyparse init tool` runs a multi-turn loop:

1. read `${CWD}/pennyparse.toolbox_user.txt`
2. read `src/pennyparse/pennyparse.prompt.toml`
3. assemble builtin tool metadata, runtime contract, example TXT style, and the source TXT
4. call the configured chat-completions endpoint
5. extract the final Python module and write it to `${HOME}/.pennyparse/user_toolbox.py`
6. import the generated module
7. load `TOOL_SPECS` from the generated module
8. mark tools unavailable when declared secrets are missing
9. smoke test generated handlers with local demo assets
10. capture stdout, stderr, exit code, and exception details
11. feed failures back into the next repair turn
12. stop when remaining enabled tools pass or the loop limit is reached

The final stdout result is a JSON summary containing:

- enabled tools
- unavailable tools and reasons
- generated file path
- turns used
- log path

## Runtime Contract

The generated module must define:

- `TOOL_SPECS`
- `TOOL_HANDLERS`
- `UNAVAILABLE_TOOLS`
- `SMOKE_TEST_ARGS`

`TOOL_SPECS` drives `pennyparse tool --list` and `pennyparse tool <name> --help`. It must stay faithful to the source TXT.

Each handler receives `argv: list[str]`, parses its own CLI arguments, and returns data instead of printing it.

The generator prompt requires the model to return the module inside a single fenced Python code block.

## Risk Notice

Generated user tools may execute Python code, call remote APIs, invoke local binaries, and handle credentials.

- review generated code before trusting it
- scope secrets to the smallest possible permission set
- expect third-party APIs and outputs to drift
