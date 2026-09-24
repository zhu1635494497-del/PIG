# PIG V1 工作台桌面验收 / Workbench Desktop Acceptance

- 状态：W8 源码桌面人工验收通过；最终包与干净主机发布资格转入 W9 / Status: W8 source-desktop manual acceptance passed; final-package and clean-host release qualification moves to W9
- 日期：2026-09-24 / Date: 2026-09-24
- 约束决策：`ADR-010`、`ADR-018`、`ADR-019`、`ADR-020` / Governing decisions: `ADR-010`, `ADR-018`, `ADR-019`, `ADR-020`
- 适用范围：仅新 Workbench Project，旧 Project 兼容不在范围内 / Applies to: new Workbench Projects only; old Project compatibility is out of scope

## 中文规范正文

### 1. 目的与通过边界

本流程定义 W1–W8 实现后的目标用户验收：

```text
选择 Project 存储位置
  -> 拖入文件/文件夹
  -> 创建不可变 Original Snapshot
  -> 发现嵌套 Container 结构
  -> 展示可编辑 Workspace Tree
  -> 延迟物化并打开一个文件
  -> 在 Host Application 中编辑/保存
  -> 刷新并识别修改
  -> 保留当前与上一版本并可确认回滚
  -> Move/Add/Soft Delete/Restore
  -> 必要时撤销一个误导入的顶层输入
  -> 导出单个文件、多选 ZIP 或普通文件夹
  -> 重启并验证持久化
```

W8 自动化、真实规模参考基线、当前 Windows 主机 Package Smoke 和源码真实数据人工
桌面流程均已通过；最终 Package 与干净主机发布资格步骤 33–34 转入 W9。历史 Evidence
Browser 验收结果不能算作 Workbench 验收。

### 2. 准备测试数据

所有输入必须位于 Project Storage Root 外，并预先记录 Top-level File Count、Total
Bytes 和 SHA-256。核心数据集必须包含：可编辑 XLSX/DOCX/TXT；第二种可打开格式；
`ZIP -> Folder -> EML/MSG -> Attachment ZIP/7z -> Editable Document`；不同目录的
同名文件；一个 Unknown；一个损坏/不支持 Container；一个初次导入后再 Add 的
普通文件。负面测试可包含 Password、Excessive Depth/Size 和 Symbolic Link。

### 3. 核心手工流程

只使用新的空 `<acceptance-root>`，旧数据库不能作为验收 Fixture。

1. 启动 Workbench Build：窗口响应正常，无 Console/Startup Error。
2. 创建 Project：Project Directory 和 Database 存在，尚无输入。
3. 一次拖入准备好的文件和文件夹：PIG 只创建一个 Import Action，展示进度并分别
   报告 Accepted/Failed。
4. 导入后在 PIG 外移动或删除原测试目录：Project 仍可加载并检查 Source Structure。
5. 对比 Fingerprint：每个接受的字节对象都有实际 Size/SHA-256，外部原件未修改。
6. 展开 Workspace Tree：Folder/ZIP/7z/RAR/MSG/EML 层级正确；坏对象结果明确，
   Sibling 仍可用。
7. 打开深层 Terminal 前检查 Storage：Item 为 `VIRTUAL`，没有为全部 Terminal
   Durable Materialize；Inspection Cache 不作为 Project Content 展示。
8. 双击深层可编辑 Item：只物化该 Item 为带安全扩展名的 Stable Working Artifact，
   并用关联 Host Application 打开。
9. 在 Host Application 原地 Save，返回 PIG 并必要时点击 **Refresh file state**：
   PIG 重新计算 Size/SHA-256，显示 `MODIFIED`，Original 不变。
10. 关闭并重新打开同一文件：复用 Stable Working Artifact，打开修改后字节。
11. 创建 Workspace Folder 并移动两个 Item，重启：Parent/Order 保持，Source 和
    Origin Binding 不变。
12. Add 额外文件：PIG 先 Snapshot，再创建 Workspace Item，外部路径不是编辑位置。
13. 确认后 Soft Delete 一个 Materialized Item：普通 Tree 隐藏，但相关 Fact/Bytes
    可恢复。
14. Restore：返回有效旧 Placement；否则回到 Project Root 并明确报告 Fallback。
15. 尝试向 ZIP/RAR/7z/MSG/EML Container View Move/Add：PIG 拒绝并说明 V1 不回写。
16. 在 OS 中删除一个 Working File 后 Refresh：PIG 报告 `MISSING`，Original/Source
    完整；只有显式安全 Action 才能重新物化。
17. 搜索 Original Name、Edited Item、Added Item：结果显示当前 Lifecycle/Content。
18. 关闭重开 Project：布局、Delete/Restore、Edit、State 和 Original Fact 全部保持。
19. 将一个或多个新输入拖到 Workspace Tree 之外的中央空白区域：PIG 将其增加到
    Project Root，不要求精确命中 Tree。
20. 双击物化文件：Host Application 看到安全化的原显示名，而不是 `content`；同一
    会话再次打开同名文件时，PIG 先提示可能产生辨识冲突。
21. 对同一 Working File 连续执行两次“编辑、原地保存、返回 PIG 刷新”：Item
    Details 只显示 `当前版本` 和 `上一版本`，时间可读、SHA-256 对应实际字节，不出现
    第三个历史槽。
22. 点击 **回滚到上一版本** 并确认：Working File 恢复上一版本；再次回滚可返回刚被
    覆盖的版本；Original Snapshot、Source Structure 和 Workspace Placement 均不变。
23. 单选导出一个文件，再多选导出 ZIP：导出内容为当前 Working 字节，名称和 ZIP
    Entry 使用安全的 Workspace 相对路径；成功后有明确提示，未确认不得覆盖目标。
24. 新建名为“测试000”的 Project：数据库必须位于
    `<acceptance-root>/测试000/project.sqlite`，内部 UUID 只作为身份，不出现在新目录名中；
    同名目标已存在时明确拒绝。
25. 一次拖入文件夹 A 和误选文件 A，在误选文件的右键菜单选择 **撤销此次误导入**：
    PIG 先显示 Workspace/Working/字节影响并二次确认；完成后文件夹 A 及其内容仍在，
    误选文件不再出现在 Workspace、Search 或 Deleted Items，外部原文件保持不变。
26. 右键 Active File/Folder 和 Deleted Item：Open/Refresh/Export/Soft Delete/Restore
    等入口与 Toolbar 结果一致，所有校验仍由后端执行。
27. 单选一个含嵌套层级、空普通文件夹和已修改 Working File 的 Workspace Folder，
    导出到新目标：得到同名普通目录，结构和当前字节正确；已有目标目录不得合并或覆盖。
28. 正常关闭后重新打开健康 Project：后台 Recovery Scan 不显示警告、不修改数据库，
    所有正常 Action 可用。
29. 在一次性验收 Project 的 `.inspection` 下放置可再生测试残留并重新打开：显示醒目
    Recovery-required 提示；Tree/Search 可读，Import/Open/Export/Move/Delete 等写或
    外部副作用 Action 禁用；仅扫描不得移动测试残留。
30. 取消 Recovery：Project 保持只读且残留仍在；再次点击 Recover 并确认后，可再生
    残留被清理，Run/Item/Event 可查，Project 恢复正常。
31. 修改一个已物化 Working File 但不点击 Refresh，同时制造一个未登记 Working
    测试对象：Recover 只能隔离未登记对象，已知 Working 的修改字节必须逐字节保持。
32. 使用源码端执行一个真实 RAR：无 7-Zip 时得到受控错误且 ZIP/7z 不受影响；标准
    Windows 位置存在 7-Zip 时 RAR 成功，并记录 Backend Version 与 Executable SHA-256。
33. 从 `dist/workbench-w8/PIG/PIG.exe` 重复步骤 1–32 的适用部分；窗口无 Console，
    新 Project 使用 `0008`，Package 内部验收报告为 PASS。
34. 核对最终 `windows-file-inventory.json`：Build Hash 和 PIG.exe Hash 与实际文件相符，
    `bundled_7zip_binary_count` 为 0；人工 License/Signing/Clean-host 门未完成时不得外发。

### 4. 安全与资源验收

Traversal/Absolute/Device Path 不得选择输出位置；Archive Symbolic Link 不得跟随；
Snapshot/Inspection/Materialization 统一执行资源限制；Password 记录
`PASSWORD_REQUIRED` 且不收集密码；Unknown/Denied Format 不交给 OS；Move 不能形成
Cycle 或跨 Project；Soft Delete 不删除 Original；Materialization 失败不丢弃 Sibling
或 Placement。

### 5. 外部编辑限制

PIG 不承诺识别精确 Save 时刻；Focus Return 只触发选中项的确定性刷新，W7.1 不建立
Watcher；Project 外 Save As 不跟踪；编辑 Member 不回写 Container；V1 不保留完整
Version History，只维护 `CURRENT_CHECKPOINT` 与 `PREVIOUS` 两个有界版本槽。同名
提示仅覆盖当前 PIG 会话；OS 文件关联无法反馈 Host Application 内部是否拒绝打开。

### 6. 验收记录

记录 Build Path/Hash、OS/Host App Version、Project Path/Model Version、Input
Fingerprint、Snapshot Count/Bytes、Import Result、Nested Structure、首次 Open 前的
Virtual Count、Working Path/Baseline/Current Hash/State、Move/Add/Delete/Restore
重启结果、每次 Workspace Write 后的 Original Integrity，以及所有异常文件和状态。

另记录中央区域 Drop 结果、实际 Working 文件名、两个版本槽的 Hash/时间、回滚前后
Hash、Project 名称目录、Import Undo 影响/结果、单文件/ZIP/文件夹导出路径与 Hash，
覆盖拒绝/确认结果、Recovery Run/Item/Event、隔离位置、恢复前后 Working Hash、
7-Zip Version/SHA-256（如存在）以及 Package Build/PIG.exe Hash。

W8 源码桌面验收要求步骤 1–32 和适用安全检查无未解释差异，现已由用户确认通过。
步骤 33–34 是 W9 最终 Package 与发布资格门，尚未完成。

### 7. 明确排除

不验收 Archive/Email Write-back、Transparent Repack、任意节点 Permanent Purge、Rename、
Content Index、OCR、RAG、AI、Agent、Workflow Engine、Automation Engine、MCP、
Cloud Sync、Multi-user Collaboration 或旧 Project Compatibility。

## English normative text

## 1. Purpose and pass boundary

This procedure defines the target user acceptance flow after Workbench Milestones
W1-W8 are implemented:

```text
Choose Project storage
  -> drag files/folders into PIG
  -> create immutable Original Snapshot
  -> discover nested Container structure
  -> display editable Workspace Tree
  -> lazily materialize and open one file
  -> edit/save in the host application
  -> refresh and detect the change
  -> retain current/previous versions and confirm rollback
  -> move/add/soft-delete/restore
  -> undo one accidental top-level import when needed
  -> export one file, a multi-selection ZIP, or an ordinary folder
  -> restart and verify persistence
```

Automated W8 qualification, the realistic reference baseline, current-host
package smoke tests, and the real-data source-desktop flow have passed. Final
package and clean-host Steps 33-34 move to W9 release qualification. Historical
Evidence Browser acceptance cannot substitute for Workbench acceptance.

## 2. Prepare test data

Keep all inputs outside the selected Project storage root. Record file count,
total bytes, and SHA-256 for each top-level file before import.

The core dataset must contain:

1. an editable document such as XLSX, DOCX, or TXT;
2. a PDF or image for a second openable format;
3. a realistic nested chain such as
   `ZIP -> folder -> EML/MSG -> attachment ZIP/7z -> editable document`;
4. duplicate names in different directories;
5. one Unknown terminal file;
6. one intentionally corrupt or unsupported Container for partial-success
   behavior;
7. a separate ordinary file to add after initial import.

Optional negative fixtures include password-protected archives, excessive depth,
excessive expanded size, and symbolic links. Use only disposable, non-sensitive
data.

## 3. Core manual procedure

Use a new empty `<acceptance-root>`. Old project databases are not acceptance
fixtures.

| Step | User operation | Expected result / evidence |
|---:|---|---|
| 1 | Start the new Workbench build. | One responsive PIG window opens without a console or startup error. |
| 2 | Create a Project and choose `<acceptance-root>`. | The Project directory and database are created; no input has been imported yet. |
| 3 | Drag the prepared files and folders into PIG in one operation. | PIG asks for/uses one import action, shows progress, and reports accepted and failed items separately. |
| 4 | After import, rename or remove the external test-data directory outside PIG. | The Project still loads and its Source Structure remains inspectable because it is backed by the Project-owned Original Snapshot. |
| 5 | Compare recorded fingerprints with Project Original facts. | Every accepted byte-bearing input has verified size/SHA-256. External originals were not modified. |
| 6 | Expand the Workspace Tree and nested Containers. | Folder/ZIP/7z/RAR/MSG/EML nesting is correct within policy limits; corrupt/unsupported content has an explicit result and accepted siblings remain usable. |
| 7 | Inspect the Project storage before opening a deep terminal member. | The selected terminal item is `VIRTUAL`; PIG has not durably created Working Files for all terminal members. Inspection cache/staging is not presented as project content. |
| 8 | Double-click one deep editable terminal item. | PIG materializes exactly that item to a stable safe-suffix Working Artifact and opens it with the associated host application. |
| 9 | Modify the opened file in its host application and use normal Save, not Save As. Return focus to PIG and, if needed, click **Refresh file state**. | PIG observes stable bytes, recalculates size/SHA-256, and shows `MODIFIED` without changing the Original Snapshot. |
| 10 | Close and reopen the same Working File from PIG. | The edited bytes reopen; PIG reuses the stable Working Artifact rather than rematerializing the original. |
| 11 | Create an ordinary Workspace folder and move the modified item plus another item into it. Restart PIG. | Workspace parent/order persists. Source Structure and origin bindings are unchanged. |
| 12 | Add the separate prepared file. | PIG snapshots the new input, creates a Workspace Item, and does not use the external path as its editable location. |
| 13 | Soft-delete one materialized item after confirmation. | The item disappears from the normal tree, but its Original/Source/Working facts remain recoverable. |
| 14 | Restore the deleted item. | It returns to its valid prior placement, or to Project root with an explicit fallback result. |
| 15 | Attempt to move/add a file into a ZIP, RAR, 7z, MSG, or EML Container View. | PIG refuses and explains that V1 does not rewrite or repack Containers. |
| 16 | Delete one Working File directly through the operating system, then refresh it in PIG. | PIG reports `MISSING`; the Source and Original Snapshot remain intact and rematerialization is offered only through an explicit safe action. |
| 17 | Search for an original name, an edited item, and an added item. | Search returns current Workspace Items and their current lifecycle/content states. |
| 18 | Close and reopen the Project. | Workspace layout, soft-delete/restore result, Working File edit, states, and Original Snapshot facts persist. |
| 19 | Drop one or more new inputs on the central Workspace surface outside the tree. | PIG adds them at Project root without requiring a precise tree target. |
| 20 | Double-click a materialized file, then open another same-named file during the same PIG session. | The host sees a safe recognizable display name rather than `content`; PIG warns before the second same-name handoff. |
| 21 | Edit, save in place, return to PIG, and refresh the same file twice. | Item Details shows only `Current` and `Previous`, with readable timestamps and hashes matching the bytes; no third history slot exists. |
| 22 | Click **Roll back to previous version** and confirm, then repeat once. | The first rollback restores the previous bytes; the second can restore the version just replaced. Original Snapshot, Source Structure, and Workspace Placement do not change. |
| 23 | Export one selected file, then export multiple selected files as ZIP. | Exports contain current Working bytes and safe Workspace-relative names; success is explicit and an existing destination is not replaced without confirmation. |
| 24 | Create a Project named `测试000` under `<acceptance-root>`. | Its database is `<acceptance-root>/测试000/project.sqlite`; the UUID remains internal, and an existing same-name destination is rejected. |
| 25 | Drop Folder A plus an accidentally selected File A in one operation, then choose **Undo this accidental import** from the File's context menu. | PIG previews Workspace/Working/byte impact and asks again. Folder A remains, File A disappears from Workspace/Search/Deleted Items, and the external File A is unchanged. |
| 26 | Right-click active files/folders and deleted items. | Context Open/Refresh/Export/Soft Delete/Restore actions match toolbar behavior and remain backend-validated. |
| 27 | Export one ordinary Workspace folder containing nested levels, an empty folder, and a modified Working File. | A same-named normal directory is created with preserved structure and current bytes; an existing destination directory is never merged or replaced. |
| 28 | Close normally and reopen a healthy Project. | The background recovery scan is silent, does not write the database, and leaves normal Actions enabled. |
| 29 | Put reproducible test residue under `.inspection` in a disposable acceptance Project, then reopen it. | A visible Recovery-required banner appears. Tree/Search remain readable; import/open/export/move/delete are disabled. Scanning alone does not move the residue. |
| 30 | Decline recovery, then invoke Recover again and confirm. | Declining preserves read-only mode and the residue. Confirmed recovery removes only the reproducible residue, persists Run/Item/Event facts, and restores normal mode. |
| 31 | Modify a materialized Working File without refreshing it, and create one unregistered Working test object. | Recovery quarantines only the unregistered object; the registered modified Working bytes remain byte-for-byte unchanged. |
| 32 | Process a real RAR in the source build. | Without 7-Zip, RAR returns a controlled error while ZIP/7z still work. With 7-Zip in a standard Windows location, RAR succeeds and records backend version and executable SHA-256. |
| 33 | Repeat applicable Steps 1-32 using `dist/workbench-w8/PIG/PIG.exe`. | No console appears; new Projects use migration `0008`; the packaged Workbench acceptance report is PASS. |
| 34 | Review final `windows-file-inventory.json`. | Build/PIG.exe hashes match actual files and `bundled_7zip_binary_count` is zero. The package is not externally distributed while license/signing/clean-host gates remain open. |

## 4. Security and resource acceptance

Run negative cases in a disposable Project:

- traversal/absolute/device archive paths never select a physical output path;
- archive symbolic links are described when possible but never followed;
- snapshot, inspection, and materialization all enforce centralized limits;
- password-protected content records `PASSWORD_REQUIRED` without requesting or
  storing a password;
- Unknown or denied formats are not handed to the operating system;
- Workspace moves cannot create a cycle or cross a Project boundary;
- soft delete never deletes Original Snapshot bytes;
- a failed materialization does not discard accepted siblings or Workspace
  Placement.

## 5. External-edit limitations to verify

- PIG does not promise to detect the exact Save instant; displayed save records
  are PIG detection times plus observed file-modified times.
- Focus return requests deterministic refresh of the selected item; it is not
  the authoritative observation. W7.1 adds no watcher.
- Save-As outside the Project is not tracked.
- Editing a member never rewrites the backing ZIP/email/other Container.
- No full version history exists. V1 retains only `CURRENT_CHECKPOINT` and
  `PREVIOUS` and supports confirmed slot-swapping rollback.
- Same-name warnings cover only the current PIG session. OS file association
  cannot report whether the host application internally refused an open.

## 6. Acceptance record

Record:

- build path and executable SHA-256;
- operating system and host application versions used for edit testing;
- Project directory and model version;
- input paths and before/after fingerprints;
- snapshot count/bytes and import partial-success result;
- expected/actual nested structure;
- count of virtual terminal items before first Open;
- Working Artifact path, baseline hash, edited current hash, and state;
- move/add/delete/restore results after restart;
- Original Snapshot integrity after every Workspace write operation;
- unexpected statuses, errors, or unexplained physical files;
- central-surface drop result and the physical friendly Working filename;
- current/previous version hashes and timestamps, plus hashes before/after rollback;
- named Project path and import-undo preview/result;
- single-file, ZIP, and folder export paths/hashes and overwrite-decision results.
- recovery Run/Item/Event IDs, quarantine paths, and Working hashes before/after recovery;
- 7-Zip version/SHA-256 when present, plus package build and PIG.exe hashes.

W8 source-desktop acceptance requires Steps 1-32 and applicable security checks
with no unexplained difference; the user has confirmed it passed. Steps 33-34
are W9 final-package and release-qualification gates and remain open.

## 7. Explicit exclusions

This acceptance does not test archive/email write-back, transparent repack,
arbitrary-node permanent purge, rename, content indexing, OCR, RAG, AI, Agent, Workflow engine,
Automation engine, MCP, cloud sync, multi-user collaboration, or old Project
compatibility.
