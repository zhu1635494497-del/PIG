# PIG V1 Workbench W1 实施记录 / Workbench W1 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-21 / Date: 2026-09-21
- 决策：D25-B / Decision: D25-B
- 后续状态：W2 已另行授权并完成 / Follow-up: W2 was separately authorized and completed

## 中文实施记录

### 目标与边界

W1 建立新 Workbench Domain 和 Persistence Foundation。它不读取或复制外部文件，
不调用格式 Handler，不物化 Working File，也不修改桌面 UI。

### 领域对象

新增 `ImportSession`、`OriginalSnapshot`、`OriginalArtifact`、`WorkspaceItem`、
`WorkspacePlacement` 和 `WorkingArtifact`。`ProcessingEvent` 增加显式的 Import、
Snapshot、Workspace Item 和 Working Artifact 身份字段。

状态维度分别建模为 `ImportSessionStatus`、`OriginalSnapshotStatus`、
`WorkspaceItemLifecycleStatus`、`WorkspaceMaterializationStatus` 和
`WorkingContentStatus`，并由确定性转换函数校验。

### 数据流

```text
Create empty Project
  -> model_version = workbench-v1
  -> Alembic 0001_workbench baseline
  -> Repository transaction
  -> persist/reload Workbench objects
```

W1 Test Fixture 可以表达完整对象关系，但不代表已经实现真实导入：

```text
Project
  -> ImportSession
  -> OriginalSnapshot
  -> OriginalArtifact
  -> WorkspaceItem + WorkspacePlacement
  -> WorkingArtifact
  -> ProcessingEvent
```

### 持久化与不变量

- 每个 Project 一个 SQLite；
- Original Artifact 的 Storage Identity、Size 和 SHA-256 不可改写；
- Source Node Binding 只允许从空值赋值一次；
- Workspace Origin Binding 不可改变；
- Placement 必须同 Project、Parent 必须是 Active 普通 Folder，并且不得成环；
- Working Artifact Baseline 不可改变，Current Fingerprint 可在未来刷新；
- Processing Event 不得 UPDATE 或 DELETE；
- Unit of Work 未显式 Commit 时自动 Rollback。

### 版本边界

新 Project 使用 `workbench-v1`。旧版本通过 Application Load Boundary 返回
`UNSUPPORTED_PROJECT_MODEL_VERSION`。未实现旧数据迁移。

W1 当时阻止旧 External-reference `register_source` Action。W2 已提供 Snapshot Import
Contract；该旧 Action 现在永久返回 `EXTERNAL_REFERENCE_IMPORT_RETIRED`，调用者必须
使用 `import_project_items`。

### 测试与验收

自动化覆盖状态转换、非法转换、所有新对象 Round-trip、Rollback、Repository 和
Database 两层 Cycle Rejection、Original Immutable、Append-only Event、Migration
Metadata 一致性、Downgrade、Project 创建/重载和旧 Model Version 拒绝。

结果：`87 passed, 80 skipped`。80 个 Skip 是 ADR-010 已取代的历史 Milestone 3–10
Application/UI Acceptance；测试文件没有删除，后续由 W2–W7 测试逐步替换。

### 未闭环边界

W1 没有外部字节复制、Snapshot Staging/Publish、Source Inspection、Workspace Action、
Lazy Materialization、Open/Edit Refresh 或 Workbench UI。这些能力不得从 W1 的可持久
化对象推断为已经可用。

## English implementation record

## Goal and boundary

W1 establishes the new Workbench domain and persistence foundation. It does not
read or copy external files, invoke format handlers, materialize Working Files,
or modify the desktop UI.

## Domain objects

W1 adds `ImportSession`, `OriginalSnapshot`, `OriginalArtifact`,
`WorkspaceItem`, `WorkspacePlacement`, and `WorkingArtifact`. `ProcessingEvent`
gains explicit Import, Snapshot, Workspace Item, and Working Artifact identity
fields.

State dimensions are modeled separately as `ImportSessionStatus`,
`OriginalSnapshotStatus`, `WorkspaceItemLifecycleStatus`,
`WorkspaceMaterializationStatus`, and `WorkingContentStatus`, with deterministic
transition validation.

## Data flow

```text
Create empty Project
  -> model_version = workbench-v1
  -> Alembic 0001_workbench baseline
  -> Repository transaction
  -> persist/reload Workbench objects
```

W1 test fixtures can represent the complete relationship below, but this does
not mean real import has been implemented:

```text
Project
  -> ImportSession
  -> OriginalSnapshot
  -> OriginalArtifact
  -> WorkspaceItem + WorkspacePlacement
  -> WorkingArtifact
  -> ProcessingEvent
```

## Persistence and invariants

- one SQLite database per Project;
- Original Artifact storage identity, size, and SHA-256 are immutable;
- Source Node binding can be assigned once from null;
- Workspace origin binding is immutable;
- Placement is Project-local, its parent is an active ordinary Folder, and it
  cannot form a cycle;
- Working Artifact baseline facts are immutable while current fingerprints may
  be refreshed later;
- Processing Events cannot be updated or deleted;
- a Unit of Work without an explicit commit rolls back.

## Version boundary

New Projects use `workbench-v1`. The Application load boundary rejects older
versions with `UNSUPPORTED_PROJECT_MODEL_VERSION`. No old-data migration exists.

W1 initially blocked the old external-reference `register_source` action. W2
now provides the snapshot-import contract; the old action permanently returns
`EXTERNAL_REFERENCE_IMPORT_RETIRED`, and callers use `import_project_items`.

## Tests and acceptance

Automated coverage includes valid and invalid transitions, round trips for all
new objects, rollback, Repository- and database-level cycle rejection, Original
immutability, append-only Events, migration/metadata parity, downgrade, Project
creation/reload, and rejection of old model versions.

Result: `87 passed, 80 skipped`. The 80 skips are historical Milestone 3-10
Application/UI acceptance tests superseded by ADR-010. Their files remain and
will be replaced incrementally by W2-W7 coverage.

## Open boundaries

W1 does not implement external-byte copying, Snapshot staging/publish, Source
inspection, Workspace actions, lazy materialization, open/edit refresh, or a
Workbench UI. Persistable objects must not be mistaken for completed user
capabilities.
