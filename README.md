# agentic

```mermaid
---
title: agentic — one idea in, one working project out
---
flowchart LR
    A(["💡 an idea<br/>in plain language"]) ==> B{{"agentic"}}
    B ==> C[/"✅ a real project on disk<br/>source · tests · README · AGENTS.md"/]
    C -.-> D(["run it: pytest -q"])
    style B fill:#1b3a5b,color:#fff
```

---

## 1. What it is

```mermaid
---
title: The whole system in one picture
---
flowchart TB
    subgraph STD["Open standards — nothing proprietary"]
        direction LR
        A2A["A2A v1.0.0<br/>agent discovery<br/>+ task lifecycle"]
        MCP["MCP<br/>tools and context<br/>for agents"]
        JS["JSON Schema<br/>2020-12<br/>artifact contracts"]
        OA["OpenAPI 3.1<br/>the service's<br/>own API"]
        AM["AGENTS.md<br/>instructions for<br/>any agent<br/>opening the tree"]
    end

    subgraph CORE["agentic"]
        direction TB
        ORCH["Orchestrator<br/>drives the pipeline"]
        AG["7 stage agents"]
        TOOLS["MCP tool servers"]
        STORE["Content-addressed<br/>artifact store"]
    end

    STD --> CORE
    ORCH -->|"A2A"| AG
    AG -->|"MCP"| TOOLS
    ORCH --> STORE
    AG -->|"every output validated against"| JS
    CORE --> SVC["HTTP service<br/>/docs = OpenAPI"]

    style STD fill:#0f2a1f,color:#fff
    style CORE fill:#1b1b2f,color:#fff
```

```mermaid
---
title: Why "open standards" is not decoration
---
flowchart LR
    subgraph THEM["Someone else's tool"]
        T1["A2A client<br/>from the official SDK"]
        T2["Claude Desktop<br/>or any MCP client"]
        T3["jsonschema in any language"]
        T4["curl / openapi-generator"]
    end
    subgraph US["agentic"]
        U1["/agents/scout<br/>A2A endpoint"]
        U2["agentic.mcp_servers<br/>stdio MCP server"]
        U3["schemas/*.schema.json"]
        U4["/openapi.json"]
    end
    T1 -->|JSON-RPC 2.0| U1
    T2 -->|MCP over stdio| U2
    T3 -->|Draft 2020-12| U3
    T4 -->|HTTP| U4
    style THEM fill:#2d2d2d,color:#fff
```

---

## 2. How to use it

```mermaid
---
title: Install and check
---
flowchart TD
    A["git clone … && cd agentic"] --> B["uv sync --extra dev"]
    B --> C["agentic doctor"]
    C --> D{"LLM endpoint<br/>reachable?"}
    D -->|yes| E["real model<br/>AGENTIC_LLM_MODE=openai"]
    D -->|no| F["mock model<br/>offline, deterministic<br/>AGENTIC_LLM_MODE=mock"]
    E --> G["ready"]
    F --> G
    style F fill:#3a3a00,color:#fff
```

```mermaid
---
title: The command you will use 90% of the time
---
flowchart LR
    A["agentic build 'a CLI that validates<br/>emails and totals invoice cents'"] --> B["pipeline runs"]
    B --> C{"exit code"}
    C -->|0| D["✅ completed<br/>green suite + approved review"]
    C -->|1| E["❌ failed<br/>see the stage records"]
    style D fill:#14532d,color:#fff
    style E fill:#5b1a1a,color:#fff
```

```mermaid
---
title: Every CLI command
---
mindmap
  root((agentic))
    build
      "agentic build IDEA"
      "--out DIR"
      "--fix-rounds N"
      "--mcp / --no-mcp"
      "--json"
      "--quiet"
    serve
      "agentic serve --port 8080"
      "--mock"
      "docs at /docs"
    agents
      "agentic agents"
      "agentic agents --json"
    schemas
      "agentic schemas"
      "agentic schemas --check"
    validate
      "agentic validate f.json --as Requirements"
    call
      "agentic call URL TEXT"
      "any remote A2A agent"
    doctor
      "agentic doctor"
      "checks llm + mcp + schemas"
```

```mermaid
---
title: Configure with environment variables — AGENTIC_ prefix
---
mindmap
  root((config))
    LLM
      AGENTIC_LLM_MODE
        auto
        mock
        openai
      AGENTIC_LLM_BASE_URL
      AGENTIC_LLM_API_KEY
      AGENTIC_MODEL
      AGENTIC_LLM_TEMPERATURE
      AGENTIC_LLM_MAX_TOKENS
      AGENTIC_LLM_TIMEOUT
    Pipeline
      AGENTIC_MAX_FIX_ROUNDS
      AGENTIC_REPAIR_ATTEMPTS
      AGENTIC_MCP
      AGENTIC_MAX_PARALLEL_TASKS
    Service
      AGENTIC_HOST
      AGENTIC_PORT
    Storage
      AGENTIC_HOME
    Demo
      AGENTIC_MOCK_FAULTS
```

---

## 3. The pipeline

```mermaid
---
title: Idea to verified project — the stage graph
---
flowchart TD
    I(["idea"]) --> S1
    subgraph S1["scout · IdeaScout"]
        A1["vague idea → sharp brief"]
    end
    S1 -->|IdeaBrief| S2
    subgraph S2["analyst · Requirements Analyst"]
        A2["FR-001… and NFR-001…<br/>with testable acceptance criteria"]
    end
    S2 -->|Requirements| S3
    subgraph S3["architect · Software Architect"]
        A3["stack, components,<br/>module paths, entry points"]
    end
    S3 -->|Architecture| S4
    subgraph S4["planner · Task Planner"]
        A4["dependency-ordered task DAG"]
    end
    S4 -->|TaskPlan| LOOP

    subgraph LOOP["build loop — one task at a time, topological order"]
        direction TB
        B1["builder · Implementer<br/>writes complete files via MCP"]
        B1 --> B1
    end

    LOOP -->|files on disk| V
    subgraph V["verify · Verifier"]
        E1["runs the REAL test suite<br/>in the sandbox"]
    end
    V -->|TestReport| R
    subgraph R["review · Code Reviewer"]
        RV1["approve or request changes"]
    end
    R --> DONE(["RunReport"])
    style LOOP fill:#241b3a,color:#fff
```

```mermaid
---
title: The loop that makes it trustworthy
---
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant B as Builder
    participant W as workspace MCP
    participant V as Verifier
    participant S as sandbox MCP
    participant RV as Reviewer

    O->>B: TaskItem + Architecture + Requirements
    B->>W: write_file(path, content)
    W-->>B: ok
    B-->>O: BuildResult (validated)

    loop until green, or fix budget spent
        O->>V: verify
        V->>S: check_python_syntax
        S-->>V: problems or clean
        V->>S: run_tests(pytest)
        S-->>V: exit code + stdout + stderr
        V-->>O: TestReport (parsed from real output)
        O->>RV: Requirements + TestReport + file list
        RV-->>O: Review (verdict + findings)

        alt suite green AND verdict approve AND no blocking findings
            O-->>O: DONE — status completed
        else still broken, budget left
            O->>B: REPAIR with failure evidence + findings
            Note over O,B: never "weaken the test"<br/>the instruction is explicit
            B->>W: write_file(...)
        else budget exhausted
            O-->>O: DONE — status failed, honestly reported
        end
    end
```

```mermaid
---
title: Repair feedback — exactly what the builder is shown
---
flowchart LR
    A["TestReport"] --> E["_repair_evidence()"]
    B["Review.blocking<br/>blocker + major only"] --> E
    C["raw pytest output<br/>last 3000 chars"] --> E
    E --> P["repair prompt"]
    P --> B2["Builder"]
    B2 --> W["workspace.write_file"]
    W --> V["verify again"]
    V -->|still red| E
    V -->|green| OK(["approved"])
    style E fill:#3a2a00,color:#fff
```

---

## 4. The agents

```mermaid
---
title: Seven agents, seven contracts
---
flowchart LR
    subgraph AG1["1 scout"]
        P1["IdeaScout<br/>discovery, scoping"]
    end
    subgraph AG2["2 analyst"]
        P2["Requirements Analyst<br/>specification"]
    end
    subgraph AG3["3 architect"]
        P3["Software Architect<br/>design"]
    end
    subgraph AG4["4 planner"]
        P4["Task Planner<br/>decomposition"]
    end
    subgraph AG5["5 builder"]
        P5["Implementer<br/>coding · uses workspace MCP"]
    end
    subgraph AG6["6 verifier"]
        P6["Verifier<br/>uses sandbox MCP<br/>NO LLM — runs commands"]
    end
    subgraph AG7["7 reviewer"]
        P7["Code Reviewer<br/>quality gate"]
    end
    AG1 --> AG2 --> AG3 --> AG4 --> AG5 --> AG6 --> AG7
    style AG6 fill:#0f2a1f,color:#fff
```

```mermaid
---
title: What each agent must return — the artifact contracts
---
classDiagram
    class IdeaBrief {
        +title
        +one_liner
        +problem
        +users[]
        +value
        +constraints[]
        +out_of_scope[]
        +assumptions[]
        +success_metrics[]
    }
    class Requirements {
        +project_name
        +summary
        +requirements[]
        +open_questions[]
        +functional()
    }
    class Requirement {
        +id FR-NNN or NFR-NNN
        +kind
        +title
        +description
        +acceptance_criteria[]
        +priority
    }
    class Architecture {
        +stack
        +overview
        +components[]
        +entry_points[]
        +data_flow[]
        +decisions[]
        +all_paths()
    }
    class TaskPlan {
        +goal
        +tasks[]
        +build_order()
    }
    class TaskItem {
        +id
        +title
        +description
        +component_ids[]
        +target_files[]
        +depends_on[]
        +requirement_ids[]
        +done_when[]
    }
    class BuildResult {
        +task_id
        +status
        +files[]
        +notes
        +deviations[]
    }
    class TestReport {
        +command
        +success
        +exit_code
        +passed
        +failed
        +errors
        +failures[]
        +raw_output
    }
    class Review {
        +verdict
        +summary
        +findings[]
        +blocking
    }
    IdeaBrief "1" --> "1" Requirements : sharpened into
    Requirements "1" *-- "1..*" Requirement
    Requirements "1" --> "1" Architecture : realised by
    Architecture "1" --> "1" TaskPlan : split into
    TaskPlan "1" *-- "1..*" TaskItem
    TaskItem "1" --> "1" BuildResult : implemented as
    BuildResult "1" --> "1" TestReport : checked by
    TestReport "1" --> "1" Review : judged with
```

```mermaid
---
title: Every contract is published as JSON Schema 2020-12
---
flowchart LR
    A["Pydantic models<br/>src/agentic/core/spec.py<br/>extra=forbid"] -->|"agentic schemas"| B["schemas/*.schema.json<br/>self-contained, $id set"]
    B --> C["agents validate<br/>before trusting"]
    B --> D["GET /api/schemas"]
    B --> E["any other language<br/>validates the same bytes"]
    B --> F["agentic validate f.json --as Requirements"]
    style A fill:#1b3a5b,color:#fff
```

---

## 5. Schema-constrained generation

```mermaid
---
title: ask_structured — where reliability actually comes from
---
flowchart TD
    A["system prompt<br/>AGENTIC-STAGE marker + rules<br/>+ the JSON Schema inline"] --> B["LLM complete(json_mode)"]
    B --> C["extract_json()<br/>fenced block, balanced-brace scan,<br/>prose tolerated"]
    C --> D{"valid JSON?"}
    D -->|no| R
    D -->|yes| E{"JSON Schema<br/>Draft 2020-12?"}
    E -->|no| R
    E -->|yes| F{"Pydantic semantic rules?<br/>unique ids, acyclic DAG,<br/>safe paths, id format"}
    F -->|no| R
    F -->|yes| G(["✅ accepted artifact"])
    R["append REPAIR REQUESTED<br/>with the exact validation errors"] --> B
    R --> H{"attempts left?"}
    H -->|no| X(["LLMError"])
    style G fill:#14532d,color:#fff
    style X fill:#5b1a1a,color:#fff
    style R fill:#3a2a00,color:#fff
```

```mermaid
---
title: Three independent gates, each catching what the others miss
---
flowchart LR
    subgraph G1["Gate 1 · syntax"]
        A["extract_json"]
    end
    subgraph G2["Gate 2 · contract"]
        B["jsonschema<br/>Draft202012Validator"]
    end
    subgraph G3["Gate 3 · meaning"]
        C["pydantic validators<br/>cycle detection<br/>duplicate ids<br/>path traversal<br/>vague criteria"]
    end
    A --> B --> C
    A -.->|"hallucinated prose<br/>around the JSON"| A
    B -.->|"missing or extra<br/>fields"| B
    C -.->|"a task graph<br/>with a cycle"| C
```

---

## 6. A2A — how agents talk

```mermaid
---
title: A2A task lifecycle (spec TaskState)
---
stateDiagram-v2
    [*] --> SUBMITTED : SendMessage
    SUBMITTED --> WORKING : agent starts
    WORKING --> WORKING : status update
    WORKING --> COMPLETED : artifact produced
    WORKING --> FAILED : handler raised
    WORKING --> INPUT_REQUIRED : needs more from client
    INPUT_REQUIRED --> WORKING : client sends follow-up Message
    WORKING --> CANCELED : CancelTask
    WORKING --> REJECTED : refused
    COMPLETED --> [*]
    FAILED --> [*]
    CANCELED --> [*]
    REJECTED --> [*]
```

```mermaid
---
title: Discovery then work — the A2A handshake
---
sequenceDiagram
    autonumber
    participant C as A2A client<br/>(ours or the official SDK)
    participant S as agentic A2A server

    C->>S: GET /.well-known/agent-card.json
    S-->>C: AgentCard<br/>name, skills, capabilities,<br/>supportedInterfaces[].url
    Note over S: the card URL is rendered<br/>per-request, so it always<br/>matches host, port and mount

    C->>S: POST / {"jsonrpc":"2.0","method":"SendMessage","params":{message}}
    Note over S: taskId and contextId<br/>are server-generated
    S-->>C: Task (SUBMITTED → WORKING → COMPLETED) + Artifacts

    C->>S: GET-equivalent {"method":"GetTask","params":{"id":...}}
    S-->>C: current Task

    C->>S: POST / {"method":"SendStreamingMessage", ...}
    S-->>C: SSE data: {"jsonrpc":"2.0","id":...,"result":{StreamResponse}}
    S-->>C: SSE statusUpdate / artifactUpdate frames
    S-->>C: SSE terminal frame, stream closes
```

```mermaid
---
title: One data model, two bindings, identical semantics
---
flowchart TB
    subgraph DATA["Canonical data model (spec §4)"]
        direction LR
        T["Task"] --- M["Message"] --- P["Part"] --- AR["Artifact"]
    end
    subgraph JR["JSON-RPC 2.0 binding"]
        J1["POST /"]
        J2["SendMessage · SendStreamingMessage<br/>GetTask · ListTasks · CancelTask<br/>SubscribeToTask · GetExtendedAgentCard"]
    end
    subgraph REST["HTTP+JSON/REST binding"]
        R1["POST /message:send · /message:stream"]
        R2["GET /tasks · GET /tasks/{id}"]
        R3["POST /tasks/{id}:cancel · :subscribe"]
    end
    DATA --> JR
    DATA --> REST
    style DATA fill:#1b3a5b,color:#fff
```

```mermaid
---
title: Part is a oneof — text, structured data, file reference or bytes
---
flowchart LR
    P["Part"] -->|"content"| A["text<br/>plain string"]
    P -->|"content"| B["data<br/>JSON value + mediaType"]
    P -->|"content"| C["url<br/>file reference"]
    P -->|"content"| D["raw<br/>base64 bytes"]
    P --> E["metadata · filename · mediaType"]
    B -.->|"agentic convention"| F["metadata.artifact = 'Requirements'<br/>→ named input for the agent"]
```

```mermaid
---
title: Error codes are the spec's, not invented
---
flowchart LR
    subgraph E["A2A error → JSON-RPC code → HTTP status"]
        direction TB
        E1["TaskNotFoundError · -32001 · 404"]
        E2["TaskNotCancelableError · -32002 · 400"]
        E3["PushNotificationNotSupported · -32003 · 400"]
        E4["UnsupportedOperation · -32004 · 400"]
        E5["ContentTypeNotSupported · -32005 · 400"]
        E6["InvalidAgentResponse · -32006 · 500"]
        E7["VersionNotSupported · -32009 · 400"]
        E8["MethodNotFound · -32601 · 404"]
        E9["InvalidParams · -32602 · 400"]
    end
    E --> N["JSON-RPC carries errors in the envelope<br/>with HTTP 200; the REST binding uses the HTTP status"]
```

---

## 7. MCP — how agents act

```mermaid
---
title: Agents never touch your disk or shell directly
---
flowchart LR
    subgraph AG["Agent"]
        A["Builder / Verifier"]
    end
    subgraph TB["MCPToolbox"]
        T["spawns stdio servers<br/>owns sessions<br/>normalises results"]
    end
    subgraph SRV["MCP servers (real MCP, over stdio)"]
        W["agentic-workspace<br/>list_files · read_file<br/>write_file · delete_file"]
        S["agentic-sandbox<br/>run_command · run_tests<br/>check_python_syntax"]
        AR["agentic-artifacts<br/>read_artifact · write_artifact"]
    end
    A --> T --> SRV
    SRV --> FS[("project directory")]
    SRV --> PR[("subprocess<br/>pytest")]
    style AG fill:#241b3a,color:#fff
    style SRV fill:#0f2a1f,color:#fff
```

```mermaid
---
title: An MCP tool call, byte for byte
---
sequenceDiagram
    autonumber
    participant A as Agent
    participant X as MCPToolbox
    participant C as ClientSession
    participant P as python -m agentic.mcp_servers
    participant S as MCPServer

    X->>P: spawn subprocess, stdin/stdout pipes
    X->>C: wrap pipes
    C->>S: initialize
    S-->>C: capabilities + server info
    C->>S: list_tools
    S-->>C: tool list with JSON Schemas
    A->>X: call("workspace","write_file",{path,content})
    X->>C: call_tool
    C->>S: tools/call
    S->>S: _safe_join(root, path)<br/>reject .. and absolute paths
    S-->>C: CallToolResult structuredContent
    C-->>A: {"ok":true,"path":"app/core.py"}
    X->>P: terminate on context exit
```

```mermaid
---
title: Policy enforced by the servers, not by trusting the model
---
flowchart TD
    A["tool call arrives"] --> B{"path relative,<br/>no .. no ~ no /"}
    B -->|no| X1["reject: path escapes workspace root"]
    B -->|yes| C{"resolved path<br/>inside root?"}
    C -->|no| X1
    C -->|yes| D{"server read-only?"}
    D -->|yes| X2["reject: read-only"]
    D -->|no| OK(["perform the action"])

    E["run_command arrives"] --> F{"contains ; & | backtick $ newline"}
    F -->|yes| Y1["reject: shell metacharacters"]
    F -->|no| G{"executable on allowlist?"}
    G -->|no| Y1
    G -->|yes| H{"python -c or -m?"}
    H -->|yes| Y2["reject: use run_tests instead"]
    H -->|no| YOK(["exec with timeout"])
    style X1 fill:#5b1a1a,color:#fff
    style Y1 fill:#5b1a1a,color:#fff
```

```mermaid
---
title: Use the same servers from outside agentic
---
flowchart LR
    A["python -m agentic.mcp_servers workspace --root ./proj"] --> C["any MCP client"]
    B["python -m agentic.mcp_servers sandbox --root ./proj"] --> C
    C --> D["Claude Desktop"]
    C --> E["MCP Inspector"]
    C --> F["another agent framework"]
```

---

## 8. The service

```mermaid
---
title: One port, two standards-compliant surfaces
---
flowchart TB
    subgraph APP["agentic serve"]
        direction TB
        subgraph API["OpenAPI 3.1 REST — /docs"]
            H1["GET /health"]
            H2["GET /api/agents"]
            H3["GET /api/schemas"]
            H4["POST /api/runs · GET /api/runs"]
            H5["GET /api/runs/{id}"]
            H6["GET /api/runs/{id}/events  SSE"]
            H7["GET /api/runs/{id}/report"]
            H8["GET /api/a2a/cards"]
        end
        subgraph A2A["A2A per agent"]
            G1["/agents/scout/"]
            G2["/agents/analyst/"]
            G3["/agents/architect/"]
            G4["/agents/planner/"]
            G5["/agents/builder/"]
            G6["/agents/verifier/"]
            G7["/agents/reviewer/"]
        end
    end
    U1["your app"] --> API
    U2["any A2A client"] --> A2A
    style API fill:#1b3a5b,color:#fff
    style A2A fill:#241b3a,color:#fff
```

```mermaid
---
title: Drive a run over HTTP
---
sequenceDiagram
    autonumber
    participant U as Client
    participant S as Service
    participant O as Orchestrator

    U->>S: POST /api/runs {"idea":"..."}
    S->>O: build() in a background task
    S-->>U: 202 {"run_id":"run-abc","status":"running"}
    par stream progress
        U->>S: GET /api/runs/run-abc/events
        S-->>U: SSE stage events (scout, build, verify, fix ...)
    and poll
        U->>S: GET /api/runs/run-abc
        S-->>U: status
    end
    S-->>U: SSE run finished
    U->>S: GET /api/runs/run-abc/report
    S-->>U: RunReport (validated against its schema)
```

```mermaid
---
title: Calling a single agent, not the whole pipeline
---
flowchart LR
    A["agentic call http://host:8080/agents/scout 'a tool that ...'"] --> B["A2AClient<br/>reads the card"]
    B --> C["SendMessage"]
    C --> D["Task COMPLETED<br/>artifact IdeaBrief"]
    D --> E["prints the JSON artifact"]
```

---

## 9. Storage and reproducibility

```mermaid
---
title: Content-addressed artifact store
---
flowchart TD
    A["stage produces a model"] --> B["validate against JSON Schema"]
    B --> C["canonical JSON<br/>sorted keys, indent 2"]
    C --> D["sha256 digest"]
    D --> E[("runs/{run_id}/artifacts/<br/>{Name}-{digest16}.json")]
    E --> F["index.json records the uri"]
    F --> G["agentic://{run_id}/{Name}@{digest16}"]
    G --> H["same bytes → same address →<br/>a run can be replayed and audited"]
    style E fill:#1b3a5b,color:#fff
```

```mermaid
---
title: What lands on disk
---
flowchart TB
    R[(".agentic/runs/{run_id}/")] --> A["artifacts/<br/>IdeaBrief-abc123.json …"]
    R --> I["index.json"]
    R --> P["project/"]
    P --> P1["pyproject.toml"]
    P --> P2["README.md"]
    P --> P3["AGENTS.md"]
    P --> P4["{package}/core.py · cli.py · __main__.py"]
    P --> P5["tests/test_core.py"]
    style P fill:#0f2a1f,color:#fff
```

---

## 10. Offline mode and the fix-loop demo

```mermaid
---
title: Mock mode — the pipeline is testable with zero API keys
---
flowchart LR
    A["prompt"] --> B["parse AGENTIC-STAGE marker"]
    B --> C["parse <<<ARTIFACT:Name blocks"]
    C --> D{"stage"}
    D -->|scout analyst architect planner| E["deterministic<br/>parameterised JSON"]
    D -->|builder| F["real code generator<br/>codegen.py"]
    D -->|reviewer| G["verdict from the<br/>actual TestReport"]
    F --> H["19 real behaviours,<br/>each with a real test"]
    style F fill:#0f2a1f,color:#fff
```

```mermaid
---
title: Prove the loop heals — AGENTIC_MOCK_FAULTS=1
---
sequenceDiagram
    autonumber
    participant B as Builder
    participant V as Verifier
    participant O as Orchestrator

    B->>V: code with an injected off-by-one
    V->>V: pytest → 1 failed
    V-->>O: TestReport(success=false)
    O->>O: reviewer → blocker → request_changes
    O->>B: REPAIR with the failure output
    Note over B: mock regenerates correct code<br/>real model gets the real diff to fix
    B->>V: repaired code
    V-->>O: 6 passed
    O-->>O: approved, fix_rounds=1
```

---

## 11. Code map

```mermaid
---
title: Where everything lives
---
mindmap
  root((src/agentic))
    core
      spec.py
        contracts
      contracts.py
        schema gen + validate
      artifacts.py
        content addressed store
      events.py
        event bus
    llm
      base.py
        protocol
      openai_compat.py
        any OpenAI-shaped server
      mock.py
        offline deterministic
      structured.py
        repair loop
    a2a
      models.py
        ProtoJSON types
      server.py
        JSONRPC + REST + SSE
      client.py
        httpx client
    mcp_servers
      workspace.py
      sandbox.py
      artifacts_server.py
      __main__.py
    mcp
      toolbox.py
        stdio spawner
    agents
      base.py
      stages.py
      registry.py
      codegen.py
    pipeline
      graph.py
      orchestrator.py
    service
      app.py
    cli.py
```

---

## 12. How to extend it

```mermaid
---
title: Add a new artifact contract
---
flowchart LR
    A["add a Pydantic model<br/>in core/spec.py"] --> B["register it in MODELS"]
    B --> C["agentic schemas"]
    C --> D["schemas/YourThing.schema.json"]
    D --> E["agents can now be asked<br/>to produce it and it is validated"]
```

```mermaid
---
title: Add a new agent
---
flowchart LR
    A["subclass StageAgent"] --> B["set stage · output_model · requires"]
    B --> C["write system_prompt()"]
    C --> D["register in AGENT_TYPES"]
    D --> E["it appears in<br/>agentic agents<br/>/api/agents<br/>/agents/{stage} as A2A"]
    E --> F["wire it into PIPELINE in pipeline/graph.py"]
```

```mermaid
---
title: Add a new tool
---
flowchart LR
    A["add an async function<br/>under @server.tool in an MCP server"] --> B["it is auto-described<br/>from its signature"]
    B --> C["agents call it via<br/>toolbox.call(server, tool, args)"]
    C --> D["any external MCP client<br/>sees it too"]
```

---

## 13. Test strategy

```mermaid
---
title: What is proven, and how
---
flowchart TB
    subgraph T1["Contracts"]
        A["test_contracts<br/>schema gen · extra=forbid ·<br/>cycle rejection · id format"]
    end
    subgraph T2["Standards compliance"]
        B["test_a2a_wire_compat<br/>round-trip every object through<br/>the official protobuf types"]
        C["test_a2a_protocol<br/>our client vs our server<br/>over a real socket"]
        D["test_official_sdk_interop<br/>official a2a-sdk client<br/>drives our server"]
    end
    subgraph T3["Tools — planned, see TODO"]
        E["test_mcp_tools<br/>stdio spawn · traversal blocked ·<br/>allowlist enforced"]
    end
    subgraph T4["End to end — planned, see TODO"]
        F["test_pipeline_e2e<br/>full mock run green ·<br/>fault injection triggers a fix round"]
        G["test_codegen<br/>every generated CLI command runs"]
    end
    T1 --> T2 --> T3 --> T4
    style T2 fill:#0f2a1f,color:#fff
    style T3 fill:#3a3a00,color:#fff
    style T4 fill:#3a3a00,color:#fff
```

```mermaid
---
title: Interop is proven, not assumed
---
flowchart LR
    A["our JSON"] -->|"json_format.ParseDict"| B["official a2a_pb2 types"]
    B -->|"MessageToDict"| C{"byte-identical<br/>to our wire form?"}
    C -->|yes| D(["✅ canonical A2A v1.0.0"])
    C -->|no| E(["test fails — drift is caught<br/>in CI, not in production"])
    F["official a2a-sdk Client"] -->|real HTTP| G["our A2A server"]
    G --> H(["card · SendMessage ·<br/>GetTask · artifacts"])
    style D fill:#14532d,color:#fff
```

---

## 14. Design decisions

```mermaid
---
title: The choices that matter
---
flowchart TB
    subgraph D1["Verification is execution"]
        A["the Verifier runs pytest<br/>a model never reports<br/>what it thinks happened"]
    end
    subgraph D2["Contracts before trust"]
        B["no artifact is accepted until<br/>it passes JSON Schema + Pydantic"]
    end
    subgraph D3["Side effects behind MCP"]
        C["agents cannot touch disk or shell<br/>except through audited tools"]
    end
    subgraph D4["Data over control flow"]
        D["the pipeline is a table in graph.py<br/>reorder or extend without rewriting"]
    end
    subgraph D5["Boring dependencies"]
        E["pydantic · fastapi · httpx ·<br/>jsonschema · mcp · typer"]
    end
    style D1 fill:#0f2a1f,color:#fff
```

```mermaid
---
title: Failure is a first-class outcome
---
stateDiagram-v2
    [*] --> Running
    Running --> Completed : green suite + approved
    Running --> Failed : stage raised
    Running --> Failed : fix budget spent
    Failed --> [*] : RunReport still written,<br/>stage records say exactly where
    Completed --> [*]
```
