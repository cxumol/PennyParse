# Configuration

PennyParse loads configuration from TOML files, then applies environment-variable overrides.

`load_pp_config()` also reads `${CWD}/.env` with `python-dotenv` before applying environment overrides. Existing process environment values win over `.env`.

## Files

Create one or both of these files:

- `${HOME}/.pennyparse/pennyparse.settings.toml`
- `${CWD}/pennyparse.settings.toml`

## Precedence

Higher priority wins:

1. Environment variables
2. `${CWD}/pennyparse.settings.toml`
3. `${HOME}/.pennyparse/pennyparse.settings.toml`
4. Package defaults: `src/pennyparse/pennyparse.settings.default.toml`

## Chat Completions Settings

Set these in TOML:

```toml
[aigc.api.chatcomp]
base = "http://localhost:8080/v1"
authkey = ""
model = ""
model_hasVision = true
```

Or override with env vars:

- `PENNYPARSE_CHAT_BASE`
- `PENNYPARSE_CHAT_AUTHKEY` (or `OPENAI_API_KEY`)
- `PENNYPARSE_CHAT_MODEL`

If no `PENNYPARSE_CHAT_*` variable is present, the CLI prints a warning because these values must be configured by the user for normal LLM-backed operation.

`pennyparse init tools` and `pennyparse init docs` require `aigc.api.chatcomp.model` to be non-empty (or set `PENNYPARSE_CHAT_MODEL`).

## Web Settings

```toml
[web]
host = "0.0.0.0"
port = 52026
```

Env overrides:

- `PENNYPARSE_HOST`
- `PENNYPARSE_PORT`

## CLI Timeout

Overwrite prompts use a timeout. Configure it in TOML:

```toml
[cli]
timeout = 15
```

Or override with env:

- `PENNYPARSE_CLI_TIMEOUT`

## Output Settings

```toml
[output]
dir = "pennyparse_results"
ext = "auto"
```

`pennyparse run` uses `dir` as the default output directory. `ext` may be `auto`, `txt`, `md`, or `html`; `auto` currently writes `txt`.

## Reviewer Settings

```toml
[reviewer]
max_length = 1000
```

`max_length` limits only the reviewer audit fragment sent to the chat model. It does not cap parser output length.
