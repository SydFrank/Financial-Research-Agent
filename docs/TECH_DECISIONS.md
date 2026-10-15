# A-Share Research Agent — Technical Decision Handbook

English | [简体中文](TECH_DECISIONS.zh-CN.md)

This handbook records every key technical decision in the system: the problem, the options considered, the choice, the reasoning, the cost, the conditions under which the decision should change, and how it is verified.

Division of labour with the [Architecture](ARCHITECTURE.md) document: the architecture describes **what** the system is; this handbook explains **why** it is that way.

## Conventions

- **Status**: `Adopted` means the design is settled; `Pending measurement` means the current choice is a hypothesis to be confirmed by evaluation data; `Superseded` means replaced by a later decision (the original text is kept and the successor is named).
- **Comparison data** records only results from actual runs, with the evaluation set version, sample count and number of runs. Anything not yet measured says "pending measurement" and gives the experiment plan; no estimates are filled in.
- Adopted decisions are not rewritten. When a decision changes, a new entry is added and the old one is marked superseded.

## Index

| ID | Decision | Method | Status |
|---|---|---|---|
| [D01](#d01-positioning-research-reports-without-ratings-or-backtesting) | Positioning: research reports without ratings or backtesting | Analysis | Adopted |
| [D02](#d02-workflows-first-and-the-initial-role-set) | Workflows first and the initial role set | Analysis + Experiment B | Adopted |
| [D03](#d03-orchestration-mode-single-agent-vs-multi-agent) | Orchestration mode: single agent vs multi-agent | Experiment A | Pending measurement |
| [D04](#d04-orchestration-framework-langgraph) | Orchestration framework: LangGraph | Analysis | Adopted |
| [D05](#d05-service-boundaries-modular-monolith--worker--sandbox-runner) | Service boundaries: modular monolith + worker + sandbox-runner | Analysis | Adopted |
| [D06](#d06-storage-postgresql--pgvector) | Storage: PostgreSQL + pgvector | Analysis | Adopted |
| [D07](#d07-filtered-vector-search) | Filtered vector search | Retrieval evaluation | Pending measurement |
| [D08](#d08-keyword-search-and-chinese-tokenisation) | Keyword search and Chinese tokenisation | Retrieval evaluation | Pending measurement |
| [D09](#d09-chunking-strategy) | Chunking strategy | Retrieval evaluation | Pending measurement |
| [D10](#d10-retrieval-pipeline-hybrid-search--rrf--reranking) | Retrieval pipeline: hybrid search + RRF + reranking | Experiment C | Pending measurement |
| [D11](#d11-embedding-and-reranking-models) | Embedding and reranking models | Retrieval evaluation | Pending measurement |
| [D12](#d12-point-in-time-correctness-bitemporal-data-model) | Point-in-time correctness: bitemporal data model | Analysis | Adopted |
| [D13](#d13-source-of-numbers-structured-data--sandboxed-computation) | Source of numbers: structured data + sandboxed computation | Analysis + evaluation | Adopted |
| [D14](#d14-sandbox-isolation) | Sandbox isolation | Analysis | Adopted |
| [D15](#d15-citation-binding-and-verification) | Citation binding and verification | Experiment B | Adopted |
| [D16](#d16-context-management) | Context management | Experiment C | Pending measurement |
| [D17](#d17-memory-scope-and-write-policy) | Memory scope and write policy | Analysis + evaluation | Adopted |
| [D18](#d18-task-queue-redis-streams) | Task queue: Redis Streams | Analysis | Adopted |
| [D19](#d19-delivery-semantics-at-least-once--idempotency) | Delivery semantics: at-least-once + idempotency | Analysis + fault injection | Adopted |
| [D20](#d20-model-access-tier-abstraction-and-provider-neutrality) | Model access: tier abstraction and provider neutrality | Experiment D | Adopted |
| [D21](#d21-evaluation-method) | Evaluation method | Analysis | Adopted |
| [D22](#d22-ci-evaluation-gate) | CI evaluation gate | Analysis | Adopted |
| [D23](#d23-prompt-injection-defence-in-depth) | Prompt injection: defence in depth | Injection test set | Adopted |
| [D24](#d24-data-access-control-filter-before-retrieval) | Data access control: filter before retrieval | Analysis | Adopted |
| [D25](#d25-observability-opentelemetry--in-house-execution-tree) | Observability: OpenTelemetry + in-house execution tree | Analysis | Adopted |
| [D26](#d26-frontend-react-single-page-application) | Frontend: React single-page application | Analysis | Adopted |
| [D27](#d27-deployment-single-host-compose--reverse-proxy) | Deployment: single-host compose + reverse proxy | Analysis | Adopted |

---

## D01 Positioning: research reports without ratings or backtesting

**Status** Adopted

**Problem**
Should the system output only a sourced research report, or also a bullish / neutral / bearish rating?

**Options**

| Option | Pros | Cons |
|---|---|---|
| Report + rating + backtest validation | Judgements have an objective right or wrong; negative samples arrive automatically | Backtesting must handle look-ahead bias, and the model's training data already contains information from after any historical as-of date, so evaluation points must lie after the model's training cutoff and samples accrue slowly; hit rates need hundreds of samples to mean anything; requires quantitative finance expertise |
| Report + rating, no backtest | Output looks more "complete" | Ratings cannot be checked, violating the principle that every technique must be verifiable |
| **Sourced report only** | Quality is measurable with factual evaluation and citation checks; scope stays manageable | Provides no investment judgement |

**Decision** Output sourced research reports only; no ratings, no backtesting. The guardrail layer refuses requests for buy/sell recommendations and price predictions.

**Reasoning**
- Without backtesting, a rating cannot be verified; it is better not to output something that cannot be checked.
- Report reliability (accurate numbers, real citations, no fabrication) is itself the hardest and most valuable part of the financial use case.

**Cost** Loses posterior outcomes as an automatic source of negative samples; the improvement flywheel draws only on Critic interceptions, low evaluation scores and user feedback.

**Change when** There is a clear need to validate judgement quality, and every evaluation point can be placed after the training cutoff of the models in use.

---

## D02 Workflows first and the initial role set

**Status** Adopted

**Problem**
How many agents the system needs, and which steps the model should decide autonomously.

**Options**

| Option | Pros | Cons |
|---|---|---|
| One specialist agent per analytical dimension (fundamental, technical, sentiment, macro, bull/bear debate, …) | Intuitive division of labour; demos well | Every role adds cost and evaluation burden; most dimensions lack a data source or are out of scope; contribution of each role is hard to show |
| One agent holding every tool | Simplest to build | Context bloats on complex questions; no parallelism |
| **Workflows by default, agents only where needed** | Cost and behaviour are predictable and easy to evaluate | Flows must be designed up front; less flexible |

**Decision** Five initial roles: Router, Orchestrator, Analyst, Synthesizer, Critic. Only the Analyst is an agent (it chooses tools autonomously in a loop); the others are model calls at fixed positions in the graph. The Analyst is one definition instantiated in parallel, split by "security × research dimension". Simple lookup questions take a fixed workflow that bypasses the Orchestrator.

**Reasoning**
- The more autonomy, the higher the cost, latency and failure surface, and the harder the evaluation. Only steps whose path cannot be known in advance (which data a sub-question needs, and how many lookups) are left to the model.
- Research dimensions are distinguished by the sub-task description; there is no need to maintain a separate prompt, tool set and evaluation for each.

**Cost** Depth on any single dimension is bounded by how general the one Analyst definition is.

**Change when** Incremental experiments (Experiment B) show a clear gap on a dimension under the current design, and a data source for that dimension exists.

**Verification** Experiment B: add candidate roles one at a time; keep a role only if metrics improve by more than the standard deviation across repeated runs.

---

## D03 Orchestration mode: single agent vs multi-agent

**Status** Pending measurement

**Problem**
Should complex questions (multi-dimensional research, multi-security comparison) be handled by one agent or split into parallel sub-tasks?

**Options**

| Option | Pros | Cons |
|---|---|---|
| Single agent loop | Simple, fewer tokens, no aggregation loss | Material exceeds the context budget; serial execution is slow |
| **Orchestrator + parallel Analysts** | Isolated context per sub-task; parallelism cuts latency | Token use multiplies; aggregation can lose information |

**Decision (hypothesis)** Complex questions use orchestrator + parallel Analysts; simple questions take the fixed workflow.

**Reasoning** The material for one research task (several periods of filings, several securities) far exceeds one context window; sub-task isolation is the main lever for controlling context.

**Cost** Higher cost; the Synthesizer and Critic must handle aggregation quality.

**Change when** Experiment A shows the multi-agent quality gain is within the standard deviation, or the cost increase is out of proportion to the gain.

**Verification** Experiment A: same evaluation set, same retrieval parameters, result cache off, each item run three times; compare quality metrics, tokens, cost and latency.

**Comparison data** Pending measurement.

---

## D04 Orchestration framework: LangGraph

**Status** Adopted

**Problem**
Which framework implements the agent flow.

**Options**

| Option | Pros | Cons |
|---|---|---|
| In-house loop and state machine | Full control, few dependencies | Checkpointing, interrupt/resume and parallel branches must all be built |
| **LangGraph** | Explicit graph and state; built-in Postgres checkpointing, interrupts (for human approval) and resume; model-agnostic | Adds framework abstraction and version-churn risk; its checkpointer uses its own connection |
| Claude Agent SDK | Complete agent loop, tools and sub-agents | Claude models only, so unusable for a mainland China deployment; oriented to autonomous agents rather than explicit flow control |
| PydanticAI | Type-safe, model-agnostic | Durable execution and human approval need more in-house work |

**Decision** Implement the orchestration graph in LangGraph; model calls do not go through the framework but through the system's own llm module.

**Reasoning**
- The system is mostly explicit workflow (D02), which matches LangGraph's graph + state + conditional edges.
- Checkpoints, interrupts and resume are exactly what durable execution (D19) and human approval need.
- Routing model calls through the system's own llm module keeps tier mapping, cost accounting and the retry budget independent of the framework and reduces lock-in.

**Cost** Framework upgrades may break things; checkpoints and business tables are not in the same transaction (see D19).

**Change when** The framework's checkpoint or interrupt mechanisms cannot meet the required recovery semantics, or upgrade costs stay persistently high.

---

## D05 Service boundaries: modular monolith + worker + sandbox-runner

**Status** Adopted

**Problem**
How many independently deployed services the system is split into.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Single-process monolith | Simplest deployment | Minute-long tasks block request handling; generated code shares a process with the main service, so there is no security boundary |
| Microservice per module (retrieval, data, models) | Independent scaling | Network calls, deployment and consistency costs; heavy for one maintainer |
| **Modular monolith + worker + sandbox-runner** | Splits only where there is a clear reason | Module boundaries rely on convention and static checks |

**Decision** Four deployment units: api (modular monolith), worker, sandbox-runner, frontend. A service is split out only if it meets at least one criterion: security boundary, different resource profile and lifecycle, independent release cadence, independent scaling need.

**Reasoning**
- The sandbox-runner executes model-generated code and needs container-level isolation.
- The worker runs minute-long tasks, with a different process model and scaling dimension from short requests.
- Retrieval, data and model modules meet none of the criteria; splitting them would only add network calls and operational cost.

**Cost** Dependency direction between modules has to be enforced by a CI check.

**Change when** A module develops an independent scaling or release need.

---

## D06 Storage: PostgreSQL + pgvector

**Status** Adopted

**Problem**
Where business data, vectors, checkpoints and evaluation records live.

**Options**

| Option | Pros | Cons |
|---|---|---|
| **PostgreSQL + pgvector in one database** | Metadata filters and vector search run in one query; one set of transactions, backups and operations | Weaker than dedicated stores at very large scale; filter semantics need extra handling (D07) |
| PostgreSQL + a dedicated vector database (Milvus, Qdrant, …) | Strong at scale, more index types | Document metadata must be synchronised in two places, risking inconsistency; one more stateful service |
| Embedded indexes such as FAISS | High single-node performance | No persistence or filtering; must be wrapped by hand |

**Decision** Use PostgreSQL + pgvector, with retrieval coded against a `VectorStore` interface.

**Reasoning**
- Retrieval depends heavily on metadata filters (security, point in time, document type, permissions); filters stay consistent with business data by construction.
- The vector volume (dozens of companies, several years of reports) is well within pgvector's range.

**Cost** Approximate search with strict filters needs dedicated handling (D07).

**Change when** Vector volume reaches tens of millions, or search latency becomes a bottleneck that index parameters cannot fix. The `VectorStore` interface confines a switch to one implementation class.

---

## D07 Filtered vector search

**Status** Pending measurement

**Problem**
On approximate indexes such as HNSW, pgvector applies filters after the index scan: it fetches candidates according to `ef_search`, then applies the WHERE clause. The stricter the filter (a single security, before a given date, a specific document type), the fewer candidates survive, and fewer than k results may come back.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Raise `ef_search` | Simple configuration | Slows every query and still guarantees nothing |
| Iterative index scans (pgvector ≥ 0.8, `hnsw.iterative_scan`) | Keeps scanning when candidates run short | Worst-case latency rises; needs a scan cap |
| Partition by security, or partial indexes | The index covers only the target range; stable recall | Partition and index counts grow with the number of securities |
| Exact search when the candidate set is small | Exact results | Unacceptable latency on large candidate sets |

**Decision (hypothesis)** Enable iterative index scans by default; use exact search when filtering to a single security whose chunk count is below a threshold; record the number of results for every search and count shortfalls below k as a metric.

**Verification** Stratify retrieval evaluation by filter strictness and compare Recall@k and latency across the options above.

**Comparison data** Pending measurement.

---

## D08 Keyword search and Chinese tokenisation

**Status** Pending measurement

**Problem**
Keyword search handles exact matches on line-item names, ticker codes and proper nouns. Two facts rule out PostgreSQL's defaults: the default parser splits on spaces and punctuation, so a whole Chinese sentence becomes one token; and the built-in `ts_rank` is frequency-based, not BM25, with no term-frequency saturation or document-length normalisation.

**Options**

| Option | Pros | Cons |
|---|---|---|
| `ts_rank` + a Chinese tokenizer extension (zhparser or pg_jieba) | In-database, few components | Ranking weaker than BM25; needs a custom database image |
| A PostgreSQL extension with BM25 | In-database and BM25 | Chinese tokenisation support, version compatibility and deployment cost must be assessed |
| Application-level BM25 (jieba + inverted index) | Transparent and easy to debug | Index and incremental updates must be maintained by hand |

**Decision (hypothesis)** Establish a baseline with `ts_rank` + a Chinese tokenizer extension, then compare against a BM25 option.

**Reasoning** Hybrid search fuses results with RRF, which uses only ranks, not raw scores, so the scoring algorithm affects only the ordering within the keyword branch. Build the baseline with the fewest components, then let data decide whether more are worth adding.

**Verification** In retrieval evaluation, measure the keyword branch's Recall@k on its own, and its effect on the final hybrid result.

**Comparison data** Pending measurement.

---

## D09 Chunking strategy

**Status** Pending measurement

**Problem**
Annual reports are 200–300 page PDFs whose key data sits in tables that span pages and merge cells. Chunking sets the granularity of retrieval and how much context each piece retains.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Fixed length + overlap | Simplest | Cuts through tables and paragraphs |
| **Split by section structure, keep tables whole** | Semantically complete; tables stay readable | Uneven chunk sizes; depends on layout parsing quality |
| Parent–child (search small chunks, return the enclosing large chunk) | Precise retrieval with context | More complex implementation and storage |

**Decision (hypothesis)** Split by section structure, targeting about 512 tokens with 64 tokens of overlap; never split a table across chunks, and split long tables by row with the header repeated; prefix each chunk with "document title + section + reporting period" before embedding.

**Reasoning** A chunk stripped of context cannot tell companies or years apart, and "found a similar passage from the wrong year" is the dominant retrieval failure in this domain.

**Verification** Build an index per strategy and compare Recall@5 on the factual and retrieval sets; spot-check table cell extraction accuracy.

**Comparison data** Pending measurement.

---

## D10 Retrieval pipeline: hybrid search + RRF + reranking

**Status** Pending measurement

**Problem**
How to find, among all chunks, the passages that actually support an answer.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Dense vector search only | Understands meaning and paraphrase | Insensitive to exact numbers, line items and codes |
| Keyword search only | Strong exact matching | No notion of paraphrase |
| Hybrid + RRF | Complementary; RRF uses ranks only, so no weights to tune | Two retrieval paths add latency |
| **Hybrid + RRF + reranking** | Cross-encoder reranking gives the best precision | Adds one model inference of latency and cost |

**Decision (hypothesis)** Metadata filters (including the PIT constraint) → 50 candidates each from vector and keyword search → RRF fusion (k = 60) → rerank the top 30 → return the top 8.

**Reasoning** Research questions mix semantic phrasing ("why did gross margin fall") with exact entities ("R&D expenses", "300750"); each retrieval method alone has blind spots.

**Verification** Experiment C: vector only, hybrid, hybrid + rerank; compare Recall@5, NDCG@10 and P95 latency. All parameters are part of `config_hash`.

**Comparison data** Pending measurement.

---

## D11 Embedding and reranking models

**Status** Pending measurement

**Problem**
Which models produce embeddings and perform reranking.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Self-hosted open multilingual embedding model (for example bge-m3) | No per-call fees; data stays local; strong on Chinese | Needs compute; deployment and operations cost |
| Domestic cloud embedding service (for example Qwen embeddings) | No compute needed; available in mainland China | Usage-based billing; data leaves the host |
| International embedding service | Consistent quality | Unavailable for a mainland deployment |

Reranking has the same choice: a self-hosted open cross-encoder (for example the bge-reranker family) or a cloud reranking service.

**Decision (hypothesis)** Both embedding and reranking sit behind a common interface; candidates are compared on the retrieval evaluation set before choosing. Vector dimension follows the chosen model (the schema currently assumes 1024).

**Reasoning** The embedding model sets the ceiling on recall, and its quality on Chinese financial text can only be judged by measurement.

**Cost** Changing the embedding model requires re-embedding everything.

**Verification** Hold chunking and the retrieval pipeline fixed, swap only the embedding model, and compare Recall@k and cost per embedding.

**Comparison data** Pending measurement.

---

## D12 Point-in-time correctness: bitemporal data model

**Status** Adopted

**Problem**
Financial statements are published with a lag and may later be revised. Without separating "the period the data describes" from "when the data became public", revised figures get treated as what was known at the time, or unpublished reports get treated as known.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Store only the latest value | Simple | Cannot answer "what was known as of a given date" |
| **Bitemporal: event time + knowledge time, with revisions kept** | Queries at any point in time are reproducible | More complex schema and queries |

**Decision** Financial facts record `period_end` (event time) and `known_at` (knowledge time) and keep every revision of a period; every data query must pass `as_of`, which has no default; `as_of` is injected by the framework, never filled in by the model; the retrieval layer always appends `published_at <= as_of_date`; delisted securities stay in the database.

**Reasoning**
- A research report must state the information cut-off it is based on, or its conclusions cannot be re-checked.
- Injecting the constraint in the framework and enforcing it in the data layer means it does not depend on any caller, including the model, passing parameters correctly.

**Known boundary** PIT constrains the data given to the model, not what the model learned during training. See D13 and D15: facts and numbers may only come from this run's tool results and are checked by code.

---

## D13 Source of numbers: structured data + sandboxed computation

**Status** Adopted

**Problem**
Models fabricate numbers and miscalculate them. One wrong figure is enough to make a financial report untrustworthy.

**Options**

| Option | Pros | Cons |
|---|---|---|
| The model reads numbers from retrieved text and calculates itself | Simple | Wrong periods, wrong units, errors in multi-digit arithmetic |
| A calculator tool | Fixes arithmetic | Does not fix lookup; limited expressiveness for complex calculations |
| **Structured data lookup + code execution in a sandbox** | Every number is traceable and reproducible | Needs a structured data source and sandbox infrastructure |

**Decision** Standard financial data comes from structured tables via PIT queries, never "read" from text; all calculation runs as code in the sandbox; the Critic checks by code that every number in the report appears in this run's tool results.

**Reasoning** Remove every step where the model could err from the numeric path, leaving the model only the decisions of what to fetch and what to compute.

**Cost** Metrics not covered by structured data fall back to text retrieval; those figures are less reliable and the report labels their source type.

**Verification** On the factual set, compare `numeric_accuracy` for "model reads and calculates" against this approach.

---

## D14 Sandbox isolation

**Status** Adopted

**Problem**
Model-generated code may be wrong, and injected content may induce it to do something malicious.

**Options**

| Option | Pros | Cons |
|---|---|---|
| `exec` in the main process + a module allowlist | Simplest | Python-level import restrictions can be bypassed; not a security boundary |
| Long-running executor service running every request in one process | Low latency | One execution can affect the next, or even tamper with the executor |
| **Long-running executor + a fresh subprocess per execution + container hardening** | Executions cannot affect each other; container-level resource and network limits | Process creation overhead per execution |
| A fresh container per execution, or a user-space kernel such as gVisor | Strongest isolation | High start-up latency; more complex operations |

**Decision** The sandbox-runner is a long-running service that accepts requests and runs each execution in a newly created subprocess, destroyed afterwards. The container has a read-only root filesystem, a capped `/tmp` cleared per execution, 512 MB memory, one CPU, a 64-process limit, a non-root user and `cap_drop: ALL`. It is attached only to an `internal: true` Docker network: api and worker can reach it; it cannot reach the internet.

**Reasoning**
- The security boundary is container and process isolation, on the assumption that generated code can run arbitrary Python.
- `network_mode: none` is not used: it removes every network interface except loopback, so other containers cannot reach the service either and the HTTP endpoint becomes unreachable.

**Change when** Code of lower trust must be run, or process-level escape becomes a concern: upgrade to one container per execution or a user-space kernel sandbox, with the interface unchanged.

---

## D15 Citation binding and verification

**Status** Adopted

**Problem**
How to ensure every conclusion in a report is traceable, and that the cited text actually supports it.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Only ask in the prompt not to fabricate | No extra cost | Neither guaranteed nor measurable |
| Self-check by the same model | Simple | Models tend to approve their own output |
| **Bind conclusions to source_id + code checks + independent model judgement** | Every conclusion is traceable; failures can be classified and counted | Extra cost and latency for one verification call |

**Decision** Every piece of evidence from an Analyst must carry `source_ids`; items without a source are dropped before aggregation; the Synthesizer may cite only `source_ids` already present in the findings; the Critic checks, in order, citation existence and point in time (code), numeric consistency (code), accounting identities (code), citation support (model judgement), counter-evidence and coverage. Failing conclusions are removed, marked unverified, or sent back for follow-up research.

**Reasoning** Everything code can decide is decided by code; only the one semantic question — does the passage support the claim — goes to a model.

**Verification** Experiment B: turn the Critic's model judgement off and on and compare `citation_validity`, `unsourced_claim_rate` and cost.

---

## D16 Context management

**Status** Pending measurement

**Problem**
The material for one research task far exceeds the context window; longer contexts cost more, and models make poorer use of content in the middle.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Keep everything | Nothing lost | Exceeds budget; expensive |
| Rolling summarisation | Bounded length | Summaries lose numbers and sources |
| **Sub-task isolation + structured hand-back + just-in-time retrieval + offloading + quotas** | Each call sees only what it needs | More complex to design and build |

**Decision (hypothesis)** Analysts receive only their own sub-task; they return structured findings with source_ids, not raw text; retrieval is triggered on demand during execution; raw text stays in the database with only handles in context; after fixed overhead, the remaining window is split by quota (sub-task ≤ 5%, retrieved passages ≤ 55%, history ≤ 20%, memory ≤ 10%, output reserve ≥ 10%); stable content goes at the front of the prompt to hit the prompt cache. Summarisation is used only when the history partition exceeds its quota, and keeps numbers, source_ids and open questions.

**Verification** Experiment C: compare full context, summarisation and sub-task isolation on quality metrics, tokens and cost; record the prompt cache hit rate.

**Comparison data** Pending measurement.

---

## D17 Memory scope and write policy

**Status** Adopted

**Problem**
What memory stores, when it is written, and how to keep it from turning into noise.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Store all conversation history | Simple | Noisy retrieval, crowded context, may reuse unverified content |
| **Typed memory with explicit write policies** | Memory is trustworthy and controlled | More complex design |

**Decision** Keep three kinds of long-term memory only: episodic (past conclusions that passed every Critic check, with their source_ids), semantic (stable facts supported by at least two independent sources and not varying by reporting period), and user preferences (set explicitly or repeated at least three times). Memory retrieval also obeys PIT; reused conclusions still carry their original sources and pass this run's verification; on conflict, the old memory is marked superseded, never physically deleted.

**Not done** Procedural memory (deriving analysis paths from high-scoring trajectories), because the evaluation set is not large enough to tell high-scoring trajectories from luck.

**Verification** For repeated research on the same security, compare cost, latency and evaluation metrics with memory on and off; metrics must not drop.

---

## D18 Task queue: Redis Streams

**Status** Adopted

**Problem**
How minute-long research tasks run asynchronously.

**Options**

| Option | Pros | Cons |
|---|---|---|
| **Redis Streams (consumer group + ack)** | Redis is already in the stack; unacknowledged messages can be claimed by another worker | Heartbeats, orphan recovery and dead-lettering must be built |
| Celery | Mature ecosystem | Thick abstraction; recovery semantics must be reconciled with LangGraph checkpoints |
| PostgreSQL queue (`SELECT ... FOR UPDATE SKIP LOCKED`) | Same database as business data; transactional | Frequent polling loads the database |
| A workflow engine such as Temporal | The most complete durable execution | Adds a set of stateful services whose role overlaps LangGraph's checkpoints |

**Decision** Deliver tasks through Redis Streams; recovery semantics are provided by LangGraph checkpoints. Workers take a distributed lock per run_id and write heartbeats; runs whose heartbeat times out are re-queued; runs exceeding the recovery limit are marked failed.

**Reasoning** Execution state is already persisted by checkpoints; the queue only needs to hand each task reliably to some worker, not provide workflow-engine capabilities.

**Change when** Multiple consumer groups, long-term message retention or a cross-system event bus are needed (consider Kafka or similar); more complex long-running transaction orchestration is needed (consider a workflow engine).

---

## D19 Delivery semantics: at-least-once + idempotency

**Status** Adopted

**Problem**
A worker can crash after a node finishes but before its checkpoint is written. As long as there are external calls, no node can be guaranteed to run exactly once.

**Options**

| Option | Pros | Cons |
|---|---|---|
| At most once | Never duplicates | Tasks are lost on crash |
| **At least once + idempotency** | No lost tasks; side effects take effect once | Re-execution costs extra model calls |
| Claim exactly once | — | Impossible in the presence of external calls |

**Decision** At-least-once execution with idempotent side effects: run_event is deduplicated by a unique `(run_id, seq)` constraint; report and claim are upserted keyed by run_id; side-effecting tool calls carry an idempotency key `(run_id, node, call_index)`. Within a node, business data is written first and the checkpoint second; if a crash falls between the two, the node re-runs on recovery and idempotency keeps the result unchanged.

**Reasoning** LangGraph's checkpointer uses its own connection and does not share a transaction with business tables; write ordering plus idempotency does not depend on framework internals.

**Companion measure** A global retry budget keeps the three retry layers — model calls, queue redelivery and task recovery — from multiplying; upper-layer retries resume from the checkpoint rather than replaying completed model calls.

**Verification** Fault injection: kill the worker during a node and before and after the checkpoint write; check the recovery rate, the number of re-executed nodes, and whether any business data is duplicated.

---

## D20 Model access: tier abstraction and provider neutrality

**Status** Adopted

**Problem**
How business code refers to models, and how to deal with model availability differing by deployment region.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Business code calls a vendor SDK directly | Simplest | Changing models means changing business code; no unified cost accounting |
| **Business code refers only to tiers (strong / medium / fast); mapping lives in configuration** | Switch wholesale; trade cost per role; evaluation can compare mappings | A unified call interface and price table must be maintained |

**Decision** The llm module provides one interface for tier routing, structured output validation, retries, caching, and token and cost accounting. It supports Anthropic and OpenAI-compatible endpoints (DeepSeek, Qwen and others). The result cache is disabled in evaluation mode.

**Reasoning**
- Anthropic's model services are not offered in mainland China; a mainland deployment must use models that can be called there compliantly. With the tier abstraction, that is a configuration change.
- Roles need different capabilities; mapping by tier trades cost against quality per role.

**Verification** Experiment D: sweep tier mappings and plot the quality–cost Pareto frontier to choose the default mapping.

---

## D21 Evaluation method

**Status** Adopted

**Problem**
How to measure system quality credibly.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Manual trial use | Nothing to build | Not repeatable, no regression detection |
| LLM grading for everything | Covers open questions | Judges are biased (toward longer answers and so on) and cannot be trusted as-is |
| **Code grading first + human-calibrated LLM grading + separate retrieval evaluation** | Each question type gets its most reliable grader | Requires labelling and calibration effort |

**Decision**
- factual: code compares numbers with tolerance and unit normalisation; analytical: an LLM grades against a rubric; retrieval: Recall/MRR/NDCG, evaluated separately.
- The LLM judge is first calibrated against at least 30 human-scored items; if agreement falls short, the rubric is revised; changing the judge model requires recalibration.
- Items are split into a development set and a holdout set; tuning looks only at the development set, and the holdout runs only at milestone acceptance.
- factual items record the page of their gold evidence, so retrieval failures and generation failures can be told apart.
- Each item runs several times; results report mean and standard deviation, with confidence intervals for small samples.

**Reasoning** Evaluation is the yardstick for every other decision, so its own credibility has to come first.

---

## D22 CI evaluation gate

**Status** Adopted

**Problem**
How to stop changes to prompts, models or retrieval parameters from silently degrading quality.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Unit tests only | Fast and cheap | Cannot detect quality regressions |
| Full evaluation on every commit | Most complete | Too costly and slow |
| **Fixed-seed sample on PRs, full evaluation on a schedule** | Bounded cost; blocks obvious regressions | The sample may miss some regressions |

**Decision** Changes that affect quality (prompts, agent definitions, retrieval parameters, model configuration) run a fixed-seed sample of about 30% of the evaluation set on the PR and compare it with the baseline; a drop in a key metric of more than twice the standard deviation, or cost over threshold, blocks the merge. Full evaluation runs on a schedule. Baseline updates must be committed explicitly with a stated reason.

**Reasoning** A gate can only block before merge, so even a one-person project goes through PRs. Using the standard deviation as the threshold keeps run-to-run noise from being mistaken for regression.

---

## D23 Prompt injection: defence in depth

**Status** Adopted

**Problem**
Annual reports, announcements and external tool output read by the system may all carry instructions aimed at the model.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Only tell the model in the prompt not to follow instructions in documents | Cheap | Not reliable |
| Input detection only | Catches known patterns | Weak against variants and indirect injection |
| **Layered: data boundary markers + least privilege + re-validated arguments + deterministic paths for high-risk actions + approval** | Something still holds when one layer fails | More work to build and test |

**Decision**
- Direct injection: rule-based detection at the entry point plus a small classifier model; hits are rejected and audited.
- Indirect injection: tool output is wrapped in data boundary markers and declared as data; each role sees only the tools it needs; tool arguments are re-validated before execution; key parameters such as `as_of` are injected by the framework; high-risk actions are never triggered directly by the model; access to restricted data needs human approval.

**Reasoning** Prompt injection cannot be fully prevented, so no single measure is relied on; instead, the damage a successful injection can do is limited.

**Verification** Build an injection test set (instructions hidden in documents) and measure attack success rate with and without defences, and the defences' effect on normal task success.

---

## D24 Data access control: filter before retrieval

**Status** Adopted

**Problem**
When roles may see different documents, how to ensure restricted content never appears in a report.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Filter after retrieval | Simple | Too few results after filtering; a bug lets restricted content into context |
| Ask the model not to output restricted content | — | Unreliable |
| **Permission conditions as part of the retrieval SQL** | Restricted content never enters context | Strict filters worsen recall shortfall (see D07) |

**Decision** Documents carry a classification and permitted roles; permission filters are appended to the retrieval SQL together with the PIT constraint and apply before similarity is computed. Tools and data endpoints declare `required_scopes`, checked before each call.

**Reasoning** What the model never sees, it cannot leak.

---

## D25 Observability: OpenTelemetry + in-house execution tree

**Status** Adopted

**Problem**
When an answer is wrong, how to tell whether retrieval, data lookup, reasoning or synthesis is to blame.

**Options**

| Option | Pros | Cons |
|---|---|---|
| Plain text logs only | No extra components | Cannot reconstruct a task's full path |
| A third-party LLM observability platform | Works out of the box, with prompt management and labelling | Another service, or data sent out; separated from business data |
| **OpenTelemetry traces + Prometheus metrics + an execution tree built from run_event** | Standard protocols, no lock-in; execution tree lives with business data | Dashboards and query views must be built |

**Decision** The api generates a trace_id that propagates through the worker, sandbox and database calls; span attributes follow the GenAI semantic conventions; logs are JSON and always carry trace_id, with no full prompt text; the frontend renders an execution tree from run_event.

**Change when** Prompt version management and a human labelling workflow are needed; then evaluate a dedicated platform.

---

## D26 Frontend: React single-page application

**Status** Adopted

**Problem**
Single-page application or a server-rendered framework.

**Options**

| Option | Pros | Cons |
|---|---|---|
| **React + TypeScript SPA served statically by Nginx** | Static build output, simple deployment; clean front/back boundary | First paint depends on client-side rendering |
| Next.js or another server-rendering framework | Better first paint and SEO | One more Node runtime service; an internal tool needs no SEO |

**Decision** React + TypeScript SPA; TanStack Query manages server state; SSE connections are managed separately with resume based on `last_event_seq`; frontend and backend share TypeScript types generated from Pydantic models.

**Reasoning** This is an internal tool used after login and needs no SEO; static deployment removes a runtime service.

---

## D27 Deployment: single-host compose + reverse proxy

**Status** Adopted

**Problem**
How to deploy the demo and trial environment.

**Options**

| Option | Pros | Cons |
|---|---|---|
| **One cloud VM + Docker Compose + Caddy** | One-command deployment; automatic HTTPS; low cost | No high availability; host failure means downtime |
| Kubernetes | Replicas, autoscaling, rolling releases | Operational complexity and cost far beyond current needs |
| Each component on a separate managed cloud service | No operations | Scattered components; complex cost and configuration |

**Decision** Run compose on one cloud VM with Caddy as the only public entry point providing HTTPS; every other service stays on internal networks. Services are stateless, configuration is external, health probes are provided and graceful shutdown is supported, keeping a future move to Kubernetes open.

**Change when** Replicas with autoscaling, zero-downtime releases or multi-environment governance are needed.

**Details** See the [Deployment Guide](DEPLOYMENT.md).
