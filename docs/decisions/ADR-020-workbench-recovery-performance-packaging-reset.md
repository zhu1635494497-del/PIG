# ADR-020：Workbench W8 Recovery、Performance 与 Packaging 重置 / Workbench W8 Recovery, Performance, and Packaging Reset

- 状态：已接受并实施；等待 W8 人工桌面验收 / Status: Accepted and implemented; W8 manual desktop acceptance pending
- 提案日期：2026-09-23 / Proposal date: 2026-09-23
- 接受日期：2026-09-24 / Accepted: 2026-09-24
- 范围：Workbench Milestone W8 / Scope: Workbench Milestone W8
- 历史参考：ADR-008，不作为当前实现授权 / Historical reference: ADR-008, not current implementation authority

## 中文提案

### 背景

W7.2 源码桌面人工验收已经通过。旧 ADR-008 Recovery 只识别 Evidence-era 的
`artifacts`、`manifests` 和 `.open-handoff`，不能安全处理当前 Workbench 的
`originals`、`working`、`working-versions`、`.inspection`、materialization staging
和 import-undo staging。尤其是 Import Undo 在文件系统移动与 SQLite 提交之间崩溃时，
同一暂存目录可能需要“恢复原位”而不是统一隔离。旧 Recovery 不得直接重新启用。

### 实施前影响

- **Domain**：候选 `RecoveryRun`、`RecoveryItem`、操作级 Staging Manifest；不改变
  Original/Source/Workspace 的所有权边界。
- **Flow**：Project Open 只读扫描，必要时进入 Recovery-required；用户确认后按操作
  类型恢复、隔离或清理可再生 Cache，再验证 Project。
- **State**：Recovery 当前状态与 Append-only Event 分离；已知 Working Content
  Status 仍由确定性观察更新。
- **Lineage**：Source/Origin Binding 不重写；Recovery 只恢复物理一致性和中断状态。
- **Log**：扫描、确认、逐项结果和终态均结构化记录；Debug Log 保存异常栈。
- **Permission**：扫描是 Read；Restore/Quarantine/Cleanup 是确认后的 Project Write；
  已知 Modified Working File 不自动覆盖或移动。
- **Tool**：候选 typed Actions 为 `inspect_project_recovery` 和 `recover_project`，当前
  不作为公共 Tool 暴露。
- **AI / Automation**：不使用 AI，不增加自动重试、调度器或事件驱动 Automation。
- **UI**：只增加 Recovery-required Banner/Dialog 和明确 Recover Action，不增加新
  Dashboard 或管理页面。

### D69：Project Open Recovery 入口

**方案 A（推荐）**：每次打开 Project 执行只读快速扫描。无异常时不打扰；发现未完成
状态或残留时，Project 进入 Recovery-required 只读模式，禁止写 Action，并由用户明确
确认恢复。扫描本身不得移动或删除字节。

**方案 B**：只提供手工 Recovery 菜单，Project Open 不扫描。实现更少，但用户可能在
未知残留上继续写入，使恢复边界进一步复杂化。

### D70：Recovery 持久化模型

**方案 A（推荐）**：新增 `recovery_runs` 和 `recovery_items`，通过 Alembic `0008`
持久化计划、逐项 Action、原位置、隔离位置、Size/SHA-256、结果和 Error。Run 使用
`DETECTED -> AWAITING_CONFIRMATION -> RUNNING -> SUCCESS/PARTIAL_SUCCESS/FAILED`；
Item 使用 `DISCOVERED -> PLANNED -> RESTORED/QUARANTINED/
REMOVED_REPRODUCIBLE/UNCHANGED/FAILED`。Event 保留历史但不替代当前 Recovery 状态。

**方案 B**：复用 `ProcessingJob`、`ProcessingEvent` 和 `report.json`，不增加表。变更
较少，但 Workbench 文件恢复不是 Node Processing，逐项当前状态只能埋在 Event/JSON，
不利于查询、重试和 UI 解释。

### D71：残留分类策略

**方案 A（推荐）**：一个 Scanner 加操作类型专属 Planner。至少分别处理：

- Snapshot Import staging；
- Inspection Cache；
- Materialization staging/published Working；
- Working version rotation/rollback；
- Import Undo staging；
- 未登记的 `originals/working/working-versions` 对象。

Planner 根据数据库事实决定 Restore、Quarantine、删除可再生 Cache、保持不动或要求
人工处理。Import Undo 若数据库尚未 `PURGED` 必须恢复原位；已提交 `PURGED` 后才可
隔离残留。任何无法证明类型的字节默认进入可逆 Quarantine。

**方案 B**：所有未登记路径统一移动到 Quarantine。实现简单，但可能把尚未提交的
Import Undo 原字节移走，导致一个本可恢复的 Project 被进一步破坏。

### D72：跨 SQLite/Filesystem 操作证据

**方案 A（推荐）**：为 Snapshot、Materialization、Version Rotation/Rollback 和 Import
Undo 统一增加版本化 Staging Manifest，记录 Operation ID、类型、Project ID、源/目标
Storage Key、预期 Hash/Size 和 Publish Phase，并在关键写入后 `fsync`。核心 Recovery
结果仍落库；Manifest 只作为跨介质崩溃证据，不替代领域表。

**方案 B**：不增加 Manifest，只根据目录名和数据库当前状态推断。改动较少，但对
部分移动完成、SQLite 未提交等窗口不能给出足够确定的逆操作依据。

### D73：Working File 保护

**方案 A（推荐）**：Recovery 永不自动覆盖、删除或隔离数据库已知的 Working File
和版本槽。Hash 变化按现有 Refresh 规则记录为 `MODIFIED`；`MISSING/UNREADABLE` 保持
显式状态。只有未登记额外对象可隔离；恢复 Original/Previous 必须由用户另行确认。

**方案 B**：若 Working File 与 Current Checkpoint 不同，自动用 Checkpoint 修复。
这会丢失用户刚保存但尚未被 PIG 刷新的工作，不符合 Workbench 首要价值。

### D74：Performance Qualification

**方案 A（推荐）**：建立可重复的参考基线而非跨机器硬 SLA。Fixture 至少覆盖 10,000
Workspace Item Tree/Search、2,000 文件 Snapshot Import、10,000-entry ZIP Inspect、
大文件 Materialize/Refresh Hash、Folder/ZIP Export；记录三次运行中位数、吞吐、Peak
RSS、SQLite 大小和 UI Busy 时间。本次形成首个 Workbench Baseline，后续同参考环境
超过 25% 才作为回归门。

**方案 B**：现在定义所有机器通用的绝对秒数 SLA。看似明确，但磁盘、杀毒软件和
Host 差异会让门槛不可重复，也容易驱动不必要的架构升级。

### D75：执行模型

**方案 A（推荐）**：保持当前单后台 Action 边界；Application Use Case 同步且确定，
UI 串行化冲突 Action。W8 不引入持久异步队列、Pause/Resume、Broker 或 Worker Service。

**方案 B**：在 W8 引入可取消的持久任务系统。能力更强，但会扩大状态机、Recovery
和 Packaging 范围，当前没有业务必要。

### D76：Windows Package 形态

**方案 A（推荐）**：继续 PyInstaller `onedir`、`console=False`、`upx=False` 的内部
验收包，重新绑定当前 `0001_workbench..0008` Migration、Qt 和格式依赖。暂不制作
Installer/OneFile/Auto-update，也不宣称 macOS/Linux 已验证。

**方案 B**：改用 PyInstaller `onefile`。分发文件更少，但启动时自解压、杀毒误报、
动态依赖与崩溃残留更难诊断，不适合作为本次可靠性基线。

### D77：7-Zip 与发布证据

**方案 A（推荐）**：不捆绑 7-Zip；在 Windows 标准安装位置自动发现受控 `7z.exe`，
保留 `--seven-zip` 显式覆盖，并继续记录 Backend Version/SHA-256。构建同时产生精确
依赖锁、CycloneDX SBOM、`pip-audit` 结果、第三方 Notice、文件清单、Build Hash 和
双语人工验收清单。外部分发继续等待人工许可证复核和 Code Signing。

**方案 B**：把 7-Zip 二进制随 PIG 打包。RAR 开箱体验更直接，但改变许可证、更新、
供应链和签名边界，与此前“使用用户已安装 7-Zip”的产品选择冲突。

### 推荐组合

推荐：`D69-A、D70-A、D71-A、D72-A、D73-A、D74-A、D75-A、D76-A、D77-A`。

产品负责人已于 2026-09-24 批准推荐组合。实现记录见
`docs/application/PIG-V1-workbench-W8.md`；外部分发仍受人工许可证复核、代码签名、
干净 Windows 主机和人工桌面验收门约束。

## English proposal

## Context

W7.2 source-desktop manual acceptance passed. The historical ADR-008 Recovery
recognizes only Evidence-era `artifacts`, `manifests`, and `.open-handoff`. It
cannot safely reconcile current Workbench `originals`, `working`,
`working-versions`, `.inspection`, materialization staging, or import-undo
staging. In particular, an Import Undo crash between filesystem moves and the
SQLite commit may require restoration in place rather than generic quarantine.
The old Recovery must not simply be re-enabled.

## Pre-implementation impact

- **Domain**: candidate `RecoveryRun`, `RecoveryItem`, and operation-scoped
  Staging Manifest; Original/Source/Workspace ownership remains unchanged.
- **Flow**: read-only scan on Project Open, Recovery-required mode when needed,
  then confirmed type-specific restore, quarantine, or reproducible-cache
  cleanup followed by verification.
- **State**: current Recovery state remains separate from append-only Events;
  deterministic observation continues to own Working Content Status.
- **Lineage**: Source and Origin bindings are never rewritten; Recovery restores
  physical consistency and interrupted state only.
- **Log**: scan, confirmation, per-item outcomes, and terminal result are
  structured Events; exception stacks remain Debug Logs.
- **Permission**: scan is Read; restore/quarantine/cleanup is a confirmed Project
  Write. Known modified Working Files are never automatically replaced or moved.
- **Tool**: candidate typed Actions are `inspect_project_recovery` and
  `recover_project`, not public Tools yet.
- **AI / Automation**: no AI, automatic retry, scheduler, or event-driven
  Automation is added.
- **UI**: only a Recovery-required banner/dialog and explicit Recover Action;
  no dashboard or administration page.

## D69 - Project Open Recovery entry

**Option A (recommended)**: run a fast read-only scan whenever a Project opens.
Stay silent when healthy. If incomplete state or residue exists, open in a
Recovery-required read-only mode, block writes, and require explicit user
confirmation before Recovery moves or removes any bytes.

**Option B**: expose only a manual Recovery menu. This is smaller but permits
users to continue writing over unknown residue.

## D70 - Recovery persistence model

**Option A (recommended)**: add `recovery_runs` and `recovery_items` through
Alembic `0008`, persisting the plan, per-item action, original/quarantine keys,
size/hash, outcome, and error. Run states are `DETECTED ->
AWAITING_CONFIRMATION -> RUNNING -> SUCCESS/PARTIAL_SUCCESS/FAILED`; Item states
are `DISCOVERED -> PLANNED -> RESTORED/QUARANTINED/REMOVED_REPRODUCIBLE/
UNCHANGED/FAILED`. Events retain history but do not replace current state.

**Option B**: reuse `ProcessingJob`, `ProcessingEvent`, and `report.json` without
new tables. This hides per-item current state in Events/JSON even though
Workbench storage recovery is not Node Processing.

## D71 - Residue classification

**Option A (recommended)**: use one Scanner with operation-specific Planners for
Snapshot Import, Inspection Cache, Materialization, Working version rotation,
Import Undo, and unregistered `originals/working/working-versions` objects. The
Planner chooses restore, quarantine, reproducible-cache removal, unchanged, or
manual review from database facts. Uncommitted Import Undo bytes are restored
when the database is not `PURGED`; only committed purge residue is quarantined.
Unknown bytes default to reversible quarantine.

**Option B**: move every unregistered path to quarantine. This can move live
Import Undo bytes away from a Project that was still recoverable in place.

## D72 - Cross-media operation evidence

**Option A (recommended)**: add a versioned Staging Manifest to Snapshot,
Materialization, Version Rotation/Rollback, and Import Undo. It records operation
identity/type, Project, source/target keys, expected size/hash, and publish phase,
with `fsync` at critical transitions. Core Recovery outcome remains relational;
the Manifest is crash evidence rather than a domain-table substitute.

**Option B**: infer only from directory names and current database rows. This is
smaller but cannot deterministically reverse every partial-move/pre-commit
window.

## D73 - Working File protection

**Option A (recommended)**: Recovery never automatically overwrites, deletes, or
quarantines a database-known Working File or version slot. A changed hash follows
normal Refresh into `MODIFIED`; missing/unreadable remains explicit. Only
unregistered extra objects may be quarantined. Restoring Original/Previous
requires a separate user confirmation.

**Option B**: automatically restore Current Checkpoint when Working bytes differ.
This can erase a recent save that PIG had not yet observed.

## D74 - Performance qualification

**Option A (recommended)**: establish a reproducible reference baseline rather
than a cross-machine hard SLA. Cover at least a 10,000-item Tree/Search, 2,000
file Snapshot Import, 10,000-entry ZIP inspection, large-file materialize/refresh
hashing, and Folder/ZIP export. Record three-run median, throughput, peak RSS,
SQLite size, and UI busy duration. This becomes the first Workbench baseline;
later runs on the same reference environment fail at more than 25% regression.

**Option B**: define universal absolute timing SLAs now. Disk, antivirus, and
host variation make such gates non-reproducible and may drive premature
architecture changes.

## D75 - Execution model

**Option A (recommended)**: retain one background desktop Action. Application
use cases stay synchronous and deterministic, and UI serializes conflicting
Actions. W8 adds no persistent async queue, pause/resume, broker, or worker
service.

**Option B**: add a cancellable persistent task system in W8, substantially
expanding state, Recovery, and Packaging without a current business need.

## D76 - Windows package form

**Option A (recommended)**: retain PyInstaller `onedir`, `console=False`, and
`upx=False` for an internal acceptance build, now bundling the current
`0001_workbench..0008` migrations, Qt, and format dependencies. No installer,
OneFile, auto-update, or macOS/Linux verification is claimed.

**Option B**: use PyInstaller `onefile`. It has fewer distribution files but
self-extraction, antivirus false positives, dynamic dependency behavior, and
crash residue are harder to diagnose.

## D77 - 7-Zip and release evidence

**Option A (recommended)**: do not bundle 7-Zip. Auto-discover controlled
`7z.exe` in standard Windows installation locations, retain explicit
`--seven-zip` override, and persist backend version/SHA-256. Produce an exact
dependency lock, CycloneDX SBOM, `pip-audit` result, third-party notices, file
inventory, build hash, and bilingual manual checklist. External distribution
remains blocked on human license review and code signing.

**Option B**: bundle a 7-Zip binary with PIG. This improves immediate RAR use but
changes licensing, update, supply-chain, and signing boundaries and conflicts
with the prior installed-7-Zip product choice.

## Recommended combination

Recommended: `D69-A, D70-A, D71-A, D72-A, D73-A, D74-A, D75-A, D76-A, D77-A`.

The owner approved the recommended combination on 2026-09-24. See
`docs/application/PIG-V1-workbench-W8.md` for implementation evidence. External
distribution remains gated by human license review, code signing, clean-Windows
host qualification, and manual desktop acceptance.
