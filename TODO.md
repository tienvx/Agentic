# TODO — agentic

Resumption notes. Everything below marked **[x]** is done and verified; **[ ]** is open work.

---

## Status snapshot

| | |
|---|---|
| Test suite | **43 passed**, 0 failed (`pytest -q`, ~1.4s) |
| A2A interop | **proven** against official `a2a-sdk` 1.3.0 protobuf types + official client |
| README | 39 mermaid diagrams, **all validated** with the real mermaid v11 parser |
| Runtime | Python 3.14, `uv`, venv at `.venv` |
| Git | repo exists, 1 commit `92ef5a2` — **`__pycache__` is tracked, needs removing** |

Reproduce:

```bash
uv sync --extra dev
.venv/bin/python -m pytest -q
.venv/bin/agentic doctor
AGENTIC_MOCK_FAULTS=1 .venv/bin/agentic build "count words and total invoice cents" --out /tmp/demo
```

---

## 1. Do first — correctness gaps

### 1.1 `SubscribeToTask` is advertised but not implemented
`src/agentic/a2a/server.py` — `SubscribeToTask` is in `SUPPORTED_METHODS` (line ~57) but
`_dispatch()` has no branch for it, so a JSON-RPC `SubscribeToTask` call falls through to
`MethodNotFoundError` (-32601). The REST `POST /tasks/{id}:subscribe` path **does** work.

- Add a `_dispatch` branch returning a streaming response, or route it through `_stream_rpc`.
- Note: `_dispatch` returns `dict`, streaming returns `StreamingResponse` — needs a small
  refactor of the RPC handler to allow either.
- Add a test: JSON-RPC `SubscribeToTask` on a non-terminal task streams frames; on a terminal
  task returns `UnsupportedOperationError` (-32004).

### 1.2 Artifacts MCP server is built but never wired in
`src/agentic/mcp_servers/artifacts_server.py` is complete and `ServerSpec.artifacts()` exists,
but `Orchestrator._specs()` only returns `workspace` + `sandbox`. Either wire it in or delete it.

- Preferred: add it to `_specs()` and give the reviewer/verifier read access via MCP instead of
  passing Python objects, so every agent interaction goes through the audited tool layer.

### 1.3 The reviewer only sees file *paths*, not contents
`src/agentic/agents/stages.py` → `ReviewerAgent.user_prompt()` receives `files: list[str]`.
It is reviewing blind. Fix: read the actual source through the workspace MCP tool and pass a
bounded excerpt (respect `MAX_BLOCK_CHARS`).

### 1.4 `max_parallel_tasks` is dead config
`src/agentic/config.py:77` reads it; nothing uses it. Build tasks run strictly serially.
Either implement bounded-parallel task execution (`asyncio.Semaphore`, respecting `depends_on`)
or remove the setting.

---

## 2. Missing tests

The README test-strategy diagram advertises four files that **do not exist yet**. Write them or
correct the diagram.

- [ ] `tests/test_mcp_tools.py` — stdio spawn, `write_file`/`read_file` round-trip,
      path traversal (`../evil.py`) returns `{"ok": false}` not an exception,
      `run_command` allowlist rejects `rm`, shell metacharacters rejected,
      `check_python_syntax` localises a broken file, `list_files` glob `**/*.py` semantics.
- [ ] `tests/test_codegen.py` — generate a project with **all 19 behaviours**, assert it
      compiles, `pytest` is green, and **every CLI subcommand** runs and prints the expected
      value. (This caught the `total()` splat bug — keep it.)
- [ ] `tests/test_pipeline_e2e.py` — full mock run reaches `status=completed`;
      `AGENTIC_MOCK_FAULTS=1` produces `fix_rounds >= 1` and still completes;
      artifacts are content-addressed and re-readable; `AGENTS.md` is written.
- [ ] `tests/test_service_api.py` — `/openapi.json` is valid OpenAPI 3.1, `/api/agents`,
      `POST /api/runs` → poll → `/report`, `/api/runs/{id}/events` SSE terminates.

Also worth adding:
- [ ] A test that the JSON-RPC SSE stream contains **no** empty `{}` data frame
      (this is the regression that broke official-SDK interop — see §6).
- [ ] `agentic validate` CLI test.

---

## 3. Repo hygiene

- [ ] Add `.gitignore` — `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.agentic/`,
      `.agentic-test/`, `*.egg-info/`.
- [ ] `git rm -r --cached` the tracked `__pycache__` directories (they are in commit `92ef5a2`).
- [ ] Add `LICENSE` (pyproject claims MIT; no file present).
- [ ] De-duplicate dev deps in `pyproject.toml`: both `[project.optional-dependencies].dev`
      and `[dependency-groups].dev` exist. Keep one.
- [ ] Move `a2a-sdk` from runtime `dependencies` to a `test` extra — it is only used by
      `tests/test_a2a_wire_compat.py` and `tests/test_official_sdk_interop.py`.
- [ ] Silence the pytest-asyncio deprecation:
      `asyncio_default_fixture_loop_scope = "session"` in `[tool.pytest.ini_options]`.
- [ ] `conftest.py` leaves `.agentic-test/` behind — clean it up in the fixture.
- [ ] Remove unused imports: `orchestrator.py` (`FileChange`, `IdeaBrief`, `asyncio`, `slugify`,
      `write_changes`), `service/app.py` (`AgentCard`, `TaskState`, `data_part`, `text_part`),
      `a2a/client.py` (`Part`).
- [ ] `pipeline/graph.py`: `next_stage()` and `stages_requiring()` are unused — wire them into
      the orchestrator or drop them.
- [ ] Add CI (`.github/workflows/ci.yml`): `uv sync`, `pytest`, `agentic schemas --check`,
      `agentic doctor`.

---

## 4. Real-model validation — the biggest unknown

Everything is currently proven with the **mock** LLM. The OpenAI-compatible path has never been
exercised against a live endpoint.

- [ ] Smoke-test against a local llama.cpp server / Ollama with a small instruct model.
- [ ] Check `response_format={"type":"json_object"}` fallback actually works on servers that
      reject it (`openai_compat.py` retries without it on HTTP 400 — untested).
- [ ] Measure repair-loop effectiveness: how many attempts per stage for a real model.
- [ ] Real models will not produce the mock's tidy file split — verify the builder handles
      partial/overlapping `target_files` and that `_ensure_scaffold` covers a missing
      `pyproject.toml`.
- [ ] Confirm generated code from a real model passes `check_python_syntax` and the suite,
      or that the fix loop converges within `max_fix_rounds`.
- [ ] Consider `structured output` / grammar-constrained decoding where the server supports it.

---

## 5. Feature work

- [ ] **Orchestrator as an A2A server.** Today only the individual agents are A2A endpoints;
      the pipeline itself is REST-only. Expose `build` as an A2A task with streaming so an
      external A2A client can drive a whole run.
- [ ] Push notifications (spec §3.1.7–3.1.10). Currently `capabilities.pushNotifications=false`,
      which is spec-legal, but the four methods should exist behind that flag.
- [ ] `agentic init` — write an `AGENTS.md` into an existing repository.
- [ ] Multi-language scaffolding: the code generator is Python-only; the architecture model
      already supports `stack.language`, so a Node/Go generator would slot in.
- [ ] Persist runs across restarts (currently `RunRegistry` is in-memory; a restart loses runs).
- [ ] `--watch` mode on the CLI to tail a run's SSE events.
- [ ] Cost/token accounting — `LLMResponse.usage` is captured but never aggregated.
- [ ] Human-in-the-loop: use A2A `TASK_STATE_INPUT_REQUIRED` so a run can pause and ask a
      question mid-pipeline.
- [ ] Requirement→test traceability report: `RunReport.requirements_covered` is derived from
      architecture components only, not from which tests actually exercise which FR.

---

## 6. Bugs found and fixed (keep as regression guards)

| Bug | Fix | Guard |
|---|---|---|
| `to_wire()` emitted snake_case (`context_id`) — only `validation_alias` was set | use `alias=` so serialization is camelCase | `test_a2a_wire_compat.py` exact round-trip |
| Custom `$ref` resolver had no `.resolving()` | make schemas self-contained, drop the resolver | `test_contracts.py` |
| MCP toolbox closed before verify ran | hoist `async with MCPToolbox` to span build+verify+review+fix | `test_pipeline_e2e.py` (**not yet written**) |
| Module docstring concatenated with imports → `SyntaxError` | rewrite `render_core` block joining | `test_codegen.py` (**not yet written**) |
| pytest could not import the generated package | add `[tool.pytest.ini_options] pythonpath=["."]` | ditto |
| `total()` splatted instead of passed an iterable | `CLI_CALL` / `CLI_OPTIONS` mapping | ditto |
| `list_files` glob `**/*` matched nothing (fnmatch treats `**` as `*`) | real glob→regex translator | `test_mcp_tools.py` (**not yet written**) |
| Path traversal raised instead of returning an error dict | catch `ValueError` in tool bodies | ditto |
| Agent Card hardcoded host:port → official SDK connected to the wrong place | render card per-request from `request.url` | `test_official_sdk_interop.py` |
| JSON-RPC SSE frames were bare `StreamResponse` | wrap in `{"jsonrpc","id","result"}` per spec §9.4.2 | ditto |
| **`event: done` / `data: {}` sentinel** — an empty object is a malformed JSON-RPC response, so the official SDK rejected every stream | removed the sentinel; the stream just ends | **needs an explicit test** |
| REST errors returned HTTP 500 instead of spec codes | `@app.exception_handler(A2AError)` mapping to §5.4 statuses | `test_a2a_protocol.py` |
| `typer.Exit(exit_code=…)` — wrong kwarg | `typer.Exit(code)` | CLI smoke test |

---

## 7. Map — where to look

```
src/agentic/
  core/spec.py            8 artifact contracts (source of truth)
  core/contracts.py       JSON Schema 2020-12 gen + validation
  core/artifacts.py       content-addressed store, agentic:// URIs
  core/events.py          event bus (CLI + SSE both read this)
  llm/structured.py       ask_structured + repair loop  <-- reliability
  llm/openai_compat.py    any OpenAI-shaped endpoint
  llm/mock.py             stage-aware offline responder
  agents/codegen.py       19 real behaviours -> real tested project
  agents/stages.py        the 7 agents
  a2a/models.py           ProtoJSON-exact A2A v1.0.0 types
  a2a/server.py           JSON-RPC + REST + SSE
  mcp_servers/*.py        workspace / sandbox / artifacts
  mcp/toolbox.py          stdio spawner + client sessions
  pipeline/orchestrator.py  the loop
  service/app.py          OpenAPI + per-agent A2A mounts
  cli.py                  build serve agents schemas validate call doctor
schemas/*.schema.json     published contracts
```

Key conventions to preserve:
- Prompts embed `AGENTIC-STAGE: <name>` and `<<<ARTIFACT:Name ... ARTIFACT>>>` blocks — the mock
  parser depends on both.
- Every model uses `extra="forbid"` so contract drift fails loudly.
- Agents never touch disk/shell directly; only through MCP tools.
- The Verifier **executes**. Never let a model assert test results.
