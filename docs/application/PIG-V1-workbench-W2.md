# PIG V1 Workbench W2 实施记录 / Workbench W2 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-22 / Date: 2026-09-22
- 决策：D26-A、D27-B、D28-A、D29-A / Decisions: D26-A, D27-B, D28-A, D29-A
- 后续状态：W7 已完成；W8 未授权 / Later status: W7 complete; W8 not authorized

## 中文实施记录

### 目标与边界

W2 实现一个真实但有限的闭环：把用户授权的绝对 File/Folder Path 复制为 Project
内不可变 Original Snapshot，落库逐项结果，创建 Snapshot-backed Source 与 Root
Node，并可重新校验 Project-owned Bytes。

W2 不调用 Folder/ZIP/Email/7z/RAR Handler，不发现 Folder Child Node，不创建
Workspace Item，不物化 Working Artifact，也不修改桌面 UI。

### 数据流

```text
ImportProjectItemsRequest
  -> validate Project/model/idempotency/policy
  -> create ImportSession + ordered ImportSessionItem rows
  -> preflight each absolute input
  -> stream into .staging and calculate SHA-256
  -> verify the input did not change
  -> atomically publish originals/<snapshot-id>
  -> persist Snapshot/Artifact/SnapshotEntry tree
  -> create Source + root Node
  -> bind root entry and root file Artifact when applicable
  -> item CAPTURED or FAILED
  -> session INSPECTING or FAILED
  -> typed partial-success result
```

### 持久化与不变量

- 新增 `ImportSessionItem` 与 `OriginalSnapshotEntry`；
- `Source` 改为由唯一 `snapshot_id` 支撑；
- File Entry 必须绑定同 Snapshot 的 Artifact，Folder Entry 不得绑定 Artifact；
- 每个 Snapshot 只有一个 Root Entry，Parent 必须是同 Snapshot Folder；
- Artifact Bytes、Entry Identity/Parent/Ordinal 和 Source-Snapshot Identity 不可改写；
- Root Entry 与 Root File Artifact 的 Source Node Binding 只允许赋值一次；
- 同 Project 同时最多一个 `QUEUED/SNAPSHOTTING/INSPECTING` Session；
- `0002_snapshot_import` 更新 Event/Error 枚举并保留 Append-only Event Trigger。

### 状态与事件

顶层 Item 使用 `PENDING -> CAPTURING -> CAPTURED | FAILED | INTERRUPTED`。
Snapshot 使用 `COPYING -> VERIFYING -> READY`，失败时进入明确终态。成功捕获后
Session 保持 `INSPECTING`，等待 W3；全部失败时进入 `FAILED`。

写入的关键 Event 包括 `IMPORT_REQUESTED`、`IMPORT_STARTED`、
`SNAPSHOT_COPY_STARTED`、`SNAPSHOT_READY`、`SNAPSHOT_INTEGRITY_FAILED`、
`SOURCE_REGISTERED`、`NODE_DISCOVERED` 和 `IMPORT_SNAPSHOT_CAPTURE_FINISHED`。
显式重新校验还记录 Snapshot/Source Verification Event。

### 安全边界

- 输入必须是绝对普通 File/Folder，且不得与 Project Workspace 重叠；
- 不跟随 Symlink 或 Windows Reparse Point；Folder 中任意此类 Entry 使整个 Snapshot
  失败；
- 集中限制 Input Count、Entry Count、Single File Size、Session Total Size 和 IO
  Chunk；
- 复制前后比较文件身份、大小和修改时间，变化即拒绝；
- Physical Path 只使用受校验的生成 ID；
- Staging 只在完整捕获后原子 Publish；DB Commit 失败会撤销已 Publish 目录；
- 外部输入只读，成功后删除外部输入不影响 Snapshot Verification。

### 测试与验收

自动化覆盖 File/Folder Snapshot、嵌套目录层级、Partial Success、Missing Input、
幂等重放、Resource Limit Rollback、外部输入删除后校验、Project Copy Missing、
Windows 文件身份采样差异、Migration/Metadata 一致性、Downgrade Guard 和数据库
不变量。Symlink Case 在宿主允许创建 Symlink 时运行，否则明确 Skip。

最终全量结果：`86 passed, 95 skipped`。其中一个 W2 Symlink Case 因当前 Windows
宿主不允许创建测试 Symlink 而 Skip；其余 Skip 为 ADR-010 隔离的历史证据导向测试
和同类宿主能力限制。

### 未闭环边界

复制期间变化、Unreadable 和 Interrupt 的生产逻辑已建模，但真实 OS 级竞态/权限/
进程中断 Fault Injection 将在 W8 再做系统级验证。W3 才会检查 Folder/ZIP 结构并
继续同一 Session；因此 W2 的成功 Session 有意停留在 `INSPECTING`，Project 有意
停留在 `IMPORTING`。

## English implementation record

## Goal and boundary

W2 implements one real but bounded loop: copy user-authorized absolute file or
folder paths into immutable Project-owned snapshots, persist per-item results,
create a snapshot-backed Source and root Node, and reverify Project-owned bytes.

W2 does not invoke Folder/ZIP/email/7z/RAR handlers, discover child Nodes,
create Workspace Items, materialize Working Artifacts, or change the desktop UI.

## Data flow

```text
ImportProjectItemsRequest
  -> validate Project/model/idempotency/policy
  -> create ImportSession + ordered ImportSessionItem rows
  -> preflight each absolute input
  -> stream into .staging and calculate SHA-256
  -> verify the input did not change
  -> atomically publish originals/<snapshot-id>
  -> persist Snapshot/Artifact/SnapshotEntry tree
  -> create Source + root Node
  -> bind root entry and root file Artifact when applicable
  -> item CAPTURED or FAILED
  -> session INSPECTING or FAILED
  -> typed partial-success result
```

## Persistence and invariants

- `ImportSessionItem` and `OriginalSnapshotEntry` are added.
- `Source` is backed by one unique `snapshot_id`.
- A file Entry references an Artifact in the same snapshot; a folder Entry has
  no Artifact.
- Each snapshot has exactly one root Entry, and a parent is a folder in that
  same snapshot.
- Artifact bytes, Entry identity/parent/order, and Source-snapshot identity are
  immutable.
- Root Entry and root-file Artifact Source Node bindings are set-once.
- A Project has at most one `QUEUED`, `SNAPSHOTTING`, or `INSPECTING` session.
- `0002_snapshot_import` updates Event/Error vocabularies and preserves the
  append-only Event triggers.

## State and events

Top-level items follow `PENDING -> CAPTURING -> CAPTURED | FAILED |
INTERRUPTED`. Snapshots follow `COPYING -> VERIFYING -> READY`, with explicit
failure outcomes. A successful W2 capture leaves the session at `INSPECTING`
for W3; all-item failure ends at `FAILED`.

Key Events include `IMPORT_REQUESTED`, `IMPORT_STARTED`,
`SNAPSHOT_COPY_STARTED`, `SNAPSHOT_READY`, `SNAPSHOT_INTEGRITY_FAILED`,
`SOURCE_REGISTERED`, `NODE_DISCOVERED`, and
`IMPORT_SNAPSHOT_CAPTURE_FINISHED`. Explicit reverification also emits Snapshot
and Source verification Events.

## Security boundary

- Inputs are absolute regular files/folders and cannot overlap the Project.
- Symlinks and Windows reparse points are not followed; any such folder member
  rejects the complete snapshot.
- Central policy bounds input count, entry count, single-file size, session
  total size, and IO chunk size.
- File identity, size, and modification time are compared before and after copy.
- Physical paths contain validated generated identities only.
- Staging publishes atomically only after complete capture; a failed database
  commit removes the published directory.
- External inputs are only read; deleting one after success does not affect
  snapshot verification.

## Tests and acceptance

Automated coverage includes file/folder snapshots, nested folder hierarchy,
partial success, missing input, idempotent replay, resource-limit rollback,
verification after external deletion, missing Project copies, Windows file
identity sampling, migration/metadata parity, downgrade guards, and database
invariants. The symlink case runs where the host permits test symlink creation
and is otherwise explicitly skipped.

Final full-suite result: `86 passed, 95 skipped`. One W2 symlink case is skipped
because this Windows host does not permit creation of the test symlink; the
other skips are evidence-era tests quarantined by ADR-010 and equivalent host
capability limits.

## Open boundaries

Copy-time change, unreadable-input, and interruption behavior is modeled and
implemented, while OS-level race/permission/process fault injection remains a
W8 system-verification concern. W3 inspects Folder/ZIP structures and continues
the same session. W2 therefore intentionally leaves successful sessions at
`INSPECTING` and the Project at `IMPORTING`.
