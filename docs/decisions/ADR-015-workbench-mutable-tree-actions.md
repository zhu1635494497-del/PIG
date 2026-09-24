# ADR-015：Workbench 可变树 Action / Workbench Mutable Tree Actions

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-23 / Decision date: 2026-09-23
- 决策：D41-A、D42-A、D43-A、D44-A、D45-A、D46-A / Decisions: D41-A, D42-A, D43-A, D44-A, D45-A, D46-A
- 范围：Workbench Milestone W5 / Scope: Workbench Milestone W5

## 中文规范正文

### 背景

W1–W4 已建立不可变 Original、Source Structure、完整初始 Workspace 投影和延迟
Materialization。W5 允许用户独立整理 Workspace，但不得把逻辑整理误写回 Source、
Container 或 Original。

### 决策

1. **D41-A**：同一有效 Parent 下，Active Sibling 使用从 `0` 开始的连续 `ordinal`。
   Move 与 Reorder 是同一个原子插入操作，事务内重排受影响 Sibling。
2. **D42-A**：Project 保存单调递增的 `workspace_revision`。每个 W5 写 Action 携带
   `expected_workspace_revision`；不匹配时拒绝整个 Action，不产生部分 Placement。
3. **D43-A**：Soft Delete 只把选中根 Item 标记为 `DELETED`。后代保留自身 Lifecycle，
   但在存在 Deleted Ancestor 时有效隐藏且不得被普通 Move/Add 使用。Restore 根 Item
   后，未单独删除的后代重新可见。
4. **D44-A**：`Add Workspace Inputs` 复用 W2–W4 Snapshot/Inspect 流程，并在
   `ImportSession` 保存目标 Workspace Parent 与预期 Revision。顶层投影直接进入目标，
   不先落到 Root 再 Move。
5. **D45-A**：用户 Folder Name 是 Logical Segment。Trim 后长度必须为 1–255，拒绝
   `.`、`..`、Slash、Backslash、NUL 与控制字符；允许同级重名，Identity 由 UUID 表达。
6. **D46-A**：Schema 使用前向 `0005_workspace_actions` Migration，增加 Project
   Revision、Import Target/Expected Revision、Constraint 与 Index；不迁移历史产品模型。

### Restore 与 Container 边界

Delete 保存 `previous_parent_id/previous_ordinal`。Restore 优先按插入语义回到旧位置；
旧 Parent 不存在、已删除或其祖先已删除时回退 Project Root，并在
`WORKSPACE_ITEM_RESTORED` 记录 `restore_fallback=true`。原本由 Source 投影在
Container View 下的 Child 可以恢复到同一结构 Parent；用户 Create/Add/Move-in 仍不得
把 Container View 当成 Write-back Target。

### Action 与 Event

W5 提供 `create_workspace_folder`、`move_workspace_item`、
`add_workspace_inputs`、`soft_delete_workspace_item` 和
`restore_workspace_item`。Delete 必须携带显式确认。成功操作分别持久化
`WORKSPACE_ITEM_ADDED/MOVED/DELETED/RESTORED`；Event 保存 Parent、Ordinal、Revision
及 Restore fallback。Add 在结构投影期间发现 Revision/Target 并发失效时转为明确
`INTERRUPTED`，不得静默留下半棵 Workspace Tree。

### 明确不做

W5 不实现 Rename、Permanent Purge、Container Repack/Write-back、Working Bytes 移动、
OS Open、External Edit Refresh、UI、多人协作、AI、Automation 或 MCP。

## English normative text

## Context

W1-W4 established immutable Originals, Source Structure, complete initial
Workspace projection, and lazy materialization. W5 lets users organize the
Workspace independently without writing logical organization back into Source,
Container, or Original facts.

## Decisions

1. **D41-A**: active siblings under one effective parent use dense zero-based
   `ordinal` values. Move and reorder are one atomic insertion operation that
   resequences affected siblings in the transaction.
2. **D42-A**: Project stores a monotonically increasing `workspace_revision`.
   Every W5 write action carries `expected_workspace_revision`; a mismatch
   rejects the entire action without a partial Placement.
3. **D43-A**: soft delete marks only the selected root Item `DELETED`.
   Descendants retain their own lifecycle but are effectively hidden, and
   normal Move/Add cannot use them while an ancestor is deleted. Restoring the
   root reveals descendants that were not separately deleted.
4. **D44-A**: `Add Workspace Inputs` reuses the W2-W4 snapshot/inspection flow
   and persists the target Workspace parent plus expected revision on the
   `ImportSession`. Top-level projection goes directly to the target instead of
   first appearing at root and then moving.
5. **D45-A**: a user folder name is a logical segment. Its trimmed length is
   1-255; `.`, `..`, slash, backslash, NUL, and control characters are rejected.
   Same-parent duplicate display names are allowed because UUID is identity.
6. **D46-A**: schema evolution uses forward revision
   `0005_workspace_actions`, adding Project revision, Import target/expected
   revision, constraints, and indexes. Historical product models are not
   migrated.

## Restore and Container boundary

Delete stores `previous_parent_id/previous_ordinal`. Restore inserts at the
prior location when valid. If the prior parent is missing, deleted, or has a
deleted ancestor, Restore falls back to Project root and records
`restore_fallback=true` on `WORKSPACE_ITEM_RESTORED`. A Source-projected child
that originally lived under a Container View may restore to that same
structural parent. User Create/Add/Move-in still cannot treat a Container View
as a write-back target.

## Actions and events

W5 exposes `create_workspace_folder`, `move_workspace_item`,
`add_workspace_inputs`, `soft_delete_workspace_item`, and
`restore_workspace_item`. Delete requires explicit confirmation. Successful
operations persist `WORKSPACE_ITEM_ADDED/MOVED/DELETED/RESTORED`, including
parent, ordinal, revision, and restore-fallback facts. If the Add target or
revision becomes invalid while inspection is pending, the Import becomes
explicitly `INTERRUPTED`; no partial Workspace subtree is silently retained.

## Explicit exclusions

W5 does not implement rename, permanent purge, Container repack/write-back,
physical Working-byte moves, OS open, external-edit refresh, UI, multi-user
collaboration, AI, Automation, or MCP.
