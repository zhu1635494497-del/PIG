# PIG V1 Milestone 6：EML 与 MSG 处理 / EML and MSG Processing

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段通过 Standard Library EML Parser 和受控 extract-msg Adapter
> 发现邮件附件与嵌入邮件，并沿用统一 Handler/Queue/Security Contract。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-14 / Date: 2026-09-14
- 范围：Email Structure Inspection、Attachment Materialization、Recursion、Metadata 与 Lineage / Scope: structural email inspection, attachment materialization, recursion, metadata, and lineage
- 架构决策 / Architecture decision: `ADR-004`

## 1. Goal and closed loop

Milestone 6 adds EML and MSG to the existing project-level processing workflow:

```text
EML/MSG Node
  -> verify Source or Workspace Artifact
  -> detect email Container
  -> inspect headers and attachment descriptors
  -> persist structural NodeMetadata
  -> materialize allowed byte-bearing attachments through ArtifactStore
  -> persist direct EMAIL_ATTACHMENT or EMBEDDED_MESSAGE relationship
  -> persist lineage closure and Processing Events
  -> enqueue newly DISCOVERED attachment Nodes
  -> process nested EML/MSG/ZIP/Folder-capable descendants in the same Job
```

The existing `ProjectProcessingService` owns the queue and global Job budget. EML/MSG Handlers do not invoke recursion and do not write the database.

## 2. Domain and persistence

Milestone 6 uses the existing objects:

- email message: a `Node` with `kind=CONTAINER` and `format=EML|MSG`;
- byte-bearing attachment: Child `Node` plus an `EXTRACTED_ARTIFACT` in `PROJECT_WORKSPACE`;
- ordinary attachment edge: `EMAIL_ATTACHMENT`;
- attached/embedded message edge: `EMBEDDED_MESSAGE`;
- ancestry: existing transitive `LineageRecord` closure;
- headers: typed `NodeMetadata` in namespace `email`;
- execution: existing `ProcessingJob`, per-Node `ProcessingAttempt`, current status, error, and append-only `ProcessingEvent`.

Persisted header keys are `subject`, `from`, `to`, `cc`, `bcc`, `date`, and `message_id` when present. EML parser defects are retained as JSON metadata. These are structural values from the deterministic parser. No person/entity model, normalized recipient table, email-body object, or content-index table is added now.

The existing SQLite schema already supports these facts, so Milestone 6 requires no Alembic migration. `max_email_parts` is added to the immutable `ProcessingPolicy` and persisted in the Job policy snapshot JSON.

## 3. Handler contract evolution

`ContainerInspection` returns:

- ordered Child descriptors;
- optional parent metadata descriptors.

Each Child descriptor can override the Handler's default relationship type and carry a media type. This is required because one email may contain both ordinary attachments and embedded messages. Folder and ZIP return the same inspection shape without metadata, preserving one Processing Framework.

## 4. EML behavior

`EmlHandler` uses the Python standard library. It:

- parses headers and MIME structure deterministically;
- recognizes non-message parts with `Content-Disposition: attachment` or a filename;
- recognizes nested `message/rfc822` parts as embedded messages;
- treats message bodies as non-child content and does not render them;
- materializes only attachment payload bytes through `ArtifactWriteSession`;
- applies the configured whole-file, MIME-part, single-output, total-output, filename, and depth/node limits.

An embedded message becomes an EML Artifact and re-enters detection/processing through the queue. It is not recursively parsed inside `EmlHandler`.

## 5. MSG behavior

`MsgHandler` depends only on the PIG-owned `MsgBackend` protocol. The production `ExtractMsgBackend`:

- opens MSG in strict mode;
- reports supported data, embedded-message, Web Reference, broken, and unsupported attachment kinds;
- maps a bounded ordered list to PIG descriptors;
- returns ordinary attachment or exported embedded-MSG bytes on materialization;
- closes parser-owned message handles on every inspection/read operation;
- never delegates filesystem output or remote loading to the third-party library.

The selected library, version boundary, GPLv3 distribution consequence, and release gate are recorded in ADR-004.

## 6. Logical path and physical storage

Email attachment Logical Paths use the same evidence boundary notation as archives:

```text
/supplier.msg!/forwarded.msg!/quote.zip!/final.xlsx
```

Raw attachment filenames are evaluated by the centralized archive-path policy. Absolute, traversal, device, NUL, or otherwise invalid path-like names are catalogued as blocked evidence. Allowed names are escaped for Logical Path display.

No attachment name is used as a physical output path. Physical storage remains:

```text
artifacts/<id-prefix>/<artifact-id>/content
```

Duplicate attachment filenames therefore remain distinct by ordinal discovery key, Node ID, and Artifact ID.

## 7. State and event behavior

The normal Node/Attempt lifecycle is unchanged. Email Containers emit the existing events for queued/started processing, format detection, Container open, Child discovery/extraction, Artifact registration, relationship creation, lineage update, and terminal outcome.

`CONTAINER_OPENED.details` records both `child_count` and `metadata_count`. Metadata remains queryable data in `node_metadata`; it is not encoded only in the event.

If one child is blocked or fails materialization while another succeeds, the email parent becomes `PARTIAL_SUCCESS`. Expected corrupt/unsupported/limit outcomes complete the Attempt with a structured error. Unexpected failures fail the Attempt and use the existing technical-reference path.

## 8. Security and permissions

- Original external EML/MSG bytes remain read-only and are fingerprint-revalidated before processing.
- Extracted attachments are staged, size/hash checked, published, and rolled back only by `LocalArtifactStore`.
- Web Reference attachments are not fetched.
- Symbolic link behavior is unchanged: external Source paths are rejected and email filenames never become filesystem paths.
- HTML, scripts, macros, embedded OLE execution, default-open behavior, and outbound network operations are absent.
- No new permission surface is introduced; this extends the existing write-side `process_project` / `process_node` Application Actions.

## 9. Verification

Tests cover:

- EML -> embedded EML -> ZIP -> XLSX processing in one Job;
- direct relationship types and multi-level persisted lineage;
- structural email metadata and explicit non-extraction of bodies;
- MIME-part count limit with a durable structured outcome;
- attachment filenames with path traversal, with no Artifact or outside write;
- Job-wide expanded-size budget shared by EML attachments;
- MSG -> embedded MSG and MSG -> attached EML queue recursion through a fake backend;
- Web Reference evidence without materialization/read;
- Adapter ordinary and embedded payload export without parser-controlled save paths;
- installed `extract-msg` mapping of an invalid real file to `CORRUPTED`;
- complete Milestone 1–5 regression compatibility.

## 10. Explicitly deferred

Now not implemented:

- email body extraction, HTML rendering, inline-body indexing, full-text search, or attachment preview;
- recipient/entity normalization, conversation/thread modeling, business tags, or semantic classification;
- digital signature/trust verification, TNEF-specific enrichment, password/decryption UI, or remote attachment retrieval;
- a redistributable valid-MSG fixture corpus and cross-platform packaging qualification;
- 7z/RAR processing (Milestone 7; must be separately confirmed as required by D4);
- Manifest and Search (Milestone 8), PySide6 UI (Milestone 9), and recovery/performance/packaging work (Milestone 10);
- Tool protocol, Workflow/Automation engine, MCP, AI, OCR, RAG, Graph DB, Vector DB, or distributed workers.
