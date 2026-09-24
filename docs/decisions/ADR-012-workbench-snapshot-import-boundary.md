# ADR-012：Workbench Snapshot Import 边界 / Workbench Snapshot Import Boundary

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-21 / Decision date: 2026-09-21
- 实施日期：2026-09-22 / Implementation date: 2026-09-22
- 决策：D26-A、D27-B、D28-A、D29-A / Decisions: D26-A, D27-B, D28-A, D29-A
- 范围：Workbench Milestone W2 / Scope: Workbench Milestone W2

## 中文规范正文

### 背景

W1 只建立了可持久化的 Workbench 对象，没有定义 Folder Snapshot 的显式成员树、
W2 与 W3 的会话边界、Snapshot-backed Source 的创建时机，或多输入中单个失败的
原子性。

### 决策

1. **D26-A**：Original Storage 仅使用生成标识，物理布局固定为：

   ```text
   <project>/.staging/imports/<import-session-id>/<snapshot-id>/
   <project>/originals/<snapshot-id>/objects/<artifact-id>/content
   ```

   Folder 的名称与层级保存为显式 `OriginalSnapshotEntry` Tree；不可信名称不参与
   物理路径选择。

2. **D27-B**：一个 `ImportSession` 跨越 W2 Snapshot Capture 与 W3 Structure
   Inspection。W2 至少有一个成功 Snapshot 时结束在 `INSPECTING`，不写入虚假的
   `SUCCESS`。只有全部顶层输入失败时，W2 将 Session 写为 `FAILED`。

3. **D28-A**：W2 取代旧 External-reference Source 语义。每个 `READY` Snapshot
   创建一个 Snapshot-backed `Source` 和一个 Root Source `Node`。W2 不发现 Folder
   Child、不调用格式 Handler；这些属于 W3。

4. **D29-A**：完整性边界是单个顶层 Snapshot。Symlink/Reparse Point、Unreadable、
   Copy-time Change、Limit 或 Publish Failure 会回滚该 Snapshot 的 Staging/Published
   Bytes，并保留结构化失败状态；其他顶层输入继续。Folder Snapshot 不接受不完整
   子集。

为表达逐项结果，`ImportSessionItem` 作为显式实体保存输入顺序、状态、Snapshot
绑定和错误。幂等键在 Project 内唯一；同一键与不同请求组合必须返回
`IDEMPOTENCY_CONFLICT`。

### 后果

- `0002_snapshot_import` 是 `0001_workbench` 之后的前向 Migration；
- W2 Action 为 `import_project_items` 和 `verify_original_snapshot`；它们是 typed
  in-process Application Contract，不是公共 Tool；
- Original File 以流式 SHA-256 复制并在 Publish 后按只读方式保存；
- W2 不实现 Archive/Email Inspection、Workspace Item 初始化、Materialization 或 UI；
- 包含 W2 数据的数据库不允许降级到 W1，避免静默丢失 Snapshot 事实。

## English normative text

## Context

W1 made the Workbench objects persistable but did not define an explicit member
tree for folder snapshots, the W2/W3 session boundary, when a snapshot-backed
Source is created, or the atomicity of one failed item in a multi-input import.

## Decisions

1. **D26-A**: Original storage uses generated identities only, with this fixed
   layout:

   ```text
   <project>/.staging/imports/<import-session-id>/<snapshot-id>/
   <project>/originals/<snapshot-id>/objects/<artifact-id>/content
   ```

   Folder names and hierarchy are persisted as an explicit
   `OriginalSnapshotEntry` tree. Untrusted names never select physical paths.

2. **D27-B**: one `ImportSession` spans W2 snapshot capture and W3 structure
   inspection. If at least one snapshot succeeds, W2 ends at `INSPECTING`; it
   does not claim a false `SUCCESS`. W2 records `FAILED` only when every
   top-level input fails.

3. **D28-A**: W2 replaces external-reference Source semantics. Every `READY`
   snapshot receives one snapshot-backed `Source` and one root Source `Node`.
   W2 does not discover folder children or invoke format handlers; that belongs
   to W3.

4. **D29-A**: one top-level snapshot is the completeness boundary. A symlink or
   reparse point, unreadable input, copy-time change, resource limit, or publish
   failure rolls back that snapshot's staged/published bytes and persists a
   structured failure, while other top-level inputs continue. Folder snapshots
   never accept an incomplete subset.

`ImportSessionItem` is an explicit entity for per-input order, state, snapshot
binding, and error. An idempotency key is unique within one Project; reuse with
a different request must fail with `IDEMPOTENCY_CONFLICT`.

## Consequences

- `0002_snapshot_import` is a forward migration after `0001_workbench`.
- W2 exposes `import_project_items` and `verify_original_snapshot` as typed
  in-process Application contracts, not public Tools.
- Original files are copied with streaming SHA-256 and made read-only after
  publication.
- Archive/email inspection, Workspace Item initialization, materialization, and
  UI remain outside W2.
- A database containing W2 rows cannot downgrade to W1 because doing so would
  silently discard snapshot facts.
