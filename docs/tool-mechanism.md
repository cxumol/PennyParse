# Tool Mechanism

Tools are PennyParse's execution contract. They put local binaries, Python libraries, and remote APIs behind one CLI-shaped interface, so agents can reason about capability, cost, and scope without knowing each backend.

## Public Commands

```shell
pennyparse tool --list
pennyparse tool --list --scope=parser
pennyparse tool <toolname> --help
pennyparse tool <toolname> [args...]
```

The stream rule is simple: tool results go to `stdout`; logs and errors go to `stderr`. Text tools print text, JSON tools print JSON, and binary tools write bytes. List output contains only available tools and includes each tool's flags.

## Tool Spec

Every tool has a small manifest.

```python
{
    "name": "pdf2txt",
    "scope": "parser",
    "cost": "low",
    "desc": "Extract PDF text with PyMuPDF.",
    "secrets": [],
    "flags": {"path": "/path/to/file.pdf"},
}
```

`scope` tells the system when to consider a tool. `cost` lets the parser and initializer try low-friction tools before expensive ones. `secrets` names environment variables that must exist before the tool is considered available.

## Handler Contract

A handler receives `argv: list[str]`, parses its own flags, and returns a value. It should not print business output.

Accepted return shapes:

- `str` for text;
- `bytes` for binary;
- JSON-like Python values for JSON;
- `(kind, value)` where `kind` is `text`, `json`, or `binary`.

This contract lets the same tool run from the CLI, from initialization, and from an agent loop.

## Builtin Tools

The builtin set covers low-cost inspection and common document parsing:

- `img_metadata_px`: image dimensions.
- `img_thumb`: thumbnail bytes.
- `pdf_metadata`: PDF page and text-layer metadata.
- `pdf2txt`: PDF text extraction.
- `pdf_pages_to_images`: PDF page rendering.
- `pandoc2txt`: Office document conversion.

Optional dependencies affect availability, not discovery. A missing PDF or Pandoc backend makes the affected tool unavailable with a reason; it does not remove the tool from the model the parser can reason about.

When the PDF and Pandoc backends are installed, `pennyparse tool --list --scope=parser` includes `pdf2txt`, `pdf_pages_to_images`, and `pandoc2txt`.

## Generated User Tools

User tools start as prose in `pennyparse.toolbox_user.txt`. Use [../src/pennyparse/pennyparse.toolbox_user.example.txt](../src/pennyparse/pennyparse.toolbox_user.example.txt) as the reference shape. The prose should state concrete facts: tool names, scopes, costs, strengths, limits, required environment variables, flags, command shapes, API calls, and caveats.

Vendor tool descriptions can be copied from official docs and trimmed. Keep API keys and other secrets in environment variables; the toolbox prose should name those variables, not contain the secret values.

`pennyparse init tools` asks the tool-generation agent to write `${HOME}/.pennyparse/user_toolbox.py`. The generated module must expose:

- `TOOL_SPECS`;
- `TOOL_HANDLERS`;
- `UNAVAILABLE_TOOLS`.

The initializer imports the module, parses specs, checks missing secrets, verifies handlers, and sends validation failures back to the model for repair. Disabled tools stay visible through `UNAVAILABLE_TOOLS` with a concrete reason.

Generated tool code can execute local programs and call remote services. Review it before trusting it, and keep credentials narrowly scoped.

## Availability

A tool is available when all of these are true:

- its manifest is valid;
- required environment variables are present;
- optional Python dependencies are importable;
- its handler exists and is callable;
- it is not explicitly disabled.

Parser selection only considers available `scope = "parser"` tools that accept `--path`. Preview sampling only considers available previewers or cheap path-based parsers. Cost is advisory, but it matters: a plain text layer should not take the same path as handwriting, formulas, or decorative type.

## Example User Tool

Toolbox prose:

```text
Tool: acme_ocr
Scope: parser
Cost: high
Description: OCR an image through Acme OCR.
Secrets: ACME_OCR_KEY
Flags: --path required image file, --lang optional language code.
Implementation: POST the file bytes to https://api.example.invalid/ocr and return the text field.
```

The generated runtime should translate that prose into a manifest plus an `argv` handler. PennyParse does not care whether the handler uses `httpx`, `subprocess`, or a Python library, as long as the contract is honored.
