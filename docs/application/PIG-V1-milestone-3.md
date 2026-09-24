# PIG V1 Milestone 3：Project / Source / Root Node 最小闭环 / Minimum Loop

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段实现 Project 创建、External Source 登记、Root Node、SQLite
> Persistence 和基础 Event 的最小闭环。它属于旧证据导向实现，仅供历史参考。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-13 / Date: 2026-09-13
- 范围：创建 Project 并登记一个已验证 Root Source 所需的 Application Action 与 Local Adapter / Scope: Application actions and local adapters required to create a Project and register one verified root Source

## Outcome

Milestone 3 establishes the first executable domain-data loop:

```text
Create Project
  -> reserve controlled workspace
  -> migrate project.sqlite
  -> persist Project + PROJECT_CREATED
  -> publish workspace

Register Source
  -> validate absolute local path
  -> reject source symlinks
  -> inspect source read-only
  -> hash a stable regular file (folders have no aggregate hash)
  -> persist Source + Root Node + self-lineage
  -> persist Original Reference Artifact for a file source
  -> persist state/history events atomically
  -> query Project overview or Node details
```

No child discovery, format detection, Handler selection, queue, extraction, or recursive processing is performed.

## Application actions

The in-process contract is `PigApplication` with four actions:

| Action | Input | Durable effect / output |
|---|---|---|
| `create_project` | name, optional description, actor, optional absolute workspace root | Creates one isolated workspace and migrated SQLite database; stores `Project(CREATED)` and `PROJECT_CREATED`; returns IDs and paths. |
| `register_source` | project/database identity, absolute source path, expected `FILE` or `FOLDER`, actor | Read-only verifies the Source, stores the catalog root, artifact where applicable, lineage, current state, and events in one transaction. |
| `get_project_overview` | project/database identity | Returns Project, Sources, roots, root artifacts, and event history. No writes. |
| `get_node` | project/database/node identity | Returns Node, owning Source, Artifacts, and persisted lineage. No writes. |

These are Application actions, not public Tool contracts. Tool schemas remain a later boundary built over stable use cases.

## Workspace baseline

The local composition root has a default absolute workspace root. A caller may
explicitly select a different absolute workspace root for one Project creation.
A Project is always created at:

```text
<workspace-root>/
└── projects/
    └── <project-id>/
        └── project.sqlite
```

Creation first uses the sibling staging directory `.creating-<project-id>`. The database migration and initial transaction complete there; only then is the directory renamed to its final name. Failed creation removes only that validated staging directory.

The desktop UI asks for this root during every New Project action, displays the
resulting Project directory after creation, and keeps the active Project path
visible. This does not change the approved physical layout: the Project name is
evidence metadata and is never used as an untrusted filesystem segment.

Milestone 3 does not create speculative `extracted`, `derived`, or `manifests` directories. A later authorized milestone creates a directory only when it owns real output there. Changing this workspace baseline after Milestone 3 is an architecture decision.

## Source acceptance and identity

- The caller supplies an absolute native local path and the intended source kind (`FILE` or `FOLDER`).
- A nonexistent path, kind mismatch, non-regular special file, or symbolic link is rejected before catalog mutation.
- File bytes are opened read-only and streamed through SHA-256.
- File identity, size, and modified time are checked before and after hashing. A detected race is rejected as `SOURCE_CHANGED_DURING_READ`.
- A folder is registered without an aggregate size or hash. Its children are not enumerated in this milestone.
- The accepted locator is an absolute `file:` URI and its native path flavor is retained.
- The external source is never copied, renamed, moved, deleted, touched, or opened for writing.
- Each successful registration creates a new Source identity. Re-registering a path does not rewrite an older Source fact.

Input-validation failures occur before a Source becomes a domain object, so they return a structured `ApplicationError` and create no partial Source or event. Failures after domain acceptance will require durable processing errors in later processing milestones.

## Persisted state and events

Project creation stores current status `CREATED` and `PROJECT_CREATED`.

The first successful source registration changes the Project from `CREATED` to `IMPORTING`. A Project already in `IMPORTING` remains there. Re-import from later terminal Project states follows the accepted Project state machine.

The accepted Source current state is `AVAILABLE`; its history records:

1. `SOURCE_REGISTERED`: `null -> REGISTERED`
2. `SOURCE_VERIFICATION_STARTED`: `REGISTERED -> VERIFYING`
3. `SOURCE_VERIFIED`: `VERIFYING -> AVAILABLE`
4. `NODE_DISCOVERED`: root becomes `DISCOVERED`
5. `ARTIFACT_REGISTERED`: only for a file Source

Project status, Source, root Node, self-lineage, file Artifact, and these events commit in one SQLite transaction. Event ordering remains the Milestone 1 contract (`occurred_at`, then ID); a project-scoped sequence number is not introduced in Milestone 3.

## Root modeling

| Source | Root Node | Artifact | Lineage |
|---|---|---|---|
| Folder | `CONTAINER / FOLDER / DISCOVERED` | None; a directory is not treated as a byte Artifact | `(root, root, 0)` |
| File | `FILE / UNKNOWN / DISCOVERED` | Verified `ORIGINAL_REFERENCE / EXTERNAL_SOURCE` with size and SHA-256 | `(root, root, 0)` |

A file remains `UNKNOWN` until Milestone 4 detection. Renaming a `.zip` file does not make this use case classify it as ZIP.

`original_name` retains evidence text. `display_name` replaces control characters for safe presentation. Logical path uses `/` as the separator and escapes PIG delimiters `%`, `!`, and `/`; it is never used as a filesystem path.

## Module boundaries

- `pig.application`: request/result contracts, ports, and orchestration.
- `pig.domain`: state-transition policy and existing entities/invariants.
- `pig.infrastructure.filesystem`: controlled workspace and read-only Source inspection.
- `pig.infrastructure.database`: migration/UoW provider plus repositories.
- `pig.bootstrap`: local composition root. It is the only convenience assembly point.

The Application layer contains no SQL, archive logic, email parsing, UI logic, or OS file-opening behavior.

## Explicitly deferred

- Folder child discovery and ZIP processing: Milestone 4.
- Queue-based recursive engine and descendant lineage: Milestone 5.
- EML/MSG, 7z/RAR, Manifest, Search, PySide6, recovery, packaging: their approved later milestones.
- UI, public Tool/MCP contract, Workflow, Agent, Automation, AI, OCR, and content indexing: not implemented.

## Verification

Milestone 3 tests cover:

- atomic Project workspace/database creation and initial event;
- no speculative workspace directories;
- external file bytes and timestamps remain unchanged;
- SHA-256, Source, Root Node, Artifact, status, events, and self-lineage round trip;
- folder root registration without enumeration or byte Artifact;
- missing, relative, and kind-mismatched Source rejection without partial catalog state;
- Project and Node query actions.
