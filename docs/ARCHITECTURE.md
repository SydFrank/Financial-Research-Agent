# A-Share Research Agent — Technical Architecture

English | [简体中文](ARCHITECTURE.zh-CN.md)

**Version** v7
**Status** Design baseline

---

## About this document

This document describes the system's technical architecture and implementation specification. It is the single design reference for development.

**Design principle**: every technology choice must answer three questions — what problem it solves, what happens without it, and how its effectiveness is verified. Anything that cannot answer them is not adopted and is recorded in [§22 Technologies not adopted](#22-technologies-not-adopted-and-their-triggers).

**Related documents**
- [TECH_DECISIONS.md](./TECH_DECISIONS.md) — Technical decision handbook (options, trade-offs and verification for each decision)
- [DEPLOYMENT.md](./DEPLOYMENT.md) — Deployment guide
- `EVAL_REPORT.md` — Evaluation report (generated after the first evaluation run)

**Compliance boundary**: the system is for investment research and analysis only. It gives no buy/sell ratings or price predictions, does not connect to live trading, does not place orders or move funds, and does not provide investment advice to individuals.

---

## Contents

| Section | Content |
|---|---|
| [1](#1-system-overview) | System overview |
| [2](#2-key-design-problems) | Key design problems |
| [3](#3-architecture-overview) | Architecture overview |
| [4](#4-data-model) | Data model |
| [5](#5-api-contract) | API contract |
| [6](#6-multi-agent-orchestration) | Multi-agent orchestration |
| [7](#7-context-engineering-and-memory) | Context engineering and memory |
| [8](#8-rag-subsystem) | RAG subsystem |
| [9](#9-financial-data-subsystem-point-in-time) | Financial data subsystem (point-in-time) |
| [10](#10-llm-module) | LLM module |
| [11](#11-tools-and-sandbox) | Tools and sandbox |
| [12](#12-evaluation-harness) | Evaluation harness |
| [13](#13-security-and-governance) | Security and governance |
| [14](#14-observability) | Observability |
| [15](#15-reliability-and-durable-execution) | Reliability and durable execution |
| [16](#16-configuration) | Configuration |
| [17](#17-frontend) | Frontend |
| [18](#18-containers-and-deployment) | Containers and deployment |
| [19](#19-cicd) | CI/CD |
| [20](#20-testing-strategy) | Testing strategy |
| [21](#21-repository-layout) | Repository layout |
| [22](#22-technologies-not-adopted-and-their-triggers) | Technologies not adopted and their triggers |
| [23](#23-milestones) | Milestones |

---

## 1. System overview

### 1.1 Responsibility

The system is an **investment research agent application** for A-share listed companies, engineered to enterprise standards.

Business capability: accept a natural-language research question, gather evidence from annual reports, announcements and structured financial data, perform all calculation in a sandbox, and produce a **structured research report in which every claim is bound to its source**.

Engineering goals: quality is measurable (evaluation harness), failures are diagnosable (end-to-end tracing), faults are recoverable (durable execution), behaviour is controlled (permissions, audit, human approval).

> **Why investment research**: it combines long-document retrieval, table and numeric reasoning, cross-document comparison and open analysis, and its factual questions have objective answers, which makes a credible evaluation benchmark possible.

### 1.1.1 Development workflow

**Docs-first**: architecture and technical decisions first → design review → implementation → evaluation. Every key trade-off is recorded in the [Technical Decision Handbook](./TECH_DECISIONS.md); changes are appended, never overwritten.

### 1.2 Users and scenarios

**Users**: in-house research analysts and portfolio managers at an investment firm. The system is an internal tool, not a public product.

**Workflow pain points**:

| Pain point | Today | System response |
|---|---|---|
| Scattered information | Filings, announcements, news and market data live in separate systems | Unified retrieval and data access layer |
| Repetitive work | For every security: fetch data → read filings → read news → summarise | Parallel multi-agent automation |
| Untraceable conclusions | Conclusions passed on verbally or by email cannot be checked later | Claim-level citation binding + end-to-end audit |
| Single perspective | Confirmation bias leads analysts to look only for supporting evidence | Reports must include a "Risks and counter-evidence" section, checked by the Critic |

### 1.3 Input and output

**Input**
```
{
  query: str,                    # research question
  symbols: list[str] | None,     # security codes (optional; can be inferred)
  as_of_date: date | None,       # information cut-off, defaults to today
  depth: "quick" | "standard" | "deep" | None
}
```

**Output**
```
{
  report: {
    sections: [{ title, content, claims: [{ text, source_ids, verified }] }],
    summary: str,
    risks: [{ text, source_ids }],         # risks and counter-evidence, never empty
    unverified: [str]                      # sub-questions with no supporting evidence, listed explicitly
  },
  citations: [{ source_id, doc_title, url|locator, published_at, snippet }],
  metadata: { trace_id, tokens, cost_usd, latency_ms, agents_invoked: [str] }
}
```

### 1.4 System quality goals

| Goal | Metric | Notes |
|---|---|---|
| Accuracy | Numeric accuracy on factual questions | Financial figures match the authoritative source |
| Trustworthiness | Unsourced claim rate → 0 | No assertion without a source_id may appear in a report |
| Cost control | Cost / latency per research run | Explicit thresholds, continuously monitored |
| Regression detection | Quality changes detected automatically | Evaluation compares against the baseline after any prompt or model change |

> Regression detection is the precondition for the other three: without automatic quality checks, quality cannot be sustained.

---

## 2. Key design problems

The architecture is the answer to the following problems. Each names the subsystems it affects.

### P1 · Reliability of numbers and citations

**Problem**: LLMs fabricate numbers and sources, which is unacceptable in finance.

**Solution (four lines of defence)**:

| Layer | Measure | Where |
|---|---|---|
| Lookup | Financial data comes from structured sources, never "read" out of text | §9 |
| Computation | All arithmetic runs as code; the LLM does no arithmetic | §11 |
| Attribution | Claims must bind a `source_id`; unsourced assertions never enter the report | §8.4 |
| Verification | The Critic checks citation validity and accounting identities | §6.4 |

**Verification**: metrics `unsourced claim rate` and `numeric accuracy`, compared with each layer switched on and off.

### P2 · Context capacity

**Problem**: the material for one research task (filings + dozens of news items + market data) far exceeds a single context budget.

**Solution**: sub-task isolation + structured hand-back + just-in-time retrieval (§7). This is the first-principles reason for a multi-agent architecture.

**Verification**: compare token consumption and accuracy for a single agent with full context versus multiple agents with isolated contexts.

### P3 · Confirmation bias

**Problem**: single-perspective analysis systematically looks only for supporting evidence.

**Solution**: the report structure must include "Risks and counter-evidence"; when decomposing the question, the Orchestrator creates a dedicated retrieval sub-task for counter-evidence; the Critic checks that this section has substance and citations (§6.4). Bull/bear debate is a candidate extension (§6.1), introduced only if evaluation shows these measures are insufficient.

**Verification**: the "counter-evidence coverage" rubric dimension in the analytical evaluation set.

### P4 · Quality regression

**Problem**: a prompt or model change can degrade quality in ways unit tests cannot detect.

**Solution**: a stratified evaluation set + a CI evaluation gate (§12, §19).

### P5 · Cost control

**Problem**: multi-agent token consumption is several times that of a single agent.

**Solution**: model tiers, prompt caching, context isolation, token budgets, and routing by complexity (§7, §10).

**Verification**: the cost–quality Pareto curve.

### P6 · Point-in-time correctness

**Problem**: financial statements are published with a lag and may later be revised. Without separating "the period the data describes" from "when the data became public", revised figures get treated as what was known at the time, or unpublished reports get treated as known.

**Solution**: a bitemporal data model + mandatory `as_of_date` filtering (§9).

### P7 · Justifying the number of agents

**Problem**: the number of agents tends to grow without reason, and the source of any gain is hard to show.

**Solution**: start from the minimal role set (§6.1); add extension roles one at a time with incremental experiments (§12.5), keeping a role only if the metric gain exceeds run-to-run variance.

### P8 · Long-task reliability

**Problem**: a research task runs for minutes; a mid-way failure loses all the work.

**Solution**: state checkpoints + asynchronous queue execution + per-node timeouts + graceful degradation (§15).

### P9 · Indirect prompt injection

**Problem**: external documents read by agents may contain malicious instructions.

**Solution**: everything returned by tools is treated as data, never as instructions; arguments are re-validated; compliance red lines are hard refusals (§13).

### P10 · Auditability

**Problem**: finance requires traceable conclusions, auditable actions and the ability to intervene in high-risk actions.

**Solution**: `trace_id` end to end + audit log + claim-level citation tracing + human-in-the-loop approval (§13, §14).

---

## 3. Architecture overview

### 3.1 Deployment units

```
┌─────────────┐      ┌──────────────────────────────────────────┐
│  frontend   │─────▶│  api  (FastAPI · modular monolith)        │
│  React + TS │ HTTP │                                           │
│  Nginx      │ SSE  │   app/gateway/   auth·RBAC·rate limit·filter│
└─────────────┘      │   app/agents/    agent definitions, prompts│
                     │   app/graph/     LangGraph state machine   │
                     │   app/context/   context management        │
                     │   app/rag/       retrieval and citation    │
                     │   app/data/      financial data · PIT      │
                     │   app/llm/       model routing · cost      │
                     │   app/tools/     tool registry             │
                     └───────┬──────────────────────────────────┘
                             │  Redis Stream (long tasks)
                     ┌───────▼──────────┐    ┌──────────────────┐
                     │  worker          │───▶│  sandbox-runner  │
                     │  runs agent graph│HTTP│  restricted code │
                     │  (reuses api)    │    │  execution       │
                     └───────┬──────────┘    └──────────────────┘
                             │
        ┌────────────────────┴────────────────────────────┐
        │                                                  │
  ┌─────▼──────────────┐   ┌──────────┐   ┌───────────────▼──┐
  │ PostgreSQL 16      │   │ Redis 7  │   │ OTel Collector   │
  │ + pgvector         │   │          │   │ → Prometheus     │
  │ business·vectors·  │   │ queue ·  │   │ → Grafana        │
  │ checkpoints        │   │ cache    │   │                  │
  └────────────────────┘   └──────────┘   └──────────────────┘

  harness/  — CLI run locally and in CI; not an online service
```

### 3.2 Deployment unit responsibilities

| Unit | Responsibility | Process model | Scaling dimension |
|---|---|---|---|
| **frontend** | UI rendering, SSE subscription | Nginx static serving | CDN / replicas |
| **api** | HTTP entry, auth, synchronous queries, task submission, SSE push | Uvicorn, multiple workers | QPS |
| **worker** | Consumes the queue, runs the agent graph | Long-running process, configurable concurrency | Queue depth |
| **sandbox-runner** | Restricted code execution | Stateless HTTP service | Execution request volume |

### 3.3 Criteria for splitting a service

A concern becomes its own service only if it meets at least one criterion:

1. **Security boundary** — needs process or container isolation
2. **Different resources and lifecycle** — a markedly different scaling model or failure mode
3. **Independent release cadence** — a separate team or iteration cycle
4. **Independent scaling** — a load profile markedly different from the main service

| Concern | Criterion met | Result |
|---|---|---|
| sandbox-runner | ① executes LLM-generated code | Separate service |
| worker | ② minute-long tasks, unlike short requests | Separate service |
| frontend | Separate build artefact | Separate deployment |
| gateway / rag / data / llm | None | Modules inside api |
| harness | Not an online service | CLI |

**Module boundary constraint**: dependencies between modules are one-directional; reverse references are forbidden. Direction is enforced by a static check in CI.

```
agents ──▶ rag ──▶ data
   │        │
   ├──────▶ llm
   └──────▶ tools ──▶ (sandbox HTTP)
gateway ──▶ agents
```

See decision D05 in the Technical Decision Handbook.

### 3.4 Request lifecycle

```
1. Client → api  POST /v1/research
2. api/gateway:  JWT check → RBAC → rate limit → injection detection → generate trace_id
3. api:          create research_run (status=queued) → publish to Redis Stream
4. api → Client: 202 { run_id, trace_id }
5. Client → api  GET /v1/research/{run_id}/events   (SSE subscription)
6. worker:       consume task → load LangGraph → execute
   6.1  Router classifies intent and complexity
   6.2  Orchestrator decomposes into sub-tasks + allocates token budget
   6.3  Parallel Analyst instances: rag retrieval → data lookup → sandbox computation → structured hand-back
   6.4  Synthesizer drafts → Critic verifies
   6.5  Checkpoint after every node; progress events pushed to Redis PubSub
7. api:          forwards progress events to the SSE channel
8. worker:       on completion → write report + citations → status=succeeded
9. Client:       receives completed event → GET /v1/research/{run_id} for the full report
```

---

## 4. Data model

### 4.1 ER overview

```
research_run ─┬─< run_event          (execution event stream)
              ├─< agent_invocation   (agent call records)
              ├─< llm_call           (model calls and cost)
              ├─< approval_request   (human approval)
              ├─< report ──< claim ──< claim_citation >── document_chunk
              └─< audit_log

document ──< document_chunk           (with embedding)
security ──< fundamental_fact         (bitemporal)
          └─< price_bar

eval_case ──< eval_run_result
eval_run ──< eval_run_result
```

### 4.2 Core tables

#### research_run — one research task

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| trace_id | text, indexed | End-to-end trace ID |
| user_id | uuid FK | |
| query | text | Original question |
| symbols | text[] | Securities involved |
| as_of_date | date | Information cut-off |
| depth | text | quick / standard / deep |
| status | text | queued / running / awaiting_approval / succeeded / failed / cancelled |
| complexity | text | Router result: simple / complex |
| graph_checkpoint_id | text | LangGraph checkpoint reference |
| token_budget | int | Allocated budget |
| tokens_used | int | Actual consumption |
| cost_usd | numeric(10,6) | |
| latency_ms | int | |
| error | jsonb | Failure details |
| created_at / updated_at | timestamptz | |

#### run_event — execution event stream (drives SSE and the execution tree)

| Column | Type | Notes |
|---|---|---|
| id | bigserial PK | |
| run_id | uuid FK, indexed | |
| seq | int | Monotonic sequence within a run |
| ts | timestamptz | |
| type | text | node_start / node_end / tool_call / llm_call / progress / error / approval_required |
| node | text | Graph node name |
| parent_node | text | For building the execution tree |
| payload | jsonb | Event details |

#### agent_invocation — agent call records

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK | |
| agent | text | router / orchestrator / analyst / synthesizer / critic |
| model | text | Model actually used |
| input_tokens / output_tokens | int | |
| cost_usd | numeric | |
| latency_ms | int | |
| status | text | ok / degraded / failed |
| output | jsonb | Structured output |

#### document / document_chunk — documents and vectors

**document**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| doc_type | text | filing / announcement / news / research |
| symbol | text, indexed | Related security |
| title | text | |
| source_url | text | |
| **published_at** | timestamptz, indexed | **Time the information became known** (used for PIT filtering) |
| period_end | date | Reporting period (filings) |
| raw_uri | text | Location of the original file |
| content_hash | text, unique | Deduplication |

**document_chunk**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | This is the `source_id` |
| document_id | uuid FK | |
| ordinal | int | Chunk order |
| content | text | Chunk text |
| context_prefix | text | Document-level context prefix (used for embedding) |
| token_count | int | |
| embedding | vector(1024) | pgvector; dimension follows the embedding model (decision D11) |
| tsv | tsvector | Full-text index, generated with a Chinese tokenizer configuration (§8.1) |
| metadata | jsonb | Table markers, section path, etc. |

Indexes:
```sql
CREATE INDEX ON document_chunk USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX ON document_chunk USING gin (tsv);
CREATE INDEX ON document (symbol, published_at DESC);
```

> For the semantics of filtered vector search see §8.6: on an HNSW index, filters apply after the index scan, so the stricter the filter, the higher the risk of returning too few results.

#### fundamental_fact — financial facts (bitemporal)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| symbol | text | |
| metric | text | revenue / net_income / gross_margin / ... |
| period_end | date | **Event time** (reporting period) |
| **known_at** | timestamptz | **Knowledge time** (moment of disclosure) |
| value | numeric | |
| unit | text | |
| revision | int | Revision number; 0 is the first release |
| source_document_id | uuid FK | |

Unique constraint: `(symbol, metric, period_end, revision)`

PIT query semantics:
```sql
-- latest revision known as of the cut-off
SELECT DISTINCT ON (symbol, metric, period_end) *
FROM fundamental_fact
WHERE symbol = :symbol AND known_at <= :as_of
ORDER BY symbol, metric, period_end, revision DESC;
```

#### security — security master data (guards against survivorship bias)

| Column | Type | Notes |
|---|---|---|
| symbol | text PK | |
| name | text | |
| listed_at | date | |
| **delisted_at** | date NULL | Delisted securities **stay in the database** and are never deleted |
| former_symbols | text[] | Renaming history |

#### claim / claim_citation — claims and citations

**claim**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| report_id | uuid FK | |
| section | text | |
| text | text | Claim text |
| verified | bool | Critic verification result |

**claim_citation**: `(claim_id, chunk_id, relevance)` — many-to-many

**Constraint**: a claim with `verified = true` must have at least one citation; claims without citations never enter the final report. The constraint spans two tables and cannot be expressed as a plain CHECK constraint; it is enforced by application-level validation inside the report-writing transaction and covered by a test (§20.3).

#### eval_case / eval_run / eval_run_result — evaluation

**eval_case**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| category | text | factual / analytical / retrieval |
| query | text | |
| symbols | text[] | |
| as_of_date | date | |
| ground_truth | jsonb | Objective answer and tolerance / rubric and key points / relevant chunk labels |
| split | text | dev / holdout |
| tags | text[] | For stratified statistics |

**eval_run**: `(id, git_sha, config_hash, variant, started_at, finished_at, summary jsonb)`
**eval_run_result**: `(eval_run_id, case_id, scores jsonb, tokens, cost_usd, latency_ms, trace_id, artifacts jsonb)`

#### approval_request — human approval

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK, indexed | |
| reason | text | Trigger reason code: unverified_core / critic_unresolved / restricted_data |
| payload | jsonb | References to the related claims, data source and draft report |
| requested_by | uuid FK | Task initiator |
| status | text | pending / approved / rejected / expired / withdrawn |
| decided_by | uuid FK NULL | Approver |
| comment | text NULL | Approver's comment, required on rejection |
| created_at | timestamptz | |
| expires_at | timestamptz, indexed | Expiry time, used by the periodic scan |
| decided_at | timestamptz NULL | |

Constraints: `decided_by <> requested_by` (in production configuration); at most one `pending` request per run at any time (partial unique index `ON approval_request (run_id) WHERE status = 'pending'`).

#### audit_log — audit

`(id, ts, trace_id, user_id, action, resource, params_digest, result, ip)`

**Retention**: audit_log and run_event are partitioned by time with a configurable retention period.

---

## 5. API contract

All endpoints are prefixed `/v1`; requests and responses are JSON; errors follow a common format.

### 5.1 Research tasks

| Method | Path | Description |
|---|---|---|
| POST | `/v1/research` | Create a research task → `202 {run_id, trace_id}` |
| GET | `/v1/research/{run_id}` | Task status and result |
| GET | `/v1/research/{run_id}/events` | **SSE** live event stream |
| GET | `/v1/research/{run_id}/trace` | Execution tree (nodes, duration, tokens, cost) |
| POST | `/v1/research/{run_id}/cancel` | Cancel a task |
| POST | `/v1/research/{run_id}/approve` | Human approval (approve / reject); permissions and semantics in §13.5.2 |

**SSE event types**
```
event: node_start   data: {node, parent, ts}
event: node_end     data: {node, status, tokens, cost_usd, latency_ms}
event: progress     data: {message, pct}
event: partial      data: {section, text}          # streamed report fragment
event: approval_required data: {reason, payload}
event: completed    data: {run_id}
event: error        data: {code, message}
```

### 5.2 Retrieval and data

| Method | Path | Description |
|---|---|---|
| POST | `/v1/search` | Hybrid search returning chunks + scores (for debugging and citation tracing in the UI) |
| GET | `/v1/documents/{id}` | Document details |
| GET | `/v1/chunks/{id}` | Chunk text (for citation links) |
| GET | `/v1/fundamentals` | PIT financial data query; `as_of` is required |
| GET | `/v1/prices` | Price series |

### 5.3 System

| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe (DB / Redis connectivity) |
| GET | `/metrics` | Prometheus metrics |

### 5.4 Error format

```json
{
  "error": {
    "code": "BUDGET_EXCEEDED",
    "message": "Token budget exhausted before convergence",
    "trace_id": "…",
    "details": { "budget": 200000, "used": 201432 }
  }
}
```

**Error code families**: `AUTH_*` / `RATE_*` / `VALIDATION_*` / `BUDGET_*` / `UPSTREAM_*` / `GUARDRAIL_*` / `INTERNAL_*`

---

## 6. Multi-agent orchestration

### 6.1 Roles

Two kinds of role are distinguished:

- **Agent**: the model decides in a loop which tools to call and how many times.
- **Workflow step**: a model call at a fixed position in the graph, with no tool loop.

Anything a workflow step can handle is not made an agent. More autonomy means more cost, latency and failure surface, and harder evaluation. By this principle, the Analyst is the only true agent in the initial role set.

#### Initial role set

| Role | Kind | Model tier | Input | Output | Tools |
|---|---|---|---|---|---|
| **Router** | Step | fast | query | `{intent, complexity, entities, reason}` | — |
| **Orchestrator** | Step (re-entered when the Critic rejects) | strong | query, complexity, entities | `{subtasks[], budget_allocation}` | — |
| **Analyst** | Agent, instantiated in parallel per sub-task | fast / medium | subtask | `AnalystFinding` | rag_search, get_fundamentals, get_prices, calc, fetch_chunk |
| **Synthesizer** | Step | strong | findings[] | Draft `Report` | — |
| **Critic** | Step (code checks + model judgement) | medium | report | `{verdict, issues[]}` | verify_citation, calc |

The Analyst is one agent definition run as several instances: the Orchestrator splits the question by "security × research dimension", each sub-task gets its own instance, and each instance runs in an isolated context. Research dimensions (financial, operating, risk, and so on) are distinguished by the sub-task description, not by separate agents.

#### Candidate extensions

The roles below are not in the initial set. Each may be added only if its precondition holds and an incremental experiment (§12.5) shows it helps.

| Candidate | Problem addressed | Precondition |
|---|---|---|
| Sentiment Analyst | News and sentiment | A news data source that can be used lawfully, with licensing |
| Macro Analyst | Macro and industry factors | Macro and industry data integration |
| Bull / Bear debate | Confirmation bias | P3's current measures are shown to fall short on "counter-evidence coverage" |

Technical analysis (price trends, technical indicators) mainly serves trading decisions and is out of scope.

Model tier mapping: see §10.2.

### 6.2 Graph state

```python
class GraphState(TypedDict):
    # input
    run_id: str
    trace_id: str
    query: str
    symbols: list[str]
    as_of_date: date
    depth: Literal["quick", "standard", "deep"]

    # routing
    intent: Literal["fact_lookup", "research", "comparison", "followup", "out_of_scope"] | None
    complexity: Literal["simple", "complex"] | None

    # budget
    token_budget: int
    tokens_used: int
    budget_by_subtask: dict[str, int]

    # intermediate artefacts (structured, no raw text)
    subtasks: list[Subtask]
    findings: list[AnalystFinding]
    draft: Report | None
    critic_issues: list[Issue]

    # control
    orchestrator_rounds: int
    degraded_subtasks: list[str]
    approval: ApprovalState | None

    # output
    report: Report | None
```

### 6.3 Graph topology

```
            ┌──────────┐
  START ───▶│  router  │
            └────┬─────┘
     fact_lookup │  research / comparison / followup
       ┌─────────┴──────────┐
       ▼                    ▼
 ┌───────────┐      ┌──────────────┐
 │   fixed   │      │ orchestrator │◀────────────┐
 │ workflow  │      └──────┬───────┘             │
 └─────┬─────┘             │ fan-out             │ follow-up (≤K rounds)
       │          ┌────────┼────────┐            │
       │          ▼        ▼        ▼            │
       │     ┌─────────┬─────────┬─────────┐     │
       │     │analyst 1│analyst 2│analyst n│     │
       │     └────┬────┴────┬────┴────┬────┘     │
       │          └─────────┼─────────┘          │
       │                 fan-in                  │
       │                    ▼                    │
       │           ┌────────────────┐            │
       │           │  synthesizer   │            │
       │           └───────┬────────┘            │
       │                   ▼                     │
       │           ┌────────────────┐            │
       │           │     critic     │──reject────┘
       │           └───────┬────────┘
       │              pass │
       └───────────────────┴──────▶ finalize ──▶ END
```

**Conditional edges**

| From | Condition | To |
|---|---|---|
| router | `intent == "fact_lookup"` | fixed_workflow |
| router | `intent ∈ {research, comparison, followup}` | orchestrator |
| router | `intent == "out_of_scope"` | finalize (guardrail refusal with explanation) |
| orchestrator | Sub-tasks ready | Fan out to analyst instances |
| analysts | All finished or timed out | synthesizer |
| critic | `verdict == "pass"` | finalize |
| critic | `verdict == "reject"` and `orchestrator_rounds < K` | orchestrator (follow-up on missing items only) |
| critic | `verdict == "reject"` and rounds exhausted | finalize (failing items flagged) |
| any node | Budget exhausted | finalize (degraded output) |

### 6.4 Node specifications

#### router (intent classification + complexity routing)

Two layers:

**1. Intent classification** — assigns the query an intent type, which selects the workflow:

| Intent | Meaning | Route |
|---|---|---|
| `fact_lookup` | A single fact or single-step calculation (a metric value, a year-on-year change) | Fixed workflow |
| `research` | Multi-dimensional research on one security | Multi-agent flow |
| `comparison` | Cross-sectional comparison of several securities | Multi-agent flow, fanned out by security |
| `followup` | A follow-up question on an existing report | Multi-agent flow, reusing session context and memory |
| `out_of_scope` | Outside the system's scope (trading instructions, price predictions, buy/sell advice) | Guardrail refusal |

The router also returns **extracted entities** (securities, time range, metrics), used to fill tool arguments downstream.

**2. Complexity** — within the multi-agent flow, decides the number of sub-tasks and the budget tier, based on whether the question needs several dimensions, compares several securities, or requires time-series reasoning.

Output is structured; `intent` and `reason` are used to evaluate intent and routing accuracy.

#### fixed_workflow (fact_lookup)

```
resolve entities → get_fundamentals (PIT) → calc if needed → code-check the source of every value → output with citations
```

It bypasses the Orchestrator and never enters an agent loop. It falls back to rag_search over the original text only when structured data is missing. This path carries most simple questions and therefore sets the system's average cost and latency.

#### orchestrator

Responsibilities:
1. Decompose the query into a list of `Subtask`s, one Analyst instance per sub-task
2. **Create at least one dedicated sub-task for "Risks and counter-evidence"** (P3)
3. Allocate token budget by `depth` and `complexity` (§7.3)
4. When the Critic rejects, create follow-up sub-tasks for the missing items only, never re-running everything

#### analysts (parallel)

Uniform execution pattern:
```
receive Subtask (its own description only, no full history)
  → call tools for data (rag_search / get_fundamentals / get_prices / calc)
  → produce AnalystFinding
```

`AnalystFinding`:
```python
class Evidence(BaseModel):
    statement: str                  # one piece of evidence
    source_ids: list[str]           # required, at least one
    values: dict[str, float] = {}   # numbers involved (from structured sources or calc)

class AnalystFinding(BaseModel):
    subtask_id: str
    dimension: str                  # financial / operating / risk / ...
    summary: str
    evidence: list[Evidence]
    data_gaps: list[str] = []       # data that could not be obtained, for degradation notes
```

**Constraint**: entries whose `evidence[].source_ids` is empty are dropped before aggregation and counted in the `unsourced claim rate` metric.

Analysts are not asked for a self-reported confidence score: a model's stated confidence has no reliable relationship to its actual accuracy, so it is not used as the basis for any decision.

#### synthesizer

- Takes all `findings` (structured, not raw text) and produces a draft report
- Each claim may cite only `source_ids` already present in the findings; no new facts may be introduced
- The report must contain a "Risks and counter-evidence" section; every `data_gaps` entry must appear in the `unverified` list
- Where evidence conflicts, state the disagreement and each side's sources explicitly rather than choosing one without grounds

#### critic

Checks:

| Check | Method | On failure |
|---|---|---|
| Citation exists | `source_id` can be found in document_chunk | Remove the claim |
| Citation point in time | Cited document's `published_at <= as_of_date` | Remove the claim |
| Citation supports claim | Does the passage support the claim (model judgement) | Mark unverified |
| Numeric consistency | Every number in a claim appears in this run's tool results (code comparison) | Reject |
| Accounting identities | Accounting identity checks (§9.4) | Flag as questionable |
| Counter-evidence coverage | "Risks and counter-evidence" is non-empty and cited | Create a follow-up sub-task |
| Completeness | Any sub-question left unanswered | Create a follow-up sub-task |

Output: `{verdict: pass|reject, issues: [{type, claim_id, detail}]}`

### 6.5 Control mechanisms

| Mechanism | Rule |
|---|---|
| **Agent step limit** | Tool-call rounds per Analyst ≤ `MAX_AGENT_STEPS` (default 8) |
| **Orchestrator round limit** | Follow-up loop ≤ `MAX_ORCH_ROUNDS` (default 2) |
| **Token budget** | The global budget is allocated across sub-tasks; exceeding it forces convergence (§7.3) |
| **Loop detection** | Same agent calling the same tool with the same arguments 3 times in a row → that agent is stopped |
| **Degradation** | Analyst failure / timeout → recorded in `degraded_subtasks`; the report marks that part as missing |
| **Checkpoint** | A checkpoint is written to Postgres after every node (§15.0) |
| **HITL** | Triggers in §13.5; status set to `awaiting_approval` and execution suspended |

### 6.6 Agent definition convention

Each role consists of the following versioned files:

```
app/agents/<agent_name>/
  prompt.md          # system prompt (versioned; changes must pass the evaluation gate)
  schema.py          # input/output Pydantic models
  tools.py           # the subset of tools visible to this role
  config.yaml        # model tier, temperature, max_tokens, step limit
```

**Tool visibility principle**: each role sees only the tools its job requires, avoiding tool confusion.

---

## 7. Context engineering and memory

### 7.1 Context composition and quotas

The context of a single agent call is allocated by quota. The system prompt and tool definitions are fixed overhead and are deducted from the window first; the percentages below are **of the space remaining after fixed overhead**:

| Partition | Default quota | When exceeded |
|---|---|---|
| System prompt | Fixed overhead | — |
| Tool definitions | Fixed overhead | Trim the tool set per role |
| Sub-task description | ≤ 5% | Truncate |
| Retrieved passages | ≤ 55% | Truncate by rerank score |
| History / intermediate artefacts | ≤ 20% | Compress (§7.2) |
| Memory | ≤ 10% | Truncate by ranking (§7.4) |
| Output reserve | ≥ 10% | — |

Quotas are in tokens and enforced by `context/budget.py` before each request is built.

### 7.2 Context management strategies

| Strategy | Rule |
|---|---|
| **Sub-task isolation** | An Analyst receives only its own `Subtask` and its retrieval results, never other Analysts' intermediate artefacts or the full conversation |
| **Structured hand-back** | Analysts return `AnalystFinding` (conclusions + source_ids), **not the retrieved text** |
| **Just-in-time retrieval** | Retrieval is triggered on demand during execution, not prefetched when the graph starts |
| **Rolling compression** | When history exceeds its quota, the oldest content is summarised, keeping numeric facts, source_ids and open questions |
| **External offloading** | Raw text and large objects stay in Postgres; the context holds only `source_id` handles, and text is fetched on demand through a tool |
| **Positioning** | Key instructions go at the top of the system prompt; task requirements go at the end of the user message (mitigating weaker attention to the middle) |

### 7.3 Token budget algorithm

```
total budget = f(depth)
  quick: 60k   standard: 200k   deep: 500k

Orchestrator allocation:
  reserve_synth_critic = total × 0.25        # reserved for synthesis and verification
  analyst_pool         = total − reserve_synth_critic
  initial quota per sub-task = analyst_pool / len(subtasks)

At runtime:
  · unused sub-task quota returns to the pool and may be reallocated by the orchestrator for follow-ups
  · cumulative use reaches 80% of total → no new follow-up rounds
  · cumulative use reaches 95% of total → stop unfinished sub-tasks, go straight to synthesizer
  · cumulative use reaches 100% of total → force finalize, emit a degraded report with a notice
```

The llm module writes consumption back to `GraphState.tokens_used` after every LLM call.

---

### 7.4 Memory

#### 7.4.1 Motivation

Memory solves three concrete problems:

| Problem | What memory does |
|---|---|
| Waste when researching the same security again | Reuse recent verified conclusions and evidence, avoiding repeated retrieval and lookups |
| Follow-up questions lack context | Link to previous reports, supporting the `followup` intent |
| Users restate their focus every time | Remember the user's securities, dimensions and report style |

Memory is not an accumulation of chat history. Writes follow explicit rules, retrieval has a quota, and expiry is handled; otherwise memory turns into retrieval noise and crowds the context.

#### 7.4.2 Memory types

| Type | Content | Written when | Used by |
|---|---|---|---|
| **Working memory** | Graph state within one run | During graph execution | All roles |
| **Episodic** | Conclusions from past reports that passed Critic verification, with their source_ids | Run completes successfully | Orchestrator (deciding which sub-tasks can be reused), followup |
| **Semantic** | Stable facts (industry, business mix, controlling shareholder) | Extracted from reports and deduplicated | Analyst (less repeated retrieval) |
| **User preferences** | Securities followed, report style, dimensions of interest | Explicit settings + behavioural inference | Router / Synthesizer |

Procedural memory (deriving analysis paths from high-scoring trajectories) is left for later exploration (§23 M5), once the evaluation set is large enough to distinguish high-scoring trajectories from chance.

#### 7.4.3 Data model

**memory_item**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| scope | text | user / global / symbol |
| scope_key | text | user_id or symbol |
| kind | text | episodic / semantic / preference |
| content | jsonb | Structured memory content, including source_ids |
| embedding | vector(1024) | For semantic retrieval |
| source_run_id | uuid FK | Originating run |
| as_of_date | date | Information cut-off the memory was produced under |
| valid_from / valid_to | timestamptz | Validity window for freshness filtering |
| access_count | int | Hit count, used for decay |
| superseded_by | uuid FK NULL | Points to the newer memory when replaced |

#### 7.4.4 Memory lifecycle

**Write (explicit rules, no indiscriminate recording)**

| Type | Write condition |
|---|---|
| episodic | The run completed successfully and the conclusion passed every Critic check |
| semantic | The fact is supported by ≥ 2 independent sources and does not vary by reporting period |
| preference | Set explicitly by the user, or the same behaviour repeated ≥ 3 times |

**Retrieve**

```
filter by scope (user / symbol)
  → point-in-time filter: as_of_date <= the current run's as_of_date (memory obeys PIT too)
  → semantic search (embedding) + freshness filter (valid_to >= now)
  → rank by freshness decay × access_count
  → inject into the memory partition of the context (quota in §7.1)
```

**Reuse constraint**: conclusions reused from memory must still carry their original source_ids in the report and pass this run's Critic checks. Memory saves retrieval and lookups; it never skips verification.

**Updates and conflict resolution**

When a new memory contradicts an existing one:
1. Compare disclosure times and revision numbers of the sources (the later disclosure wins)
2. If the new memory wins → set `superseded_by` and `valid_to` on the old one; **never physically delete it** (traceability is preserved)
3. If undecidable → keep both, marked as conflicting; the Synthesizer states the disagreement explicitly in the report

**Decay**: memories past their freshness window are down-weighted; memories not hit for a long time are archived periodically.

**Verification**: for repeated research on the same security, compare cost, latency and evaluation metrics with memory on and off; metrics must not drop.

---

## 8. RAG subsystem

### 8.1 Ingestion pipeline

```
Raw documents (filing PDFs / announcements / news HTML)
  │
  ├─ 1. Parse: extract body text + table structure + heading hierarchy
  │       tables become Markdown tables, with cell coordinates kept in metadata
  │
  ├─ 2. Normalise: strip headers and footers, join broken lines, unify number formats
  │
  ├─ 3. Chunk: semantic chunking
  │       target 512 tokens, 64-token overlap
  │       tables never split across chunks; long tables split by row with the header repeated
  │       section headings kept as chunk prefixes
  │
  ├─ 4. Contextualise: generate a document-level prefix for each chunk
  │       (document title + section + reporting period), embedded together with the text
  │
  ├─ 5. Embed: vectorise → document_chunk.embedding
  │
  └─ 6. Index: HNSW vector index + GIN full-text index + metadata indexes
          The full-text tsvector is generated with a Chinese tokenizer configuration
          (zhparser or pg_jieba). PostgreSQL's default parser splits on spaces and
          punctuation, so a whole Chinese sentence becomes one token; without a
          Chinese tokenizer, keyword search is effectively useless
```

**Idempotency**: deduplication by `content_hash`; re-ingesting the same document creates no new records.

### 8.2 Retrieval pipeline

```
query
 ├─ 1. Query rewriting: conversational question → retrieval-friendly query; expanded into several queries if needed
 ├─ 2. Metadata filters: symbol ∈ target securities
 │                       published_at <= as_of_date     ← hard PIT constraint
 │                       doc_type ∈ allowed types
 ├─ 3. Parallel recall
 │      · vector search: cosine top-k (k=50)
 │      · keyword search: top-k (k=50); scoring discussed below
 ├─ 4. Fusion: RRF (Reciprocal Rank Fusion), k=60
 ├─ 5. Rerank: cross-encoder over the fused top 30
 └─ 6. Return: top-n (n set by the caller's quota, default 8) + score + source_id
```

**The PIT constraint is hard**: the retrieval layer always appends `published_at <= as_of_date`; it does not rely on callers passing the right parameters.

**Keyword scoring**: PostgreSQL's built-in `ts_rank` is frequency-based, not BM25, with no term-frequency saturation or document-length normalisation. Options:

| Option | Notes |
|---|---|
| `ts_rank` + Chinese tokenizer | No extra components; ranking weaker than BM25 |
| A PostgreSQL extension with BM25 | In-database; Chinese tokenizer support and deployment cost need assessment |
| Application-level BM25 (jieba tokenisation) | Simple to build; a separate inverted index must be maintained as the corpus grows |

The choice is made by retrieval evaluation (§8.5); see decision D08. RRF fuses by rank, not raw score, so the scoring algorithm mainly affects ordering within the keyword branch.

### 8.3 Retrieval parameters

| Parameter | Default | Notes |
|---|---|---|
| chunk_size | 512 tokens | |
| chunk_overlap | 64 tokens | |
| vector_top_k | 50 | |
| bm25_top_k | 50 | Keyword branch top-k |
| rrf_k | 60 | |
| rerank_input | 30 | |
| final_top_n | 8 | Bounded by the context quota |
| min_rerank_score | Configurable | Passages below the threshold are dropped |

All parameters are part of `config_hash`; evaluation results are bound to the parameter set.

### 8.4 Citation binding and verification

**Binding**: every `Evidence` produced by an Analyst must carry `source_ids`, whose values are `document_chunk.id`.

**Verification (Critic stage)**:

| Check | Implementation |
|---|---|
| Existence | `SELECT 1 FROM document_chunk WHERE id = ANY(:ids)` |
| Point in time | The cited document's `published_at <= as_of_date` |
| Support | The chunk text and the claim are sent to a model to judge support |

Claims failing existence or point-in-time checks are removed; claims failing the support check are marked `unverified` and excluded from the final conclusions.

### 8.5 Standalone retrieval evaluation

Retrieval is evaluated on its own, separately from generation quality:

| Metric | Definition |
|---|---|
| Recall@k | Share of labelled relevant chunks that are retrieved |
| MRR | Mean reciprocal rank of the first relevant chunk |
| NDCG@k | Relevance gain weighted by rank position |

The evaluation set contains `(query, as_of_date, labelled relevant chunk_ids)`. Retrieval regressions can thus be located separately from generation problems.

### 8.6 VectorStore abstraction

Retrieval depends on a `VectorStore` interface, not a specific vector database, so the implementation is replaceable:

```python
class VectorStore(Protocol):
    async def upsert(self, items: list[ChunkVector]) -> None: ...
    async def search(
        self, embedding: list[float], top_k: int,
        filters: MetadataFilter,          # symbol / published_at / doc_type
    ) -> list[ScoredChunk]: ...
    async def delete(self, ids: list[str]) -> None: ...
```

**Default implementation: pgvector.** Comparison:

| Option | Strengths | Weaknesses | Fits when |
|---|---|---|---|
| **pgvector** (chosen) | Same database as business data; metadata filters and vector search in **one query**, with no cross-store consistency problem; few operational components | Index build and query performance weaker than dedicated stores at very large scale | Under tens of millions of vectors, with retrieval that depends heavily on metadata filters |
| Milvus / Qdrant | Strong at scale; distributed; more index types | Separate deployment and operations; metadata must be synced with the business database, with a consistency cost | Large vector volumes or independent scaling |
| FAISS | High single-node performance, no service dependency | No persistence or filtering; must be wrapped by hand | Offline batch retrieval, experiments |
| Chroma | Quick to start | Limited production features and scale | Prototypes |

**The deciding reason for pgvector**: retrieval here **depends heavily on metadata filters** (the PIT constraint `published_at <= as_of_date` is mandatory). Running vector search and metadata filters in one SQL statement keeps filter conditions consistent with business data by construction, with no consistency risk from syncing document metadata into another store.

**Filtered recall shortfall**: on approximate indexes such as HNSW, pgvector applies filters **after the index scan**: the index first returns a batch of candidates according to `hnsw.ef_search`, then the WHERE clause is applied. The stricter the filter (a single security, before a given date), the fewer candidates qualify, and fewer than k results may be returned. Remedies:

| Measure | Effect |
|---|---|
| Iterative index scans (pgvector ≥ 0.8, `hnsw.iterative_scan`) | Keep scanning the index when candidates run short, up to the requested count or a cap |
| Partition by security, or partial indexes for frequent filters | The index itself covers only the target range |
| Exact search when the candidate set is small | A single security has a bounded number of chunks; a sequential scan is fast enough and exact |
| Monitor result counts per search | Record a metric whenever fewer than k results are returned, to guide parameter tuning |

Retrieval evaluation (§8.5) stratifies Recall@k by filter strictness to confirm whether these measures suffice.

**Switching cost**: the abstraction confines a switch to one implementation class; the evaluation harness can compare implementations on equal terms. Triggers for switching are in §22.

---

## 9. Financial data subsystem (point-in-time)

### 9.1 Bitemporal model

Every fact records two times:

| Time | Column | Meaning |
|---|---|---|
| **Event time** | `period_end` / `bar_date` | The business moment the data describes (for example reporting period 2026-Q1) |
| **Knowledge time** | `known_at` / `published_at` | When the information actually became public |

Financial statements are disclosed with a lag (weeks to months after the period ends); the two times must never be conflated.

### 9.2 PIT query semantics

Every data query **must** pass `as_of`; the filter is always `known_at <= as_of`.

```python
def get_fundamentals(symbol: str, metrics: list[str], as_of: datetime) -> list[Fact]:
    """Return the latest revision actually known as of `as_of`."""
```

**Implementation constraints**:
- `as_of` is required and has no default, so callers cannot omit it
- The data layer offers no query path that bypasses PIT
- Online research and evaluation runs share the same query function, guaranteeing consistency

**PIT cannot constrain the model's own knowledge**: PIT only guarantees that the data given to the model contains nothing from after the cut-off. The model, however, read a great deal of public material during training and may "remember" what happened after the cut-off. The system's answer is the four lines of defence in §2 P1: facts and numbers may come only from this run's tool results, the Critic compares every number in the report by code, and unsourced assertions never enter the report. The model's training knowledge therefore cannot enter a report in the form of a "fact".

### 9.3 Revisions and survivorship bias

| Problem | Handling |
|---|---|
| **Restatements** | Several `revision`s are kept for the same `(symbol, metric, period_end)`; PIT queries take the highest `revision` with `known_at <= as_of` |
| **Survivorship bias** | The `security` table keeps delisted securities (`delisted_at` not null); historical queries do not exclude them |
| **Symbol changes** | `former_symbols` records renaming history; queries normalise symbols |

### 9.4 Accounting identity checks

Run once at ingestion and once in the Critic stage:

| Identity | Tolerance |
|---|---|
| Assets = Liabilities + Equity | ≤ 0.5% |
| Gross profit = Revenue − Cost of revenue | ≤ 0.5% |
| Net income = Profit before tax − Income tax | ≤ 0.5% |
| Closing cash = Opening cash + Net cash flow | ≤ 1% |

On failure: at ingestion the record is marked with `quality_flag`; at the Critic stage the related claims are flagged as questionable and the report says so.

---

## 10. LLM module

### 10.1 Responsibility

Wraps all model calls behind one interface providing routing, retries, caching, cost accounting, token counting and streaming. Business code depends on no vendor SDK directly.

### 10.2 Model tiers

| Tier | Use | Typical roles |
|---|---|---|
| `strong` | Complex planning, report synthesis | orchestrator, synthesizer |
| `medium` | Verification, more complex analysis sub-tasks | critic, analyst (depth=deep) |
| `fast` | Classification, parallel lookup and analysis | router, analyst |

Tier-to-model mappings are declared in configuration; business code refers only to tier names, so models can be switched wholesale and compared in evaluation.

**Mainland China deployment constraint**: Anthropic's model services are not offered in mainland China. A demo environment hosted in mainland China must map tiers to models that can be called there compliantly (for example Qwen, DeepSeek); the tier abstraction makes this a configuration change only. The quality difference between mappings is quantified by the evaluation harness.

### 10.3 Call interface

```python
class LLMRequest(BaseModel):
    tier: Literal["strong", "medium", "fast"]
    system: str
    messages: list[Message]
    tools: list[ToolSpec] | None
    response_schema: type[BaseModel] | None    # structured output
    max_tokens: int
    temperature: float
    cache_segments: list[str] = []             # prefix segments to cache
    trace_context: TraceContext                # trace_id / run_id / agent / node

class LLMResponse(BaseModel):
    content: str | BaseModel
    tool_calls: list[ToolCall]
    usage: Usage          # input/output/cache_read/cache_write tokens
    cost_usd: Decimal
    model: str
    latency_ms: int
```

### 10.4 Structured output

- Prefer the tool-calling mechanism to constrain output structure
- Validate responses against `response_schema`; on failure, return the error to the model and retry, at most twice
- After a second failure, mark the agent `failed` and degrade

### 10.5 Caching

| Cache | Content | Invalidation |
|---|---|---|
| Prompt cache | System prompt + tool definitions + long document prefixes | Invalidated when content changes |
| Result cache (Redis) | `hash(tier, system, messages, tools, params)` → response | Configurable TTL; off by default in evaluation mode |

**The result cache must be disabled in evaluation mode**; otherwise evaluation data is distorted.

### 10.6 Retries and degradation

| Case | Policy |
|---|---|
| Rate limited (429) | Exponential backoff with jitter, at most 5 retries |
| Timeout | Retry once; if it fails again, degrade the node |
| 5xx | Exponential backoff, at most 3 retries |
| Schema validation failure | Retry with the error message, at most 2 times |
| Content refusal | No retry; log and degrade |

**Global retry budget**: model calls, queue consumption (§15.2) and task recovery (§15.0) each retry independently, so in the worst case the counts multiply and one call may be repeated dozens of times, amplifying cost and load during an outage. Therefore:

- Each run has a total retry budget (default: at most 20 cumulative model-call retries); once spent, no further retries happen and the degradation path is taken
- Upper-layer retries (queue redelivery, task recovery) resume from the checkpoint and do not replay completed model calls, so they do not stack with lower-layer retries
- Retry counts are recorded in the `llm_retries_total` metric for alerting

### 10.7 Cost accounting

Every call writes to the `llm_call` table: `(run_id, agent, node, model, input_tokens, output_tokens, cache_read_tokens, cost_usd, latency_ms)`.

Cost is computed from a model price table maintained and versioned in configuration. Aggregated views: per run, per agent, per model, over time.

---

## 11. Tools and sandbox

### 11.1 Tool registry

```python
class ToolSpec(BaseModel):
    name: str
    description: str                # directly affects tool selection accuracy; changes must pass evaluation
    input_schema: type[BaseModel]
    handler: Callable
    required_scopes: list[str]      # RBAC permission bits
    timeout_s: float
    idempotent: bool
```

### 11.2 Tools

| Tool | Input | Output | Visible to |
|---|---|---|---|
| `rag_search` | query, symbols, doc_types, top_n | chunks[] + source_ids | analyst, fixed_workflow (fallback) |
| `get_fundamentals` | symbol, metrics, as_of | facts[] | analyst, fixed_workflow |
| `get_prices` | symbol, start, end, as_of | bars[] | analyst (prices and market cap needed for valuation) |
| `calc` | expression / script, inputs | result | analyst, fixed_workflow, critic |
| `verify_citation` | claim, source_ids | supported: bool | critic |
| `fetch_chunk` | chunk_id | Original text | analyst, critic (fetch text on demand) |

When a candidate extension role (§6.1) is added, its dedicated tools (news search, macro data, and so on) come with it.

**`as_of` is injected by the framework**, never filled in by the model, so the model cannot bypass the PIT constraint.

### 11.3 Argument validation

Before a tool call executes:

1. Pydantic schema validation
2. Permission check: caller scopes ⊇ `required_scopes`
3. Range checks: symbol allowlist, date range, top_n ceiling
4. Injection check: detect instruction-like content in string arguments

Any failure → a structured error is returned to the model, which may correct and retry (counted against the step limit).

### 11.4 Error feedback

Tool errors must be usable by the model: error type, reason and a feasible correction.

```json
{ "error": "INVALID_SYMBOL", "message": "Symbol 'XYZ' not found",
  "hint": "Use search_security to resolve the correct symbol code." }
```

### 11.5 Parallel tool calls

When the model requests several tool calls in one turn, they run concurrently if all are `idempotent` and independent; otherwise sequentially. Concurrency is capped by configuration.

### 11.6 sandbox-runner

**Purpose**: execute numeric calculation scripts in place of LLM arithmetic.

**Interface**
```
POST /execute
  { code: str, inputs: dict, timeout_s: float }
→ { status: ok|error|timeout, result: any, stdout: str, error: str|null, duration_ms: int }
```

**Isolation model: two layers**

| Layer | Responsibility | Isolation |
|---|---|---|
| Executor service (long-running HTTP) | Accept requests, validate, dispatch, collect results | Attached only to an internal network with no internet egress |
| Execution process (new per request) | Run the generated code | A brand-new subprocess per execution, destroyed afterwards; `/tmp` cleared each time |

Every execution runs in a new process, so one piece of code cannot affect the next or modify the executor service. If stronger isolation is needed later, the execution process can be upgraded to one container per execution or a user-space kernel sandbox such as gVisor, with the interface unchanged.

**Constraints**

| Dimension | Limit |
|---|---|
| Network | The executor service is attached only to an `internal: true` Docker network: api/worker can reach it, it cannot reach the internet. Execution processes need no network at all |
| Filesystem | Read-only root filesystem; only `/tmp` writable, capped, and cleared after each execution |
| Memory | 512 MB |
| CPU | 1 core |
| Processes | `pids_limit: 64` |
| Execution time | Default 5 s, maximum 30 s; the execution process is killed on timeout |
| Dependencies | Only the numeric libraries required are installed in the image |
| Privileges | Non-root user, `cap_drop: ALL`, `no-new-privileges` |

**The security boundary is container and process isolation, not a Python-level module allowlist**: standard modules such as `os` and `subprocess` cannot be reliably disabled through import restrictions; there are many ways around them. The design assumes generated code can run arbitrary Python and relies on the isolation above to make that harmless.

**Input and output**: only JSON-serialisable inputs and results; no access to external state.

### 11.7 MCP integration

The system uses the **Model Context Protocol** in both directions.

#### As an MCP server (exposing capabilities)

Research capabilities are packaged as a standard MCP server, so internal tools can be reused by other agent systems instead of each consumer reimplementing data access:

| Exposed tool | Description |
|---|---|
| `rag_search` | Document retrieval with PIT constraints |
| `get_fundamentals` | PIT financial data queries |
| `get_prices` | Price series |
| `run_research` | Start a full research task (asynchronous, returns run_id) |
| `get_report` | Fetch a research report |

**Design constraints**:
- The MCP server reuses the same tool implementations and permission checks; there is no side path
- `as_of` is equally mandatory; external callers cannot bypass PIT
- Separate authentication and quota channel, metered separately from internal calls

#### As an MCP client (consuming external tools)

The tool registry can load tools dynamically from external MCP servers:

```python
class MCPClientConfig(BaseModel):
    server_name: str
    endpoint: str
    allowed_tools: list[str]      # allowlist; the server's full declared tool list is not trusted automatically
    required_scopes: list[str]
    timeout_s: float
```

**Security constraints**:
- External MCP tools require an explicit allowlist and are never registered automatically
- Content returned by external tools is treated like retrieved content — **data, not instructions** (§13.3)
- External tool calls are audited and metered like any other

#### Relationship to native tools

Native tools and MCP tools are unified at the `ToolSpec` level; agents call them identically. MCP is an **access protocol** and does not change the core tool-calling mechanism.

---

## 12. Evaluation harness

### 12.1 Role

The harness is a CLI and library run locally and in CI; it is not an online service. It is the system's quality yardstick and its defence against regression.

### 12.2 Evaluation set strata

| Category | Composition | Grading |
|---|---|---|
| **factual** | Questions with a single objective answer | Exact numeric / string match (with tolerance) |
| **analytical** | Open analysis questions | LLM-as-judge + rubric |
| **retrieval** | Retrieval-labelled items | Recall / MRR / NDCG |

Every item carries an `as_of_date`, and evaluation strictly follows PIT. Every item carries a `split`: tuning uses only the development set (dev); the holdout set runs only at milestone acceptance. factual items also label the document and page of their gold evidence, so retrieval failures and generation failures can be located separately.

### 12.3 Metrics

| Metric | Computation |
|---|---|
| `numeric_accuracy` | Correct numbers / total numbers answered (relative error within tolerance counts as correct) |
| `citation_validity` | Citations passing existence + point-in-time + support checks / total citations |
| `unsourced_claim_rate` | Claims without a source_id / total claims |
| `rubric_score` | Weighted mean of the judge's scores per dimension (coverage / logic / strength of evidence / counter-evidence coverage) |
| `coverage` | Key points answered / total key points |
| `trajectory_score` | Tool selection accuracy, share of redundant steps, step-count percentiles |
| `intent_accuracy` | Accuracy of the Router's intent classification and routing |
| `cost_per_run` | USD per run |
| `latency_p50 / p95` | End-to-end latency percentiles |

### 12.4 Calibrating the LLM judge

Judges have their own biases (favouring longer answers, consistent formatting, and so on) and must be calibrated:

1. Have humans score a subset of the evaluation set (≥ 30 items)
2. Measure agreement between judge and human scores (Spearman correlation / weighted kappa)
3. If agreement falls below threshold, revise the rubric and judge prompt, then recalibrate
4. Recalibrate whenever the judge model changes

The judge uses a fixed model and a fixed prompt version; changes are part of `config_hash`.

### 12.5 Experiment design

#### Experiment A: single agent vs multi-agent

| Dimension | Content |
|---|---|
| Variable | Orchestration mode: single (one Analyst instance holding every tool handles the whole question) / multi (the full flow in §6.3) |
| Controls | Same evaluation set, same retrieval parameters, same `as_of_date`, result cache off |
| Observed | All quality metrics + cost_per_run + latency |
| Repeats | Each item run 3 times; report mean and standard deviation |
| Output | Quality–cost comparison curve |

#### Experiment B: incremental experiments (marginal contribution of components)

Start from the minimal configuration and add or remove one component at a time, holding everything else fixed.

| Dimension | Content |
|---|---|
| Variable | Presence of a single component: the Critic's model judgement, the counter-evidence sub-task, memory, candidate extension roles (§6.1), and so on |
| Observed | Change in each quality metric and in cost relative to the baseline |
| Decision rule | A change within the standard deviation of repeated runs → no significant contribution |
| Action | **Components with no significant or negative contribution are not kept**; those that help but cost too much are considered for conditional triggering |

#### Experiment C: retrieval and context strategies

| Dimension | Content |
|---|---|
| Variable | Chunking strategy, retrieval method (vector only / hybrid / hybrid + rerank), context management strategy (full / compressed / sub-task isolation) |
| Observed | Recall@k, numeric_accuracy, tokens, cost_per_run |
| Stratification | By question category and by filter strictness |

#### Experiment D: cost–quality Pareto

Sweep configuration combinations (tier mappings, top_n, sub-task granularity), plot quality against cost and the Pareto frontier, and use it to choose the default configuration.

### 12.6 Usage

```bash
harness run --suite factual --variant multi --repeat 3
harness compare --baseline baselines/v1.json --current runs/latest.json
harness ablate --components critic_judge,counter_evidence,memory
harness replay --run-id <uuid>          # replay a single run for debugging
harness report --out docs/EVAL_REPORT.md
```

Every run records `git_sha` and `config_hash`, so results are fully reproducible.

### 12.7 Regression gate

CI runs an evaluation subset (about 30% of items, fixed sampling seed) and compares it with the baselines in `baselines/`:

| Condition | Result |
|---|---|
| A key metric drops beyond threshold | Merge blocked |
| Cost rises beyond threshold | Merge blocked |
| Metrics improve | Prompt to update the baseline |

Thresholds must account for run variance: a drop greater than 2× the standard deviation is the criterion, avoiding false alarms from noise.

### 12.8 Failed-sample intake

Failed or low-scoring production samples enter a labelling queue automatically; once confirmed by a human, they are added to the evaluation set, growing the regression suite over time.

### 12.9 Improvement flywheel

Evaluation is not a one-off acceptance test but a closed loop that drives continuous improvement. The flywheel has five stages, each with defined inputs, outputs and level of automation.

```
      ┌──────────────────────────────────────────────┐
      │                                              │
      ▼                                              │
 ① Production ──▶ ② Signal ──▶ ③ Attribution ──▶ ④ Change ──▶ ⑤ Verify
   (live runs)    (failures/     (locate the        (prompt/     (evaluation
                   low scores/    failing stage)     params/      + gate)
                   user feedback)                    orchestration)
                                                                  │
      └───────────────────────────────────────────────────────────┘
                        verified → release → back to ①
```

#### Stages

| Stage | Input | Output | Automation |
|---|---|---|---|
| **① Production** | User requests | Run records, traces, reports | Fully automatic |
| **② Signal collection** | Run records | Candidate improvement samples | Fully automatic |
| **③ Attribution** | Candidate samples + traces | Failing stage identified | Semi-automatic (rules + human confirmation) |
| **④ Change** | Attribution conclusions | Prompt / parameter / orchestration changes | Manual (automatable later) |
| **⑤ Verification** | Changes | Evaluation comparison | Fully automatic (CI gate) |

#### ② Signal collection: which runs enter the flywheel

| Source | Condition |
|---|---|
| Explicit failure | run status = failed, or the Critic did not pass |
| Low quality | Unsourced claim rate above threshold, low coverage, questionable numeric checks |
| Cost anomaly | Token use or latency beyond the percentile for similar questions |
| Trajectory anomaly | Step limit exceeded, loop detection triggered, heavy degradation |
| User feedback | Explicit negative feedback or manual correction |

> **Critic interception records are a low-cost signal source**: claims removed or rejected by the Critic come with their failure type (citation missing, citation not supporting, number inconsistent) and can enter attribution without human labelling.

#### ③ Attribution: locating the failing stage

Collected samples are classified by failing stage, based on intermediate artefacts in the trace:

| Failing stage | Evidence | Typical fix |
|---|---|---|
| **Retrieval** | Relevant evidence exists but was not recalled (compared with retrieval labels) | Chunking, query rewriting, rerank threshold |
| **Tool calling** | Wrong tool, wrong arguments, many retries | Tool descriptions, schemas, error hint text |
| **Agent reasoning** | Sufficient evidence but a wrong conclusion | Agent prompt, model tier |
| **Orchestration** | Poor decomposition, missing dimensions | Orchestrator prompt, sub-task templates |
| **Synthesis** | Each Analyst conclusion is sound but the synthesis is wrong | Synthesizer prompt, conflict statement rules |
| **Data** | Source data missing or wrong | Data source coverage, accounting identity rules |

Attribution results are written to the `improvement_case` table and aggregated by failing stage **to prioritise improvement work** — the stage with the largest share is fixed first.

#### ④ Change and ⑤ Verification

- Prompts and configuration are versioned files; changes go through the same CI gate
- Every change must be linked to the `improvement_case` set it targets, and the fix rate on that set is verified afterwards
- **No regression** is verified at the same time: the full evaluation set must not drop (avoiding "fix one class, break another")

#### Flywheel health metrics

The flywheel itself must be measured, or there is no way to know whether it works:

| Metric | Definition |
|---|---|
| `case_intake_rate` | Candidate samples entering the flywheel per unit time |
| `attribution_coverage` | Share of samples attributed |
| `fix_rate` | Share of samples fixed after a change |
| `regression_rate` | Share of changes that introduce new problems |
| `evalset_growth` | Growth of the evaluation set (from intake) |
| `cycle_time` | Time from sample collection to passing verification |

#### Automation boundary

Stage ④ is currently manual. Automatic prompt optimisation (iterating on evaluation feedback automatically) is deferred, **on the precondition that evaluation signals are stable** — with high evaluation variance, automatic optimisation converges toward noise. Triggers are in §22.

---

## 13. Security and governance

### 13.1 Authentication and authorisation

- **Authentication**: JWT (HS256/RS256), short-lived access token + refresh token
- **Authorisation**: RBAC, roles → scopes; tools and data endpoints declare `required_scopes`
- **Data permissions**: documents carry a classification and permitted roles; access to securities and document types can be restricted by role. Permission filters are part of the retrieval SQL and apply before similarity is computed: content the user may not see never enters the context, rather than entering it and the model being asked not to output it

### 13.2 Rate limiting

| Dimension | Policy |
|---|---|
| Per user | Token bucket limiting both QPS and concurrent tasks |
| Global | Cap on concurrent research tasks, protecting downstream model quotas |
| Cost | Per-user / per-tenant daily cost ceiling; new tasks rejected when exceeded |

Implemented on Redis, so limiter state is shared across api replicas.

### 13.3 Prompt injection defence

**Direct injection** (user input):

1. Rule-based detection at the entry point (instruction-override patterns)
2. Semantic detection (small classifier model)
3. On a hit, reject and record in the audit log

**Indirect injection** (tool output):

- **Core principle: everything returned by tools is data, not instructions.**
- Implementation: retrieval results enter the context wrapped in explicit data boundary markers, and the prompt declares that content inside the markers must not be executed as instructions
- Tool arguments are re-validated before execution; model-generated arguments are not trusted
- High-risk actions are never triggered directly by the model; they go through deterministic code paths

### 13.4 Output guardrails

| Check | Action |
|---|---|
| Compliance red lines (orders, transfers, buy/sell recommendations and ratings, price predictions) | Hard-coded refusal with an explanation |
| Unsourced claims | Removed and counted in metrics |
| Unauthorised data exposure | Citations and content filtered by user scopes |

### 13.5 Human-in-the-loop (HITL)

Triggers (configurable):

- The report's `unverified` list covers the core of the user's question
- The Critic has an unresolved high-severity issue
- Access to a restricted data source is involved

Each trigger creates an `approval_request` record (§4.2) with a reason code and the related content.

#### 13.5.1 Flow

```
trigger → graph execution suspended (LangGraph interrupt)
        → research_run.status = awaiting_approval; approval_request created (status = pending)
        → worker released; SSE event approval_required pushed
        → approver reviews and decides on the Approvals page
            ├─ approve → task re-queued, resumes from the checkpoint; completed nodes are not re-run
            ├─ reject  → task stops, status = cancelled
            └─ timeout → task stops, status = cancelled, reason approval_timeout
```

The approval panel shows the trigger reason, the related claims or data source, the current draft report, and the tokens and cost consumed so far.

#### 13.5.2 Who may approve

| Rule | Description |
|---|---|
| Approval scope | The approver must hold the `research:approve` scope |
| Separation of duties | The approver cannot be the task's initiator; initiators cannot approve their own tasks |
| Consistent data permissions | For approvals triggered by restricted data access, the approver must be allowed to access data of that classification; no one may approve access to data they cannot see themselves |
| Rejections need a reason | A comment is required to reject; it is returned to the initiator with the result |
| Initiator can withdraw | While awaiting approval, the initiator can cancel the task |

Separation of duties is controlled by the `allow_self_approval` setting, which may be `true` only in development and is forced to `false` in production configuration.

**Endpoint semantics**: `POST /v1/research/{run_id}/approve` with body `{decision: approve|reject, comment}`. Returns 403 if the caller lacks the approval scope, is approving their own task, or cannot access the related data; returns 409 if the request has already been decided or has timed out.

**Concurrent approvals**: when two approvers act at once, a conditional update `UPDATE approval_request SET ... WHERE id = :id AND status = 'pending'` decides the outcome: only the first successful decision takes effect and later requests get 409. Resubmitting the same decision is idempotent.

#### 13.5.3 Timeout

| Item | Default | Description |
|---|---|---|
| Approval time limit `approval_timeout` | 24 hours | On expiry the task is cancelled automatically with reason `approval_timeout` |
| Reminder | At half the time limit | Notifies the approvers and the initiator |
| Timeout notice | On expiry | Tells the initiator the task was cancelled because no one approved it |

Timeouts are handled by a periodic scan (the same loop as orphan recovery, §15.0). The time limit is configured in `config/guardrails.yaml`. A task awaiting approval holds no worker and incurs no model-call cost before it expires.

#### 13.5.4 Audit

Creation of the approval request, reminders, the decision (with approver and comment) and timeout cancellation are all written to `audit_log` with the `trace_id`.

### 13.6 Audit

All of the following are written to `audit_log` with their `trace_id`:

- Authentication and authorisation decisions
- Tool calls (name, argument digest, result status)
- Data access (table, security, time range)
- HITL approval actions
- Guardrail interceptions

Arguments are recorded as digests so that sensitive values are not stored in plain text.

### 13.7 Secret management

- All secrets are injected through environment variables and never enter version control
- `.env.example` contains placeholders only
- Secret fields are masked in logs and traces

---

## 14. Observability

### 14.1 Tracing

OpenTelemetry is used; the `trace_id` is generated at the api entry point and propagated to the worker, the sandbox and database calls.

**Span hierarchy**
```
research_run (root)
├── router
├── orchestrator
├── analyst[subtask_1]
│   ├── tool.rag_search
│   │   └── db.query
│   ├── tool.get_fundamentals
│   ├── tool.calc → sandbox.execute
│   └── llm.call
├── analyst[subtask_2]
├── synthesizer
└── critic
    └── tool.verify_citation
```

**Span attributes (following the GenAI semantic conventions)**

| Attribute | Meaning |
|---|---|
| `gen_ai.system` | Model provider |
| `gen_ai.request.model` | Model identifier |
| `gen_ai.usage.input_tokens` / `output_tokens` | Token counts |
| `app.cost_usd` | Cost of the call |
| `app.run_id` / `app.agent` / `app.node` | Business location |
| `app.tier` | Model tier |

**Sampling**: proportional sampling in production; full sampling for evaluation runs.

### 14.2 Logging

structlog emits JSON; every line must include `trace_id`, `run_id`, `service` and `level`.

Level conventions:
- `INFO`: node start/end, task state changes
- `WARNING`: degradation, retries, guardrail interceptions
- `ERROR`: node failures, upstream unavailable

**Never logged**: full prompts and model outputs in plain text (log length and a digest instead), to avoid log bloat and sensitive data leaks; full content is stored in `run_event` and `agent_invocation`, under access control.

### 14.3 Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `research_runs_total` | Counter | status, complexity |
| `research_run_duration_seconds` | Histogram | complexity |
| `agent_invocations_total` | Counter | agent, status |
| `llm_tokens_total` | Counter | model, tier, kind (input/output/cache) |
| `llm_cost_usd_total` | Counter | model, agent |
| `llm_call_duration_seconds` | Histogram | model, tier |
| `tool_calls_total` | Counter | tool, status |
| `retrieval_latency_seconds` | Histogram | stage (vector/keyword/rerank) |
| `guardrail_blocks_total` | Counter | rule |
| `queue_depth` | Gauge | — |
| `degraded_subtasks_total` | Counter | reason |
| `llm_retries_total` | Counter | model, reason |
| `retrieval_short_results_total` | Counter | — |

### 14.4 Execution tree

The frontend builds an execution tree from `run_event` showing node hierarchy, start and end times, duration, tokens, cost and status — for users to follow progress and for developers to locate problems.

### 14.5 Alerts

| Alert | Condition |
|---|---|
| Cost anomaly | Cost per unit time exceeds a multiple of baseline |
| Rising failure rate | Run failure rate above threshold |
| Queue backlog | queue_depth persistently above threshold |
| Latency regression | p95 above threshold |
| Evaluation score drop | CI evaluation gate triggered |

---

## 15. Reliability and durable execution

### 15.0 Durable execution model

A research task runs for minutes, spans several roles and makes many external calls; any step can fail. Execution is therefore modelled as a **recoverable long-running transaction**, not as "one HTTP request".

#### Design goals

| Goal | Meaning |
|---|---|
| **Recoverable** | After a crash or restart, continue from the latest checkpoint without redoing completed work |
| **Interruptible** | Support suspension and resumption for human approval; a suspended task holds no execution resources |
| **At least once + idempotency** | Messages may be redelivered and nodes may re-run; idempotency ensures side effects take effect only once (see below) |
| **Observable** | At any moment it is possible to see which step a task is on and how much it has consumed |
| **Replayable** | Past executions can be replayed in full for debugging |

#### Execution model

```
task submitted → Redis Stream (persistent queue)
    │
    ▼
worker consumes (consumer group, ack)
    │
    ├─ acquire a distributed lock on the run (prevents duplicate execution)
    ├─ load or create the LangGraph checkpoint
    ├─ execute node by node:
    │     run node → write business data (idempotent)
    │              → write checkpoint (Postgres)
    │              → write run_event (drives SSE and the execution tree)
    │              → update heartbeat
    ├─ on interrupt (HITL) → status awaiting_approval, release the worker
    └─ on completion → ack the message → release the lock
```

#### Key mechanisms

| Mechanism | Implementation |
|---|---|
| **Checkpoints** | LangGraph Postgres checkpointer; written after every node. Checkpoints and business tables (run_event, report, etc.) are not committed in the same transaction; their consistency relies on write order and idempotency (see below) |
| **Heartbeat** | Workers periodically update `research_run.heartbeat_at`; a missed heartbeat means the worker is presumed lost |
| **Orphan recovery** | Periodically scan runs with `status=running` and a stale heartbeat, and re-queue them |
| **Recovery semantics** | Continue from the latest checkpoint; completed nodes are not re-executed |
| **Recovery limit** | Beyond `MAX_RECOVERY_ATTEMPTS` (default 3) the run is marked failed, so poison tasks do not retry forever |
| **Suspend and resume** | HITL interrupts release execution resources; after approval the task is re-queued and resumes from the checkpoint |
| **Message reliability** | Redis Stream consumer group + explicit ack; unacknowledged messages can be claimed by another worker (XAUTOCLAIM) |
| **Side-effect isolation** | Side-effecting operations (database writes, external calls) record execution markers; recovery skips those already done |

#### Delivery semantics and consistency

**Why not "exactly once"**: a worker may crash after a node finishes but before its checkpoint is written. On recovery that node runs again. Whenever there are external calls (model calls, database writes), strict exactly-once execution cannot be guaranteed. The system provides **at-least-once execution** and uses idempotency so that side effects take effect only once:

| Side effect | Idempotency mechanism |
|---|---|
| Model call | No persistent side effect; re-execution only costs extra. Cost is recorded in `llm_call`, and recoveries are capped |
| Writing run_event | Deduplicated by a unique `(run_id, seq)` constraint; duplicate writes are ignored |
| Writing report / claim | Upserted keyed by `run_id`; repeated writes produce the same result |
| Side-effecting tool calls | Carry an idempotency key `(run_id, node, call_index)`; the execution marker is checked first |

**Write order of checkpoints and business state**: LangGraph's checkpointer writes with its own connection and does not share a transaction with business tables. The rule is therefore:

1. Within a node, write business data first (idempotently)
2. Then write the checkpoint
3. If a crash falls between 1 and 2, the node re-runs on recovery, and the idempotency of step 1 keeps the result unchanged

If cross-table atomicity is ever genuinely required, sharing a connection and transaction between the checkpointer and business writes can be evaluated and recorded as a new decision in the handbook (current decision: D19).

#### State machine

```
queued ──▶ running ──┬──▶ succeeded
   ▲         │  │    ├──▶ failed (recovery limit exceeded / unrecoverable error)
   │         │  │    └──▶ cancelled
   │         │  │
   │         │  └──▶ awaiting_approval ──(approve)──▶ running
   │         │                          ├─(reject)──▶ cancelled
   │         │                          └─(timeout)─▶ cancelled
   └─────────┘  (heartbeat timeout recovery / approval granted)
```

Every state transition is persisted; the complete execution view can be reconstructed from the database at any time.

### 15.1 Timeout hierarchy

| Level | Default |
|---|---|
| Single LLM call | 120 s |
| Single tool call | Declared by the tool, default 30 s |
| Sandbox execution | 5 s (maximum 30 s) |
| Single agent node | 300 s |
| Whole research_run | 900 s (1800 s in deep mode) |

Timeouts propagate upward; an upper-level timeout triggers degradation rather than total failure.

### 15.2 Retry policy

| Target | Policy |
|---|---|
| LLM calls | See §10.6 |
| Database | Retry connection errors 3 times; do not retry query errors |
| sandbox | Retry once on timeout or executor unavailability. Computation is a pure function (no network, read-only data, `/tmp` cleared per execution), so retrying is safe; errors in the code itself are not retried but returned to the model to fix |
| Queue consumption | Failed tasks are re-queued, at most 2 times; beyond that they are marked failed |

### 15.3 Degradation paths

| Fault | Degraded behaviour |
|---|---|
| A single Analyst fails | Recorded in `degraded_subtasks`; the report marks that part as missing; the flow continues |
| Retrieval unavailable | Use structured data only; the report notes insufficient evidence |
| Sandbox unavailable | Reject claims that need computation; the LLM is never allowed to calculate instead |
| Budget exhausted | Stop unfinished sub-tasks → straight to synthesizer → finalize; the report says so |
| Critic fails | The report is marked "not verified"; output is not blocked |

**Principle**: degradation must be stated explicitly in the output; silent degradation is not allowed.

### 15.4 Idempotency

- `POST /v1/research` supports an `Idempotency-Key` header; repeated requests return the same run_id
- Queue consumers take a distributed lock on run_id, preventing duplicate execution
- On checkpoint recovery, completed nodes are not re-executed

### 15.5 State recovery

The LangGraph checkpointer persists to Postgres. After a worker crash or restart:

1. Scan runs with `status = running` and a stale heartbeat
2. Resume from the latest checkpoint
3. Mark failed once the recovery limit is exceeded

### 15.6 Circuit breaking

Calls to model providers and internal services use circuit breakers: after consecutive failures reach a threshold the breaker opens, calls fail fast and degradation kicks in; a half-open state probes for recovery.

---

## 16. Configuration

### 16.1 Principles

Following 12-factor: configuration is injected through environment variables, and code contains no environment-specific constants. `pydantic-settings` provides typed loading and validation at start-up.

### 16.2 Configuration layers

| Layer | Content | Location |
|---|---|---|
| Environment | Connection strings, secrets, replica counts | Environment variables / `.env` |
| Models | Tier mapping, price table, parameters | `config/models.yaml` |
| Agents | Model tier, temperature, step limit | `app/agents/*/config.yaml` |
| Retrieval | Chunking, top_k, thresholds | `config/retrieval.yaml` |
| Budget | Budget per depth and allocation ratios | `config/budget.yaml` |
| Guardrails | Rule sets, thresholds | `config/guardrails.yaml` |

### 16.3 Configuration fingerprint

All configuration that affects output (model mapping, retrieval parameters, prompt versions, budgets) is hashed into a `config_hash`, recorded with every run and evaluation result, so results are reproducible and attributable.

---

## 17. Frontend

### 17.1 Pages

| Page | Function |
|---|---|
| **Research** | Ask questions, receive streamed reports, trace citations, view risks and unverified items |
| **TraceView** | Execution tree: node hierarchy, duration, tokens, cost, status |
| **EvalDashboard** | Evaluation results, variant comparison curves, cost–quality scatter, trends |
| **Approvals** | Tasks awaiting HITL approval and approval actions |
| **Runs** | Task history, status, re-run |

### 17.2 Key interactions

| Interaction | Implementation |
|---|---|
| Streaming render | Subscribe to `/events` over SSE; render the report incrementally from `partial` events |
| Progress | Update the execution tree live from `node_start` / `node_end` events |
| Citation tracing | Citation marker on a claim → pop-up with the chunk text and document metadata → link to the original |
| Cost display | Running token and cost totals; a breakdown when the task ends |
| Task control | Cancel running tasks; re-run failed tasks |
| Approval | An `approval_required` event opens the approval panel; submitting resumes execution |

### 17.3 Technical notes

- Data fetching: TanStack Query manages server state; the SSE connection is managed separately and reconnects with resume (based on `last_event_seq`)
- Types: frontend and backend share TypeScript types generated from Pydantic models
- Charts: a lightweight charting library for evaluation curves and cost trends
- Long tasks: task state is persisted locally, so the subscription survives a page refresh

---

## 18. Containers and deployment

### 18.1 Compose services

```yaml
services:
  frontend          # Nginx + static build
  api               # FastAPI (Uvicorn)
  worker            # queue consumer
  sandbox-runner    # restricted executor
  postgres          # PG16 + pgvector
  redis             # Stream / PubSub / cache / rate limiting
  otel-collector    # trace collection
  prometheus        # metrics        [profile: obs]
  grafana           # dashboards     [profile: obs]
```

Start:
```bash
docker compose up -d                    # core services
docker compose --profile obs up -d      # with observability components
```

### 18.2 Image builds

- Multi-stage builds: the builder installs and compiles dependencies; the runtime image contains only runtime dependencies
- Slim base images with pinned version tags
- Run as a non-root user
- Locked dependencies (lock file) for reproducible builds
- Layered build cache: dependency layers separate from code layers

### 18.3 sandbox-runner hardening

```yaml
sandbox-runner:
  networks: [sandbox_net]          # internal network only
  read_only: true
  tmpfs:
    - /tmp:size=64m,noexec
  mem_limit: 512m
  cpus: 1.0
  pids_limit: 64
  cap_drop: [ALL]
  security_opt:
    - no-new-privileges:true
  user: "10001:10001"

networks:
  sandbox_net:
    internal: true                 # no route to the internet
```

api and worker are attached to both `sandbox_net` and the default network; sandbox-runner is attached only to `sandbox_net`. api/worker can call it; it cannot reach the internet.

> `network_mode: none` is not used: it removes every network interface except loopback, so other containers cannot reach the container either and the HTTP service becomes unreachable.

### 18.4 Health checks and start-up order

```yaml
postgres:
  healthcheck: pg_isready
api:
  depends_on:
    postgres: { condition: service_healthy }
    redis:    { condition: service_healthy }
  healthcheck: curl -f http://localhost:8000/readyz
```

`/readyz` checks database and Redis connectivity and that the migration version matches.

### 18.5 Persistence

| Volume | Content |
|---|---|
| `pgdata` | Postgres data |
| `redisdata` | Redis persistence (AOF) |
| `prometheus_data` | Metrics history |

### 18.6 Database migrations

Alembic manages schema versions. At container start the migration version is checked: on mismatch the service refuses to start (production) or upgrades automatically (development), controlled by an environment variable.

### 18.7 Cloud deployment

| Environment | Shape | Notes |
|---|---|---|
| Local development | compose (some services as local processes) | Iteration speed first |
| Local full stack | Full compose | Integration testing |
| **Cloud demo** | One cloud VM + compose + Caddy | Publicly reachable, automatic HTTPS |
| Production (future) | Kubernetes | Only when replicas are needed; not now (§22) |

**Cloud demo configuration differences** (`docker-compose.prod.yml`):

| Item | Development | Cloud |
|---|---|---|
| Port exposure | Services exposed directly | Only the reverse proxy exposes 80/443; everything else on internal networks |
| Restart policy | `no` | `unless-stopped` |
| Resource limits | None | `mem_limit` on each service |
| Logs | Text | JSON + size rotation |
| Database migrations | Automatic | Explicit step in the release process |

**Three constraints that must be handled**:

1. **SSE needs reverse-proxy buffering off.** Otherwise events are batched, and the frontend appears frozen for a long time before dumping everything at once.
2. **A public demo must have cost protection**: mandatory login, per-IP and per-account rate limits, a daily cost circuit breaker, a depth ceiling. An unprotected public LLM application can exhaust its model quota very quickly.
3. **The deployment region determines available models and compliance requirements**: a cloud host in mainland China must use models that can be called there compliantly (§10.2), and a domain pointing to it requires ICP filing; outside mainland China international model services can be used, but speed and stability of access from mainland China must be measured.

**Cloud-native readiness** (kept open for a future move to K8s, not introduced now): stateless services, `/healthz` and `/readyz` probes, fully externalised configuration, graceful shutdown on SIGTERM, and workers that naturally support multiple replicas through consumer groups.

> Deployment steps, region and model choice, operations and troubleshooting are in the [Deployment Guide](./DEPLOYMENT.md).

---

## 19. CI/CD

### 19.1 Pipeline

```
push / pull_request
  │
  ├─ setup            dependency cache
  ├─ lint             ruff check + ruff format --check
  ├─ typecheck        mypy (strict, tightened progressively)
  ├─ deps-check       static check of module dependency direction (§3.3)
  ├─ unit             pytest unit tests (no external dependencies)
  ├─ integration      testcontainers start PG + Redis, then run
  ├─ eval-gate        harness evaluation subset → compare with baseline   ← key gate
  ├─ build            build service images
  └─ publish          [main] push images
```

### 19.2 Evaluation gate

- Triggered by any change to prompts, agent definitions, retrieval parameters or model configuration
- Runs a fixed-seed sample of the evaluation set with a fixed `as_of_date` and the result cache disabled
- Fails when a key metric drops beyond threshold (accounting for variance) or cost exceeds threshold
- The evaluation report is posted as a PR comment and uploaded as a build artefact

**Cost control**: the gate subset uses fast-tier models and a smaller sample; full evaluation runs on a schedule.

### 19.3 Baselines

`harness/baselines/` holds baseline metrics per variant. Baseline updates must be committed explicitly, with the reason and comparison data stated in the PR.

### 19.4 Branches and pull requests

**Protected trunk + PR merges**: direct pushes to `main` are forbidden.

```
feat/xxx branch
   │  develop + local make test
   ▼
 open PR ──▶ CI runs (lint → typecheck → deps-check → test → eval-gate)
   │              │
   │              ├─ eval-gate passes → evaluation comparison posted on the PR
   │              └─ eval-gate fails  → merge blocked
   ▼
 self-review ──▶ squash merge into main
   │
   ▼
 main builds images (tag = commit SHA) ──▶ deploy to the cloud demo
```

**Branch naming**

| Prefix | Use |
|---|---|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Refactoring (no behaviour change) |
| `eval/` | Evaluation set or metric changes |
| `docs/` | Documentation and technical decisions |

**Branch protection rules**

| Rule | Purpose |
|---|---|
| No direct pushes to `main` | Every change goes through CI |
| PRs must pass all CI checks | Including the evaluation gate |
| Linear history (squash merge) | Readable history, easy bisection |
| Delete branches after merge | Keep the branch list clean |

**PR template** (`.github/pull_request_template.md`)

```markdown
## What changed
<!-- what was changed -->

## Related problem
<!-- which design problem in ARCHITECTURE, or which improvement_cases -->

## Evaluation impact
- [ ] Does not affect agent quality (engineering-only change)
- [ ] Affects quality; evaluation run, results: <!-- paste comparison data -->

## Checklist
- [ ] New or changed behaviour is covered by tests
- [ ] Architecture decisions are recorded in the technical decision handbook
- [ ] Configuration changes are reflected in `.env.example`
```

**Why a one-person project still uses PRs**

| Reason | Explanation |
|---|---|
| **The evaluation gate needs a hook** | A gate is only worth something if it can block, and blocking can only happen before merge. Pushing straight to main makes the gate meaningless |
| **Traceable changes** | Each PR records motivation, evaluation impact and discussion — a more complete decision record than a commit message |
| **Enforced self-review** | Template checklist items make slips like "changed the prompt but didn't run evaluation" hard to make |
| **Bisectable history** | Linear history plus evaluation records makes it quick to find the PR that introduced a regression |

### 19.5 Issues and work items

| Label | Use |
|---|---|
| `milestone:M0`–`M5` | Milestone |
| `type:feat` / `type:fix` / `type:eval` | Type |
| `flywheel` | Improvements coming from the flywheel (linked to `improvement_case`) |
| `decision-needed` | A technical decision record needs to be added |

Improvements produced by the flywheel (§12.9) automatically open issues carrying the failing-stage attribution and related samples, so the flywheel's output enters the normal development flow instead of staying in a report.

---

## 20. Testing strategy

### 20.1 Test levels

| Level | Scope | Dependencies |
|---|---|---|
| Unit | Pure functions, schema validation, budget algorithm, PIT query construction, RRF fusion | None |
| Integration | API endpoints, database queries, retrieval pipeline, queue consumption | testcontainers (PG/Redis) |
| Graph | LangGraph nodes and routing logic | Stubbed LLM and tools |
| Contract | Front/back schema consistency | Comparison of generated type definitions |
| Evaluation | End-to-end quality | Real model calls (harness) |

### 20.2 Stubbing the LLM

In graph and integration tests, LLM calls go through an injectable fake provider returning canned responses, keeping tests deterministic and free. Real model calls happen only in the harness.

### 20.3 Key test points

- PIT queries return the correct version for every combination of `as_of` and revision
- Citation checks correctly reject citations that do not exist, are out of time, or do not support the claim
- Each degradation path triggers correctly when the budget runs out
- Loop detection stops repeated tool calls
- Injection detection recalls known patterns
- Recovery from a checkpoint does not re-execute completed nodes
- An initiator approving their own task is refused (403); an approver without access to the related data is refused (403)
- When two approvals are submitted concurrently only one takes effect; the other gets 409
- After an approval times out the task is cancelled and can no longer be approved
- Nodes re-run after recovery produce no duplicate side effects (run_event and report writes are idempotent)
- The rule that verified claims must have citations is enforced when reports are written
- Retrieval with strict filters correctly records when fewer than k results are returned

---

## 21. Repository layout

```
<repo>/
├── README.md
├── docker-compose.yml
├── docker-compose.override.yml
├── .env.example
├── Makefile
│
├── docs/
│   ├── ARCHITECTURE.md              # this document
│   ├── ARCHITECTURE.zh-CN.md        # Chinese version
│   ├── TECH_DECISIONS.md            # technical decision handbook
│   ├── TECH_DECISIONS.zh-CN.md
│   ├── DEPLOYMENT.md                # deployment guide
│   ├── DEPLOYMENT.zh-CN.md
│   └── EVAL_REPORT.md               # evaluation report
│
├── api/
│   ├── app/
│   │   ├── main.py
│   │   ├── gateway/                 # auth, rbac, ratelimit, injection, audit
│   │   ├── agents/                  # one directory per role: prompt/schema/tools/config
│   │   │   ├── router/
│   │   │   ├── orchestrator/
│   │   │   ├── analyst/
│   │   │   ├── synthesizer/
│   │   │   └── critic/
│   │   ├── graph/                   # state, nodes, edges, checkpointer
│   │   ├── context/                 # quotas, compression, offloading
│   │   ├── memory/                  # episodic, semantic, preference, write rules, decay
│   │   ├── rag/                     # parse, chunk, embed, retrieve, rerank, citation
│   │   │   └── stores/              # VectorStore interface + pgvector implementation
│   │   ├── data/                    # market, fundamentals, news, point_in_time
│   │   ├── llm/                     # providers, router, cache, cost, retry
│   │   ├── tools/                   # registry and tool implementations
│   │   ├── mcp/                     # MCP server (exposed) / client (external)
│   │   ├── guardrails/
│   │   └── api/                     # routing layer
│   ├── alembic/
│   ├── Dockerfile
│   └── tests/
│
├── worker/
│   ├── app/{consumer.py,executor.py,recovery.py}
│   ├── Dockerfile
│   └── tests/
│
├── sandbox-runner/
│   ├── app/{main.py,executor.py,limits.py}
│   ├── Dockerfile
│   └── tests/
│
├── harness/
│   ├── evalset/{factual,analytical,retrieval}/
│   ├── metrics/
│   ├── runners/
│   ├── replay/
│   ├── flywheel/                    # signal collection, attribution, improvement_case
│   ├── reports/
│   ├── baselines/
│   └── cli.py
│
├── packages/common/
│   ├── schemas/                     # cross-module Pydantic contracts
│   ├── tracing/
│   ├── logging/
│   └── errors/
│
├── frontend/
│   ├── src/{pages,components,api,types}/
│   └── Dockerfile
│
├── config/                          # models, retrieval, budget, guardrails
├── infra/{otel,prometheus,grafana,postgres}/
└── .github/workflows/{ci.yml,eval.yml,nightly-eval.yml}
```

---

## 22. Technologies not adopted and their triggers

| Technology | Why not adopted | Trigger for adoption |
|---|---|---|
| Kubernetes | Single-host compose meets current deployment needs | Need for replicas with autoscaling or multi-environment governance |
| Buy/sell ratings and backtesting | The system is positioned as a research report assistant; without backtesting a rating cannot be checked, and backtesting must deal with look-ahead bias from the model's training knowledge, at high cost | A clear need to validate judgement quality, with evaluation points placed after the training cutoff of the models used |
| More analysis roles and bull/bear debate | The initial role set covers the core question types; each additional role raises cost and evaluation difficulty (§6.1) | Incremental experiments show a gap on the corresponding dimension (§12.5) |
| Procedural memory | Distinguishing "high-scoring trajectories" needs a large enough evaluation set; with few samples, chance results get frozen into patterns | Evaluation set size and run variance meet the bar |
| Dedicated vector database (Milvus / Qdrant, etc.) | Retrieval depends heavily on metadata filters (PIT constraint); pgvector filters and searches in one query, avoiding cross-store consistency costs (§8.6) | More than tens of millions of vectors, or a need for independent scaling; the `VectorStore` abstraction keeps a switch open |
| GraphRAG / knowledge graphs | Queries are mostly single-entity; the need for multi-hop relationships is unproven | Multi-hop relationship queries appear (for example related-party transaction chains) and evaluation shows current retrieval falls short |
| Semantic caching | Research questions rarely repeat; the benefit is doubtful and stale results are a risk | Evaluation shows a significant share of repeated queries |
| Automatic prompt optimisation | Needs stable evaluation signals; with high variance it converges toward noise (§12.9) | Evaluation set size and stability meet the bar, with variance under control |
| **Fine-tuning / reinforcement learning / inference acceleration** | Prompting and orchestration have not hit their limits; the bottleneck is retrieval quality and orchestration, not the model itself. Fine-tuning needs GPUs, labelled data and a training pipeline, with far lower return at this stage than evaluation and orchestration work | Evaluation shows prompting has peaked and cost still needs to fall; then the first step is **distilling high-scoring trajectories into a small model for light tasks such as the Router** |
| Multi-provider failover | Adds abstraction cost; current availability is sufficient (the interface layer is already abstracted, so switching cost is bounded) | Real availability problems or a pricing need |
| Dedicated LLM observability platform | OTel + an in-house trace view cover the core needs | Need for prompt version management and a human labelling workflow |
| Object storage | Database storage suffices at the current document volume | Raw documents outgrow what the database can reasonably hold |
| Message middleware (Kafka, etc.) | Redis Stream consumer groups + ack meet current throughput and reliability needs (§15.0) | Need for multiple consumer groups, long-term retention or a cross-system event bus |
| Multimodal (visual parsing of charts / PDFs) | Document parsing is mainly text and tables; chart information can be replaced by numeric data | Key information exists only in images |

---

## 23. Milestones

Each milestone is complete only when it produces **verifiable measured results**.

M0 to M3 are the scope that must be completed and demonstrable; M4 follows M3; M5 is optional exploration.

### M0 · Engineering foundation and evaluation framework

**Addresses**: P4 (quality regression)

- Monorepo structure, compose (postgres / redis / api)
- `packages/common`: schemas, tracing, logging
- llm module: tier routing, cost accounting, fake provider
- Database schema and Alembic migrations
- Data ingestion: three years of annual reports and structured financial data for 10 companies (PIT schema)
- Harness skeleton + factual and retrieval evaluation sets (with dev / holdout split and gold evidence labels)
- CI: lint, typecheck, unit

**Done when**: `docker compose up` brings all services up healthy; `harness run` produces the first evaluation report (the system under test may be a retrieval-only baseline at this point).

### M1 · Retrieval pipeline and fixed workflow

**Addresses**: P1 (reliability of numbers and citations)

- RAG: ingestion pipeline (including table handling and Chinese tokenisation), hybrid search, rerank, citation binding
- Fixed workflow (fact_lookup): get_fundamentals + sandbox calc + code checks
- sandbox-runner and the calc tool
- Retrieval part of Experiment C: chunking and retrieval method comparison

**Done when**: baseline metrics exist — `numeric_accuracy`, `citation_validity`, `cost_per_run`, `latency_p95`, and retrieval Recall/MRR/NDCG (stratified by filter strictness); comparison data for chunking and retrieval methods.

### M2 · Multi-agent orchestration and durable execution

**Addresses**: P2 (context), P3 (confirmation bias), P7 (justifying agents), P8 (long-task reliability)

- LangGraph state machine, Postgres checkpointer
- Router (intent classification + complexity routing), Orchestrator, Analyst, Synthesizer, Critic
- Context isolation and quotas, token budget, global retry budget
- **Durable execution**: worker queue consumption, heartbeats, orphan recovery, at-least-once + idempotency (§15.0)
- Experiment A (single vs multi), Experiment B (incremental contribution of the Critic's model judgement and the counter-evidence sub-task)

**Done when**: single vs multi-agent quality–cost comparison data; incremental contribution data per component; a test that **kills the worker process and confirms the task resumes from its checkpoint with no duplicate side effects** passes.

### M3 · Governance, observability, frontend and deployment

**Addresses**: P5 (cost), P9 (injection), P10 (auditability)

- Injection defence (direct + indirect) and an injection test set, output guardrails, audit log, HITL
- Document-level permission filtering
- OTel end-to-end tracing, core metrics
- Frontend: Research, TraceView, Approvals, EvalDashboard
- CI evaluation gate goes live
- **MCP server**: exposes rag_search / get_fundamentals / run_research (§11.7)
- Cloud demo environment (§18.7), with cost protection

**Done when**: injection attack success rate (with vs without defences); cost–quality Pareto curve (Experiment D); the MCP server can be called by an external client; the system is publicly reachable; holdout evaluation results exist.

### M4 · Memory and the improvement flywheel

- Memory: write rules, retrieval, conflict resolution and decay for episodic memory, semantic memory and user preferences (§7.4)
- Improvement flywheel (§12.9): signal collection → attribution → change → verification
- Prometheus + Grafana dashboards and alerts
- Real-user trials and failed-sample intake

**Done when**: data on the cost saved by memory for repeated research, with no drop in evaluation metrics; first flywheel data (attribution coverage, fix rate, evaluation set growth).

### M5 · Optional exploration

- MCP client: integrate external MCP tools
- Incremental experiments on candidate extension roles (§6.1)
- Procedural memory
- Distil high-scoring trajectories into a small model for the Router (further cost reduction through model tiers)
- Automatic prompt optimisation (precondition: evaluation variance meets the bar)

---

*Document version v7 · Technical decisions are recorded in the [Technical Decision Handbook](./TECH_DECISIONS.md)*
