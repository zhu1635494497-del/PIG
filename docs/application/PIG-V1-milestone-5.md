# PIG V1 Milestone 5：递归处理与 Lineage / Recursive Processing and Lineage

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段实现 Queue-based Recursive Processing、Project-level Job、
> NodeExecutor、持久化 Direct Relationship 与 Lineage Closure。新 Workbench 可复用
> Orchestration，但完整 Lineage 不再是 V1 主验收目标。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-14 / Date: 2026-09-14
- 范围：同步 Queue-based Folder/ZIP Recursive Processing / Scope: synchronous queue-based recursive Folder/ZIP processing
- 架构决策 / Architecture decision: `ADR-003`

## 1. Goal and closed loop

Milestone 5 turns the single-level Milestone 4 action into a project processing workflow:

```text
process_project
  -> create/start one Job
  -> seed DISCOVERED Nodes into deque
  -> NodeExecutor creates one Attempt per Node
  -> verify input and detect format
  -> terminal File completes, or Container Handler creates direct Children
  -> persist Child relationship and lineage closure
  -> append newly DISCOVERED Children to deque
  -> repeat until queue is empty
  -> aggregate outcomes and project final Project/Job states
```

The implementation is iterative. No Handler calls the processor recursively.

## 2. Application boundaries

`ProjectProcessingService` owns:

- Job creation, start, finish, and policy snapshot;
- one correlation ID for the complete action;
- the in-memory FIFO `deque`;
- shared expanded-byte accounting;
- result aggregation;
- final Project state projection.

`NodeExecutor` owns:

- exactly one `DISCOVERED -> PENDING -> PROCESSING -> terminal` Node lifecycle;
- one independently numbered Processing Attempt;
- Source or Artifact verification;
- deterministic detection and Handler resolution;
- Child Node, Artifact, direct Relationship, and lineage persistence;
- structured per-Node events and expected error outcomes.

Folder and ZIP implementations remain behind `ContainerHandler`; neither knows about Job orchestration or the queue.

## 3. Application Actions

`process_project` input:

- `project_id`
- absolute `database_path`
- `actor`
- immutable `ProcessingPolicy`

Output:

- Job ID and final Job status;
- final Project status;
- ordered processed Node IDs and Attempt IDs;
- warning and error counts;
- actual Project-workspace bytes materialized by this Job.

`process_node` remains available for one explicitly selected `DISCOVERED` Node. It now delegates to the same `NodeExecutor`, creates its own one-Node Job, and leaves Project `PROCESSING` when discovered descendants remain.

These are Application Actions, not public API, MCP, or Agent Tool implementations.

## 4. Recursive identity and lineage

Every Handler result remains a direct child of the Container that exposed it:

- Folder child: `FOLDER_CONTAINS`
- ZIP member: `ARCHIVE_ENTRY`

Repository child registration persists both the direct relationship and transitive lineage closure. A chain such as:

```text
Folder -> Folder -> ZIP -> ZIP -> XLSX
```

therefore gives the XLSX self-lineage at distance 0 and four persisted ancestors at distances 1 through 4. Queue order and physical Artifact paths do not participate in lineage identity.

ZIP member path prefixes remain Logical Path segments. An explicit ZIP directory member is recorded as a successful evidence marker and is not treated as a materialized Folder Container.

## 5. Input integrity

Before every Node runs:

- a Source root is revalidated against its registered Source fingerprint;
- an external Folder descendant is resolved from persisted `FOLDER_CONTAINS` ancestry, constrained to the Source root, rejected on unsafe segments or symbolic links, and checked against its Artifact fingerprint when it is a file;
- a Project-workspace Artifact is resolved only through its exact Artifact-ID storage key and rechecked for regular-file type, symbolic links, size, and SHA-256.

External descendant changes update that Node and Artifact to a durable changed/mismatch outcome without declaring the complete Folder Source changed. Workspace Artifact loss or mismatch is an integrity failure, not a Source mutation.

Original Source bytes are never modified or used as an extraction destination.

## 6. Global policies

- Maximum depth: a would-be Child beyond the limit is catalogued as `LIMIT_EXCEEDED`, receives its relationship and lineage, has no Artifact, and is not queued.
- Maximum Project Nodes: checked against the existing persisted Project catalog before a Container accepts its full descriptor set.
- Maximum total expanded size: shared by the complete Job. Each Node receives only the remaining allowance, and the Artifact Store also enforces actual streamed bytes.
- Per-container entry count, single-file size, compression ratio, filename, encryption, and archive path rules remain Handler/security-policy checks.

The Job stores the original requested policy snapshot. A decreasing remaining-byte value is execution context, not a replacement business fact.

## 7. State projection

Normal recursive lifecycle:

```text
Project: IMPORTING/READY/... -> PROCESSING -> READY | READY_WITH_WARNINGS | FAILED
Job: QUEUED -> RUNNING -> SUCCESS | PARTIAL_SUCCESS | FAILED
Node: DISCOVERED -> PENDING -> PROCESSING -> terminal outcome
Attempt: QUEUED -> RUNNING -> COMPLETED | FAILED
```

Projection rules after the queue is empty:

- any `DISCOVERED/PENDING/PROCESSING` Node: Project remains `PROCESSING`;
- all Nodes `SUCCESS`: `READY`;
- at least one usable `SUCCESS/PARTIAL_SUCCESS` Node plus a non-success outcome: `READY_WITH_WARNINGS`;
- no usable Node and only terminal failures/blocks: `FAILED`.

Expected data/format/security outcomes complete the Attempt with a structured error. Unexpected implementation exceptions fail the Attempt and store a technical reference.

## 8. Recovery boundary

Before creating a new Job, the coordinator checks durable state. Existing `QUEUED/RUNNING` Jobs or Attempts, or `PENDING/PROCESSING` Nodes, cause `RECOVERY_REQUIRED`.

Now not implemented:

- automatic replay, rollback, reconciliation, or orphan cleanup;
- durable queue reconstruction or checkpoints;
- pause, resume, cancellation, or retry Actions;
- asynchronous or distributed workers.

This explicit block avoids silently processing around an interrupted chain. Recovery hardening remains Milestone 10.

## 9. Events

One project run emits one `JOB_CREATED`, `JOB_STARTED`, and `JOB_FINISHED`. Each executed Node emits its own Attempt and Node lifecycle events. Container processing continues to emit format detection, container open, child discovery/extraction, Artifact registration, relationship creation, and lineage update events.

All events in the run share the Job ID and correlation ID. Current state remains in entity status columns; Events remain append-only history.

## 10. Verification

Tests cover:

- Folder -> Folder -> ZIP -> ZIP -> terminal recursive processing;
- one shared Job and multiple per-Node Attempts;
- persisted multi-level lineage distances;
- Job-wide expanded-size exhaustion across separate ZIP Nodes;
- depth-boundary evidence without scheduling or materialization;
- external descendant fingerprint changes while preserving Folder Source state;
- Workspace Artifact tamper detection;
- interrupted active Job rejection with `RECOVERY_REQUIRED`;
- original requested policy snapshot and one Job start/finish event pair;
- complete Milestone 1–4 regression compatibility.

## 11. Explicitly deferred

Now not implemented:

- EML/MSG processing (Milestone 6);
- 7z/RAR processing and packaging/license decisions (Milestone 7);
- Manifest and Search (Milestone 8);
- PySide6 UI (Milestone 9);
- complete recovery, performance, packaging, and platform verification (Milestone 10);
- AI, RAG, OCR, Agent, Workflow engine, Automation engine, MCP, Graph DB, Vector DB, or distributed infrastructure.
