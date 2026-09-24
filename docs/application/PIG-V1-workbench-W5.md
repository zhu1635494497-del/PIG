# PIG V1 Workbench W5 实施记录 / Workbench W5 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-23 / Date: 2026-09-23
- 决策：`ADR-015` / Decision: `ADR-015`
- 后续状态：W7 已完成；W8 未授权 / Later status: W7 complete; W8 not authorized

## 中文实施记录

### 1. 完成了什么

实现可持久化的 Logical Workspace Tree 写 Action：Create Folder、Move/Reorder、定向
Add、Soft Delete 与 Restore。新增 Project 级 Optimistic Revision，并让初始/新增结构
投影遵守 Active Sibling 连续顺序。新增 `0005_workspace_actions` Migration。

### 2. 涉及的领域对象

- `Project`：新增 `workspace_revision`；
- `ImportSession`：新增 Target Parent 与 Expected Revision；
- `WorkspaceItem`：保存 Logical Folder 和根 Tombstone Lifecycle；
- `WorkspacePlacement`：保存当前 Parent/Ordinal 与一次 Restore Placement；
- `ProcessingEvent`：保存 Add/Move/Delete/Restore 结果。

### 3. 用户操作到输出

```text
typed Workspace request
-> validate Project/model/database/revision
-> validate Item/target/effective lifecycle/cycle/name/confirmation
-> mutate Placement or Lifecycle in one SQLite transaction
-> resequence active siblings
-> advance Project workspace_revision
-> append structured Event
-> return Item + Placement + new revision

Add external input
-> immutable Snapshot + Source root
-> persist target folder and expected revision
-> eager structure inspection
-> direct Workspace projection under target
-> advance one Workspace revision
```

### 4. 状态变化

- Workspace Revision：每次成功的逻辑树事务增加 `1`；
- Lifecycle：`ACTIVE -> DELETED -> ACTIVE`；
- Deleted Ancestor 使后代有效隐藏，但不覆盖后代自身状态；
- 并发失效的 Pending Add：`INSPECTING -> INTERRUPTED`，Project 从 `IMPORTING` 转为
  `FAILED`，等待显式重新 Add。

### 5. Event 与 Log

成功 Action 使用 `WORKSPACE_ITEM_ADDED`、`WORKSPACE_ITEM_MOVED`、
`WORKSPACE_ITEM_DELETED` 和 `WORKSPACE_ITEM_RESTORED`。Event 保存旧/新 Parent、Ordinal、
Revision、删除恢复位置和 fallback。并发 Add 中断保存 `IMPORT_INTERRUPTED` 与 Project
Status Event。纯输入校验失败返回结构化 `ApplicationError`，不伪造成功 Event。

### 6. Tool 或 Action

新增五个 typed Application Action；它们是未来 Desktop/Tool Contract 的复用边界，但
本阶段没有建立 MCP、Agent Tool Registry 或外部 Tool Server。

### 7. 安全和权限影响

- Delete 由后端强制要求 `confirmed=true`；
- Move/Add 拒绝 Cross-project Identity、Cycle、Deleted Ancestor、File Parent 与 Container
  Write-back Target；
- Logical Name 不参与 Physical Path 选择；
- Move/Delete/Restore 不修改 Original、Source、Lineage 或 Working Artifact Storage Key；
- Permanent Purge 仍不可用。

### 8. 测试覆盖

新增 W5 Application 场景覆盖连续排序、同名 Folder、Subtree/Root Move、Cycle、Container
Target、Revision Conflict、显式删除确认、祖先 Tombstone、旧位置 Restore、Root
Fallback、Restart、定向 Add、Idempotent Replay、Pending Add Interrupt，以及 Original/
Source Relationship 不变。Migration Metadata 与 W1–W4 回归均通过。

全量结果：`111 passed, 95 skipped, 1 warning`。95 个 Skip 为 ADR-010 隔离的历史
Evidence/UI 测试和当前 Host 不允许创建的 Symlink 场景；Warning 来自刻意构造的重复
ZIP Member Name。

### 9. 当前尚未闭环的边界

W6 尚未实现稳定 Open、外部编辑、Fingerprint Refresh 与覆盖确认；W7 尚未把 W5
Action 接入 PySide6 Drag/Drop 和 Tree Interaction；W8 尚未执行 Crash Recovery、真实
规模 Benchmark 与 Packaging 重置。

### 10. 技术债务与下一步最小建议

当前 Revision 是单 Project 粗粒度锁，符合本地单用户 V1；若未来出现多人并发再评估
细粒度版本。Deleted Descendant 的“有效隐藏”由权威查询/Action 校验表达，W7 Tree/
Search 必须复用该语义，不能只过滤 Item 自身状态。下一步最小建议是单独批准 W6，先
实现稳定 Open/Edit Refresh 数据闭环，不提前写 W7 UI。

## English implementation record

## 1. What changed

Implemented durable Logical Workspace Tree writes: create folder, move/reorder,
targeted add, soft delete, and restore. Added Project-scoped optimistic revision
and dense active-sibling ordering for initial and newly added structure
projection. Added migration `0005_workspace_actions`.

## 2. Domain objects

- `Project` adds `workspace_revision`.
- `ImportSession` adds target parent and expected revision.
- `WorkspaceItem` stores logical folders and root-tombstone lifecycle.
- `WorkspacePlacement` stores current parent/order and one restore placement.
- `ProcessingEvent` stores Add/Move/Delete/Restore results.

## 3. User action to output

```text
typed Workspace request
-> validate Project/model/database/revision
-> validate Item/target/effective lifecycle/cycle/name/confirmation
-> mutate Placement or Lifecycle in one SQLite transaction
-> resequence active siblings
-> advance Project workspace_revision
-> append structured Event
-> return Item + Placement + new revision

Add external input
-> immutable Snapshot + Source root
-> persist target folder and expected revision
-> eager structure inspection
-> direct Workspace projection under target
-> advance one Workspace revision
```

## 4. State changes

- Workspace Revision increases by `1` for each successful logical-tree
  transaction.
- Lifecycle follows `ACTIVE -> DELETED -> ACTIVE`.
- A deleted ancestor effectively hides descendants without overwriting their
  own status.
- A concurrently invalidated pending Add becomes `INSPECTING -> INTERRUPTED`;
  Project moves from `IMPORTING` to `FAILED` pending an explicit new Add.

## 5. Events and logs

Successful actions use `WORKSPACE_ITEM_ADDED`, `WORKSPACE_ITEM_MOVED`,
`WORKSPACE_ITEM_DELETED`, and `WORKSPACE_ITEM_RESTORED`. Events retain old/new
parent, ordinal, revision, restore placement, and fallback. A concurrent Add
interruption persists `IMPORT_INTERRUPTED` plus Project status Event. Pure input
validation returns structured `ApplicationError` and does not fabricate a
success Event.

## 6. Tool or action impact

Five typed Application actions were added. They are the reusable boundary for
future Desktop/Tool contracts, but W5 adds no MCP, Agent Tool Registry, or
external Tool server.

## 7. Permission and safety

- Backend enforcement requires `confirmed=true` for delete.
- Move/Add rejects cross-Project identity, cycles, deleted ancestors, file
  parents, and Container write-back targets.
- Logical names never select physical paths.
- Move/Delete/Restore changes no Original, Source, Lineage, or Working Artifact
  storage key.
- Permanent purge remains unavailable.

## 8. Tests

New W5 Application scenarios cover dense order, duplicate folder names,
subtree/root move, cycle and Container-target rejection, revision conflict,
explicit delete confirmation, ancestor tombstones, prior-position restore,
root fallback, restart, targeted Add, idempotent replay, pending-Add interrupt,
and unchanged Original/Source Relationships. Migration metadata and W1-W4
regression pass.

The full result is `111 passed, 95 skipped, 1 warning`. The 95 skips are
ADR-010-quarantined historical Evidence/UI tests plus symlink cases unavailable
on this host. The warning comes from the intentionally duplicated ZIP member
name fixture.

## 9. Open boundaries

W6 has not implemented stable open, external editing, fingerprint refresh, or
replacement confirmation. W7 has not connected W5 actions to PySide6 drag/drop
and tree interaction. W8 has not reset crash recovery, realistic benchmarks,
or packaging.

## 10. Technical debt and smallest next step

Project-scoped revision is intentionally coarse for the local single-user V1;
reconsider finer versions only if real multi-user concurrency appears. Effective
hiding through a deleted ancestor is an authoritative query/action rule, so W7
Tree/Search must reuse it instead of filtering only an Item's own state. The
smallest next step is separately authorizing W6 and closing stable Open/Edit
Refresh before any W7 UI work.
