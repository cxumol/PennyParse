# Agent Loop

PennyParse uses agents where the input space is too open for durable rules and where a deterministic validator can still close the loop. The agent is allowed to propose; code decides whether the proposal becomes state.

## Responsibility Split

The system has four model-facing responsibilities.

`init_tools` turns user-authored toolbox prose into a Python runtime module. This is agent work because the source may describe local commands, HTTP APIs, credentials, and quirks in many styles. A rules engine would either reject useful prose or grow into a weak code generator.

`init docs` groups a local folder and writes `.pennyparse_memory.txt`. This is model work because filenames, preview metadata, and parsing difficulty are weak signals. The output is prose so later code can treat it as guidance rather than a hidden schema.

`parser` is an agent-shaped controller around deterministic tool execution. Today the first-order candidate ranking is deterministic: availability, scope, flags, extension fit, and cost baseline decide the order. The agent boundary is still useful because real documents are uneven and later policy can use the same tool-call contract without changing filesystem ownership.

`reviewer` audits extracted text and proposes bounded repairs. This is agent work because extraction quality is semantic. The repair mechanism is not open-ended: the model can request regex patches, but deterministic code applies and audits them.

## Why Not Deterministic Code

Fixed code is good at contracts: walking files, loading settings, checking dependencies, ranking obvious tool candidates, routing stdout, importing generated modules, applying regex, and writing output. It is weak at interpreting informal tool descriptions, grouping unfamiliar folders, and judging whether an extraction is plausible.

PennyParse therefore keeps uncertainty at the top and enforcement at the bottom. The model sees enough context to make a judgment. The program owns all effects.

## Implementation Modes

Agents declare their intended mode with `_AGENT_IMPL_MODE`.

- `agent/init_tools.py`: `pseudo_XML`.
- `agent/parser.py`: `tool_calls`.
- `agent/reviewer.py`: `tool_calls`.

The mode is documentation for maintainers and tests. It also makes accidental drift visible: a code-synthesis agent and a tool-call agent have different failure shapes.

## Tool-Generation Loop

`init_tools` uses a pseudo-XML code-generation loop.

Expected response shape:

````text
<full_file_code>
```python
...
```
</full_file_code>
````

State machine:

1. Build a prompt from the runtime contract, builtin tool metadata, examples, and the user toolbox TXT.
2. Ask the model for a complete `user_toolbox.py`.
3. Extract the Python code.
4. Write it to `${HOME}/.pennyparse/user_toolbox.py`.
5. Import it and validate `TOOL_SPECS`, `TOOL_HANDLERS`, missing secrets, disabled tools, and any caller-provided result checks.
6. If validation fails, feed the concrete failures back as the next user message.
7. Stop when validation passes or `[aigc.agent].max_iter` is reached.

Result checks are validation targets, not repair instructions. They can report execution failures, output excerpts, or parser-quality issues. The model decides which part of `user_toolbox.py` to change: metadata, argument handling, request construction, prompt text, response parsing, cleanup, or availability.

If the chat request itself fails before a module is produced, `init_tools` writes an importable fallback toolbox from conservative names inferred from the toolbox TXT. Those generated user tools are marked unavailable with the request failure reason, so `init docs` and local parsers can continue with builtin tools while preserving why the requested remote tools cannot run.

The prompt asks for a full replacement on each repair turn. This keeps the generated module coherent and avoids patch stacking.

## Tool-Call Loop

The reusable tool-call loop lives in `utils_aigc.run_tool_calls_loop`.

Loop behavior:

1. Call the chat model with the available tool schema.
2. Append the assistant message to the same session.
3. Execute each returned tool call through a name-to-handler map.
4. Append tool results as JSON.
5. Return the first assistant message that does not request tools.
6. Stop at `[aigc.agent].max_iter`.

Chat completion failures are retried up to `[aigc.agent].max_retry`. Tool exceptions, malformed arguments, and unknown tool names are returned as tool results. The model can respond to the failure, while the Python call stack stays under program control.

## Parser Loop

The parser's outer loop is deterministic:

1. Resolve target files.
2. Discover builtin and user tools.
3. Filter to available parser tools with `--path`.
4. Rank by extension fit and cost baseline from `.pennyparse_memory.txt`.
5. Run candidate tools until review accepts a result.
6. For PDFs, try one page-image fallback when text extraction fails.
7. Write the accepted full text.

Files with no available parser tool are reported as skipped. Skips are not parser failures: they mean the current toolbox set cannot handle that file type or all matching tools are unavailable.

The agent contribution is indirect: initialization writes memory, review accepts or rejects results, and the loop can react by trying the next candidate or a bounded PDF fallback. The parser never gives the model direct write access to output files.

## Reviewer Loop

The reviewer returns one normalized status:

- `pass`;
- `minor_revision`;
- `major_revision`.

Empty text is always `major_revision`. Without a configured model, non-empty text passes locally. With a model, only a bounded prefix is sent for audit; accepted output still uses the complete original text unless a valid repair is applied.

The reviewer exposes one repair tool: `myregexpatch`. It accepts `before_len`, `after_len`, and a chain of `re.sub` patches. The program applies the chain to the initial full parser text and returns only an audit summary: status, patch count, replacement count, and lengths.

Every repair call is evaluated against the same initial text. Later turns do not patch the previous patched result. This keeps repairs reproducible and prevents accidental compounding.

## Cybernetic Boundary

The cybernetic part is the feedback loop: observe a file set or parser result, act through a tool or code proposal, validate the effect, then feed the validation signal back. The boundary is the validator.

Inside the boundary, the agent may revise its judgment. Outside it, deterministic code owns side effects:

- generated code is imported before it is trusted;
- unavailable tools carry explicit reasons;
- parser candidates are ordinary tool executions;
- reviewer repairs are program-applied regex chains;
- output files are written only after review accepts.

This gives the system adaptation without letting adaptation erase accountability.

## Notes For Changes

Add a new agent only when the task needs open-ended judgment and has a compact validation signal. If the validation signal is vague, improve the deterministic contract first.

Keep prompts near their contracts. A prompt should explain the shape of valid output, the available tools, the failure feedback, and the stop condition. It should not encode filesystem policy or output ownership that code can enforce.

When changing a loop, test the failure path: invalid model output, unknown tool call, handler exception, missing dependency, and max-iteration termination.
