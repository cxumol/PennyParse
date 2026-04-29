# Architecture

PennyParse turns a folder of mixed documents into stable text output. Its design is deliberately small: deterministic code owns the filesystem, configuration, tool contracts, and validation; agents make the few choices where a document set or extraction result is too varied for fixed rules.

The system has four layers.

## Command Boundary

The CLI is the public boundary. `pennyparse init`, `pennyparse tool`, and `pennyparse run` resolve configuration, set up logging, and hand work to command modules. The CLI keeps a strict stream contract: command results go to `stdout`; logs and human messages go to `stderr`; the full runtime log goes to `pennyparse.log`.

This boundary matters because tools may return text, JSON, or bytes. A parser can compose them only if business output is never mixed with progress output.

## Local State

PennyParse uses two generated state files.

- `${HOME}/.pennyparse/user_toolbox.py` is executable tool runtime generated from user-authored toolbox prose.
- `./.pennyparse_memory.txt` is natural-language folder memory generated during initialization and appended during runs.

The first file is code and must satisfy a Python contract. The second file is prose and must remain soft context. Runtime code may read it for hints, but it must not depend on a rigid schema.

## Tool Plane

Tools are the narrow waist of the system. Builtin tools and generated user tools share one shape: a spec declares name, scope, cost, description, secrets, and flags; a handler accepts `argv` and returns text, JSON, bytes, or an explicit `(kind, value)` pair.

The three scopes express intent:

- `previewer`: cheap metadata and sampling used before parsing.
- `parser`: extraction tools that turn a source file into candidate text.
- `reviewer`: repair or audit helpers used by review agents.

The parser never reaches directly into vendor APIs. It asks the tool registry what is available, chooses a candidate, runs it through the same execution path as the CLI, and reviews the result.

## Agent Plane

Agents sit above tools, not beside them. They do not own filesystem mutation except where their output is immediately validated by deterministic code.

There are four current model-facing jobs:

- Generate user tools from a plain-text toolbox description.
- Group a document folder and write natural-language parser memory.
- Orchestrate parsing through an agent-shaped boundary while deterministic code ranks first-order candidates.
- Review extracted text and propose bounded repairs.

The division is intentional. Tool generation is open-ended code synthesis. Folder initialization needs judgment over loose filenames and preview signals. Review needs judgment about extraction quality. Parser execution still runs through ordinary tool calls and deterministic output ownership. File walking, config precedence, command syntax, output paths, dependency checks, and runtime validation stay deterministic.

## Parse Lifecycle

A normal run follows this path:

1. `pennyparse init tools` converts user toolbox prose into a validated runtime module.
2. `pennyparse init docs` scans the working directory, enriches files with cheap previews, groups them by parsing difficulty, and writes folder memory.
3. `pennyparse run` resolves targets, parses them in batches, reviews each result, writes output files, and appends compact run memory.

PDF handling shows the architecture in miniature. The parser first tries cheap text extraction. If review fails and PDF image fallback is available, it renders pages to images, parses those page images, merges the page text, and reviews the merged result. The fallback is bounded to one layer so the system can recover from scanned PDFs without becoming an unbounded planning engine.

## Configuration

Configuration is layered from package defaults, user TOML, project TOML, `.env`, and environment variables. Environment variables win. Chat settings follow the OpenAI-compatible chat-completions shape: base URL, API key, and model.

The default chat base is local. PennyParse therefore runs well in a lightweight Linux environment, but LLM-backed initialization requires an explicitly configured model.

## Design Pressure

The project is optimized for traceable automation rather than maximal autonomy. Every place where the model acts has a contract around it:

- generated code is imported and validated before use;
- tool calls return structured audit data;
- reviewer patches are applied by deterministic regex code;
- parser output is written only after review accepts it;
- generated memory is prose, not an implicit database.

This keeps the agent useful without letting it become the architecture.
