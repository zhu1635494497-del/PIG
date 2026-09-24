# PIG V1 Milestone 9：桌面 Evidence Browser 与受控打开 / Desktop Evidence Browser and Controlled Open

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段使用 PySide6 提供 Evidence Tree、Search、Detail、Event 和受控
> Open。新 Workbench UI 将以可变 Workspace Tree、Drag/Drop 和稳定 Working File
> 为中心。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-15 / Date: 2026-09-15
- 范围：最小 PySide6 Desktop UI 与 D8 Controlled Open / Scope: minimal PySide6 desktop UI and D8-controlled file opening
- 架构决策 / Architecture decision: `ADR-007`

## 1. Closed user flow

```text
Create or load Project
  -> register Folder/File Source
  -> run queue-based Project processing
  -> query persisted direct Relationships
  -> render Evidence Tree
  -> search/filter structural and Metadata fields
  -> inspect Node, Artifact, Metadata, Lineage, and Event facts
  -> request allowed file open
  -> backend allowlist + current integrity verification
  -> structured Event result
  -> host file association handoff
```

The UI is a presentation/client layer. All Source registration, processing,
search, Manifest export, Lineage retrieval, open authorization, path resolution,
hashing, status changes, and Event writes remain behind Application boundaries.

## 2. Desktop surface

One window contains:

- New Project and Open Project;
- Import File and Import Folder;
- Process Project;
- Export Manifest;
- Evidence Tree with name, format, and current processing status;
- bounded Search Results with text, format, and status filters;
- Node details with Logical Path, Source, Artifacts, Metadata, and persisted
  ancestor Lineage;
- latest 500 Processing Events;
- double-click and explicit-button controlled Open File.

There is no Dashboard, user center, workflow designer, assistant home, or empty
navigation module.

## 3. State, persistence, and events

Tree/search/detail/load queries are read-only and emit no Event. Open File does
not change Node processing status. It does update current Source and Artifact
integrity states during verification and persists the correlated open-result
history.

Alembic revision `0004` extends the constrained vocabulary with
`SOURCE_UNREADABLE_DETECTED` and `OPEN_HANDOFF_FAILED`; it adds no new table.
Project lookup remains one-Project-per-database through
`ProjectRepository.get_singleton()`.

## 4. Security boundary

- Unknown and non-allowlisted formats cannot reach the OS adapter.
- Every open requires one byte-bearing Artifact.
- External root and folder-descendant bytes are revalidated against immutable
  accepted fingerprints.
- Workspace Artifact paths are contained, non-symlink regular files and are
  rehashed immediately before handoff.
- The adapter never invokes a command shell.
- UI messages show stable safe error codes; stack traces remain Debug Log only.
- Original Source is never modified, moved, renamed, or opened through an
  unverified arbitrary path.

## 5. Verification

Executable tests cover Project loading, parent/ordinal tree data, PDF open,
Unknown denial, changed external Source denial, workspace-extracted PDF open,
host handoff failure, Windows/Linux adapter invocation, missing/relative target
rejection, and an offscreen Qt window flow for tree/search/detail/open/Event.

## 6. Run locally

From the repository virtual environment:

```powershell
.\.venv\Scripts\pig-desktop.exe
```

Development module invocation:

```powershell
.\.venv\Scripts\python.exe -m pig.ui.app --workspace-root <absolute-workspace-path>
```

`--workspace-root` must identify where new Project workspaces are created.
`--seven-zip` may specify the approved absolute 7-Zip executable for RAR.

## 7. Explicitly deferred

Now not implemented:

- pause/cancel, retry UI, persistent background jobs, installers, signing, or
  automatic recovery. UI-only worker threads, explicit recovery, reversible
  orphan quarantine, performance qualification, and internal release packaging
  were implemented in Milestone 10;
- preview, thumbnail/OCR, content indexing, FTS, semantic search, or cross-project
  search;
- rename/delete/move, reveal-in-folder, arbitrary external export destination,
  or Original Source mutation;
- public Tool/MCP, Workflow/Automation engine, AI, RAG, Agent, Graph DB, or Vector
  DB.
