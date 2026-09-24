# PIG V1 Workbench W4 实施记录 / Workbench W4 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-22 / Date: 2026-09-22
- 决策：`ADR-014` / Decision: `ADR-014`
- 后续状态：W7 已完成；W8 未授权 / Later status: W7 complete; W8 not authorized

## 中文实施记录

### 1. 本次修改了什么

将 EML、MSG、7z 和 RAR 接入 Workbench-native Structure Registry，与 ZIP 共用主动
Inspect、受控嵌套 Cache 和单目标 Lazy Materialization。新增 `0004_complex_containers`
Migration，并保留历史 Evidence Processor 隔离。

### 2. 涉及的领域对象

- `SourceEntryLocator`：新增四种格式 Locator，并统一 Container Member 字段；
- `ProcessingAttempt`：新增 Backend Name/Version/SHA-256；
- `Node`、`NodeRelationship`、`NodeMetadata`：保存邮件附件、嵌套消息、Archive 目录及
  Email Header Metadata；
- `WorkspaceItem`、`WorkingArtifact`：继续保持完整结构投影与单目标物化语义。

### 3. 完整数据流

```text
verified Original Snapshot
-> deterministic format detection
-> resolve Workbench Handler
-> persist Container Attempt and backend identity
-> inspect children
-> persist direct Relationship + typed Locator
-> materialize nested Container into bounded operation cache
-> continue iterative queue
-> project Source Structure into virtual Workspace Tree

explicit terminal materialization
-> replay Locator chain from Original
-> resolve each parent Handler through Locator kind
-> publish one stable Working Artifact
```

### 4. 状态变化

- Container Node：`DISCOVERED -> PENDING -> PROCESSING -> terminal result`；
- Attempt：`QUEUED -> RUNNING -> COMPLETED | FAILED`；
- Parent Container 在 Child 有 Blocked 结果时汇总为 `PARTIAL_SUCCESS`；
- Terminal Workspace Item 在未选择时保持 `VIRTUAL`。

### 5. Event 与 Log

新增实际使用的 Attempt Queued/Started/Finished/Failed 记录，并让 Node/Container Event
绑定 `attempt_id`。Backend Identity 写入 Attempt；RAR Event 不暴露 Executable Path。
Format/Dependency/Password/Limit/Security 失败均成为持久业务结果。

### 6. Tool 或 Action

未新增公共 Tool。继续复用 typed `inspect_import_session` 和
`materialize_workspace_item` Application Action；调用方不需要知道具体格式 Backend。

### 7. 权限与安全

- 每次检查和物化前重新验证 Project-owned Original；
- 所有输出经过生成标识 Cache/Working 路径与大小限制；
- Archive 继续执行 Traversal、Link、Duplicate、Count、Depth、Size、Ratio Policy；
- RAR 继续要求显式绝对 7-Zip Path、版本范围与 Executable Hash；
- 不收集密码、不加载远程附件、不修改 Original、不回写 Container。

### 8. 测试覆盖

覆盖真实 `ZIP -> EML -> ZIP -> terminal`、受控 `MSG -> 7z -> terminal`、重复附件名、
RAR Backend Identity、7-Zip Missing/Rejected、Malformed MSG、Password-protected 7z、
Member Limit、Lazy Terminal、Recipe Replay、Cache Cleanup、Migration 和 W2/W3 回归。

最终全量结果为 `105 passed, 95 skipped`。其中 93 个 Skip 是 ADR-010 隔离的历史
Evidence/UI 测试，2 个 Skip 是当前 Windows Host 不允许创建测试 Symbolic Link；一条
Warning 来自刻意构造重复 ZIP Member Name 的测试。

### 9. 尚未闭环边界

Workspace Create/Move/Add/Soft Delete/Restore 属于 W5；Controlled Open 与 External Edit
Refresh 属于 W6；Workbench UI 属于 W7；Crash Recovery、真实性能与 Packaging 属于 W8。
真实 RAR/系统 7-Zip 兼容性仍需在 W8 的目标平台环境验收。

### 10. 技术债务

Workbench Adapter 当前复用已验证的 EML/MSG/7z/RAR 格式 Handler，因此一次目标物化
可能重新执行一次 Inspection。它保持边界正确但不是最终性能形态，应在 W8 Benchmark
证明需要后再优化。同步本地 Queue 与单 Project SQLite 仍符合当前范围。

## English implementation record

## 1. What changed

Connected EML, MSG, 7z, and RAR to the Workbench-native Structure Registry. They
now share eager inspection, bounded nested cache, and one-target lazy
materialization with ZIP. Added migration `0004_complex_containers` while the
historical Evidence processor remains isolated.

## 2. Domain objects

- `SourceEntryLocator` adds four format-specific kinds and common structured
  Container-member fields.
- `ProcessingAttempt` adds backend name/version/SHA-256.
- `Node`, `NodeRelationship`, and `NodeMetadata` persist attachments, embedded
  messages, archive directories, and email header metadata.
- `WorkspaceItem` and `WorkingArtifact` retain full structure projection and
  one-target materialization semantics.

## 3. Complete data flow

```text
verified Original Snapshot
-> deterministic format detection
-> resolve Workbench Handler
-> persist Container Attempt and backend identity
-> inspect children
-> persist direct Relationship + typed Locator
-> materialize nested Container into bounded operation cache
-> continue iterative queue
-> project Source Structure into virtual Workspace Tree

explicit terminal materialization
-> replay Locator chain from Original
-> resolve each parent Handler through Locator kind
-> publish one stable Working Artifact
```

## 4. State changes

- Container Node: `DISCOVERED -> PENDING -> PROCESSING -> terminal result`.
- Attempt: `QUEUED -> RUNNING -> COMPLETED | FAILED`.
- A parent Container rolls up to `PARTIAL_SUCCESS` when a child is blocked.
- An unselected terminal Workspace Item remains `VIRTUAL`.

## 5. Events and logs

Attempt Queued/Started/Finished/Failed Events are now active, and Node/Container
Events link to `attempt_id`. Backend identity is persisted on the Attempt. RAR
Events never reveal the executable path. Format, dependency, password, limit,
and security failures are durable business outcomes.

## 6. Tool or action impact

No public Tool was added. The typed `inspect_import_session` and
`materialize_workspace_item` Application actions remain the caller contract;
callers do not know format-specific backends.

## 7. Permission and safety

- Project-owned Original bytes are reverified before inspection/materialization.
- Generated cache/working paths and bounded output apply to every format.
- Archive traversal, link, duplicate, count, depth, size, and ratio policy
  remains centralized.
- RAR still requires an explicit absolute 7-Zip path, accepted version, and
  executable hash.
- PIG collects no passwords, loads no remote attachment, modifies no Original,
  and writes back no Container.

## 8. Tests

Coverage includes real `ZIP -> EML -> ZIP -> terminal`, controlled
`MSG -> 7z -> terminal`, duplicate attachment names, RAR backend identity,
missing/rejected 7-Zip, malformed MSG, password-protected 7z, member limits,
lazy terminals, recipe replay, cache cleanup, migrations, and W2/W3 regression.

The final full-suite result is `105 passed, 95 skipped`. Ninety-three skips are
historical Evidence/UI tests quarantined by ADR-010, and two are symlink cases
that this Windows host cannot create. One warning comes from the intentionally
duplicated ZIP member-name fixture.

## 9. Open boundaries

Workspace create/move/add/soft-delete/restore belongs to W5; controlled open and
external-edit refresh to W6; Workbench UI to W7; crash recovery, realistic
performance, and packaging to W8. Real RAR/system-7-Zip compatibility still
requires target-platform acceptance during W8.

## 10. Technical debt

The Workbench adapter currently reuses the vetted EML/MSG/7z/RAR format Handler,
so one target materialization may repeat one inspection. This preserves the
correct boundary but is not necessarily the final performance form; optimize it
only if W8 benchmarks justify the change. The synchronous local queue and
single-Project SQLite model remain appropriate for current scope.
