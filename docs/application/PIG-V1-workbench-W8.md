# PIG V1 Workbench W8 实现记录 / Implementation Record

- 状态：自动实现、当前主机机器验收与源码桌面人工验收通过；发布资格转入 W9 / Status: automated implementation, current-host machine acceptance, and source-desktop manual acceptance passed; release qualification moves to W9
- 日期：2026-09-24 / Date: 2026-09-24
- 决策：`ADR-020`，D69-A 至 D77-A / Decisions: `ADR-020`, D69-A through D77-A
- Migration Head：`0008_workbench_recovery`

## 中文实现记录

### 1. 完成了什么

- Project Open 执行只读 Recovery Scan；发现残留后进入 Recovery-required 只读模式，
  写入、打开、导出和树修改 Action 均被禁用，查询仍可用。
- 新增 `RecoveryRun`、`RecoveryItem`、Repository、SQLAlchemy Mapping 和 Alembic
  `0008_workbench_recovery`。
- Snapshot Import、Working Materialization/Restore、Working Version 与 Import Undo 使用
  Versioned Staging Manifest 保存跨 SQLite/Filesystem 的崩溃证据。
- Operation-aware Planner 区分 Restore、Quarantine、Remove Reproducible Cache、Remove
  Manifest 与 Unchanged；无法证明身份的字节默认可逆隔离。
- 已知 Working 和版本槽永不由 Recovery 自动覆盖、删除或隔离；用户刚保存但尚未刷新
  的 Working 字节得到保护。
- 正常 `INSPECTING` 导入会话不是中断；只有处于写入临界区的 `SNAPSHOTTING` 会被
  Recovery 转为 `INTERRUPTED`。
- 生成真实规模三轮中位数基线、精确 Release Lock、CycloneDX SBOM、`pip-audit`、
  Third-party Notices、Windows 文件清单和 Build Hash。
- 重建 PyInstaller `onedir`、`console=False`、`upx=False` 内部验收包；包内闭环使用
  当前 Workbench Contract，不再调用历史 Evidence Contract。

### 2. 涉及的领域对象

- `Project`：Recovery 扫描和写入隔离边界。
- `RecoveryRun`：一次确认恢复的当前状态、计数、Actor、Correlation 和时间。
- `RecoveryItem`：逐项 Kind、Action、原 Storage Key、隔离 Key、结果与错误。
- `ImportSession`、`ImportSessionItem`、`OriginalSnapshot`：中断写状态被显式对账。
- `WorkspaceItem`、`WorkingArtifact`、`WorkingRevision`：只读事实用于保护已知字节；
  Recovery 不改 Source Origin 或 Workspace Placement。
- `ProcessingEvent`：保存 Recovery Started/Finished/Failed 和 Orphan Quarantined 历史。
- `StagingOperationManifest`：跨介质临时证据，不是新的业务事实来源。

### 3. 用户操作 -> 后端处理 -> 数据落库 -> 输出结果

```text
打开 Project
  -> Application 读取 SQLite 已知 Original/Working/Version Key
  -> Filesystem Scanner 只读检查 Staging/Manifest/未登记对象
  -> 无候选：正常进入 Workbench，不写数据库
  -> 有候选：显示 Recovery-required，Project 保持只读
  -> 用户确认 Recover
  -> 重新扫描并校验 Inspection Token
  -> 创建 RecoveryRun/RecoveryItem
  -> 按 Operation Type Restore/Quarantine/Cleanup/Keep
  -> 每项结果和 Event 同一 UoW 落库
  -> 再扫描确认剩余候选
  -> 输出 Success/Partial Success/Failed 并恢复或保持只读模式
```

### 4. 新增或修改的状态 / Event / Log

- Run：`DETECTED -> AWAITING_CONFIRMATION -> RUNNING -> SUCCESS | PARTIAL_SUCCESS | FAILED`。
- Item：`DISCOVERED -> PLANNED -> RESTORED | QUARANTINED |
  REMOVED_REPRODUCIBLE | UNCHANGED | FAILED`。
- 上一次进程终止遗留的非终态 RecoveryRun/Item，会在下一次确认恢复时显式落为
  `FAILED`/`RECOVERY_INTERRUPTED`，不会永久伪装成 Running。
- Event：`RECOVERY_STARTED`、`RECOVERY_FINISHED`、`RECOVERY_FAILED`、
  `ORPHAN_QUARANTINED`；技术异常继续进入 Rotating Debug Log。

### 5. 是否形成新的 Tool / Action

形成两个 typed in-process Action：`inspect_project_recovery` 和
`recover_workbench_project`。它们可被 Desktop 复用，但当前不是公共 API、MCP Tool、
Workflow 或 Automation。

### 6. 安全和权限影响

- Open Scan 完全只读；没有确认不得移动、删除或修复任何字节。
- Recover 只允许 Project Root 下经过解析和边界验证的 Storage Key。
- 不认识的对象进入 Project 内可逆 Quarantine；可再生 Cache 才允许删除。
- 恢复计划执行前重新计算 Token，防止扫描后状态变化导致 TOCTOU 误操作。
- Original、已登记 Working 和 Working Version 保持保护边界；7-Zip 不捆绑，只发现
  Windows 标准安装位置或接受显式 `--seven-zip` 覆盖，并记录 Version/SHA-256。

### 7. 测试覆盖

- Recovery：健康扫描不写库、残留阻断写、确认清理、未登记 Working 可逆隔离、已知
  Modified Working 不变、Import Undo 未提交恢复原位、过期 Token 拒绝、物化中断对账。
- UI：Open 后后台扫描、Recovery Banner/只读控件、确认恢复和恢复后 Reload。
- Migration：从空库升级至 `0008`，Recovery 表与约束存在。
- Package Flow：创建项目、文件夹导入、5 项结构树、物化并修改、保结构目录导出、
  Recovery 和 Reload；Runtime Smoke 与 Acceptance Smoke 均返回 0。
- 最终全量回归：`146 passed, 95 skipped`；95 个 Skip 为 ADR-010 明确隔离的历史
  Evidence-era 合同或当前主机不允许创建的 2 个 Symlink 场景。唯一 Warning 来自
  刻意构造的重复 ZIP Entry。
- D74 正式基线：每场景 3 次取中位数；参考主机上 10k Tree 5.734 s、10k Search
  5.775 s、2k Snapshot 10.904 s、10k ZIP Inspect 108.339 s、64 MiB Materialize
  0.805 s、Refresh Hash 0.717 s、500 文件夹导出 71.074 s、ZIP 导出 21.205 s。
- Release Evidence：40 个 Runtime 组件、当前已知漏洞 0、最终 onedir 922 文件、
  113,090,775 Bytes、捆绑 `7z.exe` 数量 0；打包内 RecoveryItem 记录 18 Bytes 和
  64 位 SHA-256。

### 8. 当前尚未闭环的边界

- W8 源码桌面人工验收已由用户确认通过；最终 Package 人工验收尚未在干净 Windows
  主机执行。
- 尚未在干净 Windows 主机验证解压运行、Host Application 编辑和标准位置 7-Zip RAR。
- 第三方许可证仍需人工复核；Code Signing 证书/主体/时间戳策略未决定。因此当前包
  只能用于内部验收，不能宣称可外部分发。
- 10k ZIP Inspect 和 500 文件 Folder Export 已有可重复参考值，但 W8 不据此引入
  Read Index、异步队列或大规模架构重构。
- 不实现 Installer、OneFile、Auto-update、macOS/Linux 发布、AI、Agent、MCP、Watcher
  或持久任务系统。

### 9. 下一步最小建议

进入 W9 Release Qualification 决策门。先批准 D78–D86，再执行最终包、干净 Windows
主机、License、Signing 和真实 RAR 验收；W9 不提前进入 V2 Content Index。

## English implementation record

### 1. What was completed

- Project Open performs a read-only recovery scan. Residue activates a
  Recovery-required read-only mode: writes, open, export, and tree mutation are
  disabled while queries remain available.
- Added `RecoveryRun`, `RecoveryItem`, repository, SQLAlchemy mapping, and
  Alembic `0008_workbench_recovery`.
- Snapshot import, Working materialization/restore, Working versions, and Import
  Undo now write versioned staging manifests as cross-media crash evidence.
- An operation-aware planner chooses restore, quarantine, reproducible cleanup,
  manifest cleanup, or unchanged. Unprovable bytes default to reversible
  quarantine.
- Recovery never overwrites, deletes, or quarantines registered Working bytes or
  version slots, including edits not yet refreshed into PIG.
- A normal `INSPECTING` import is resumable, not interrupted. Only a
  `SNAPSHOTTING` write-critical session is reconciled to `INTERRUPTED`.
- Produced the three-run median benchmark, exact release lock, CycloneDX SBOM,
  `pip-audit`, notices, Windows file inventory, and build hash.
- Rebuilt the internal PyInstaller `onedir`, `console=False`, `upx=False`
  package. Its packaged flow exercises current Workbench contracts rather than
  historical Evidence contracts.

### 2. Domain objects

The change adds `RecoveryRun`, `RecoveryItem`, and operation-scoped
`StagingOperationManifest`, and reconciles `ImportSession`, `ImportSessionItem`,
`OriginalSnapshot`, `WorkspaceItem`, `WorkingArtifact`, and `WorkingRevision`.
`ProcessingEvent` remains append-only history. Source Origin and Workspace
Placement are not rewritten.

### 3. User action -> backend -> persistence -> output

Project Open loads SQLite-known storage keys and performs a read-only scan.
Healthy Projects proceed without a database write. Projects with candidates
enter read-only mode. Confirmed recovery rescans, verifies the inspection token,
persists the run and items, executes operation-specific actions, commits each
result and event, rescans, and reports success, partial success, or failure.

### 4. State / Event / Log changes

Run and Item transitions are the state machines documented above. A prior
nonterminal recovery is explicitly failed as `RECOVERY_INTERRUPTED` during the
next confirmed run. Structured Events cover run/item starts and outcomes;
technical traces remain in the rotating debug log.

### 5. Tool / Action

`inspect_project_recovery` and `recover_workbench_project` are reusable typed
in-process Actions. They are not public APIs, MCP tools, workflows, or
automations in V1.

### 6. Security and permission impact

Scanning is read-only. Execution requires confirmation, revalidates the plan
token, confines storage keys to the Project root, quarantines unknown bytes
reversibly, deletes only reproducible caches, and protects Original and all
registered Working/version bytes. 7-Zip is external and validated by version and
SHA-256.

### 7. Test coverage

Automated tests cover healthy and interrupted scans, write blocking, reversible
quarantine, Working-byte protection, Import Undo restoration, stale tokens,
state reconciliation, UI recovery mode, migration, and the current packaged
Workbench flow. The formal benchmark and release evidence values are recorded
in the Chinese section and generated release files.

### 8. Boundaries not yet closed

The user confirmed W8 source-desktop manual acceptance. Final-package desktop
acceptance on a clean Windows host, human license review, and code-signing policy
remain open. The package is for internal acceptance only. W8 does not add an installer, onefile build,
auto-update, non-Windows release, persistent worker system, watcher, AI, Agent,
or MCP.

### 9. Smallest next step

Enter the W9 Release Qualification decision gate. Approve D78-D86 before final
package, clean-host, licensing, signing, and real-RAR qualification. W9 does not
enter V2 Content Index early.
