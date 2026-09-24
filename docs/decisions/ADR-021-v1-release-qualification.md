# ADR-021：Workbench W9 V1 发布资格闭环 / Workbench W9 V1 Release Qualification

- 状态：已接受；W9 实施中 / Status: Accepted; W9 implementation in progress
- 提案日期：2026-09-24 / Proposal date: 2026-09-24
- 批准日期：2026-09-24 / Approval date: 2026-09-24
- 范围：Workbench Milestone W9 / Scope: Workbench Milestone W9
- 输入：W8 源码桌面人工验收通过、当前主机内部包机器验收通过 / Input: W8 source-desktop manual acceptance passed; current-host internal-package machine acceptance passed

## 中文提案

### 背景

W8 已完成 Recovery、真实性能基线、`0008_workbench_recovery`、Windows `onedir`
内部验收包及源码桌面人工验收。当前产品功能闭环已经达到 V1 Workbench 目标，但
License Review、Code Signing、Clean-host Package Acceptance 和明确的外部分发判定仍未
闭合。直接进入 V2 Content Index 会让 V1 长期停在“能开发、不能正式交付”的状态。

因此建议 W9 只处理 V1 Release Qualification，不增加用户业务功能，也不提前实现
Content Extraction、OCR、RAG、AI、MCP 或安装更新平台。

### 规划影响

- **Domain**：不新增 Project 领域对象或数据库表；Release Evidence 属于构建资产。
- **Flow**：冻结候选版本 → 可复现构建 → 合规/签名 → 干净主机矩阵 → 人工验收 →
  发布或阻断。
- **State**：Project 状态机不变；Release Candidate 只有证据层 PASS/BLOCKED 判定。
- **Lineage**：Source、Origin、Workspace 和 Recovery Lineage 均不变。
- **Log**：保留构建报告、Hash、SBOM、Audit、License Review 和验收记录；不写入用户
  Project Event。
- **Permission**：签名密钥、外部分发和诊断资料属于高风险边界，必须人工控制。
- **Tool**：不新增公共 Tool；只允许确定性 Release Script。
- **AI / Automation**：不使用 AI，不建设发布 Automation 平台。
- **UI**：默认不增加页面；只验收现有桌面流程和错误可解释性。

### D78：下一 Milestone 定位

**方案 A（推荐）**：W9 定义为 V1 Release Qualification and Closure。先完成可交付、
可复核、可阻断的发布闭环，再单独决定是否进入 V2。

**方案 B**：立即进入 V2 Content Index。可更快增加内容搜索，但会跳过 V1 外部分发、
签名与干净主机验证，两个阶段的故障会混在一起。

### D79：V1 分发形态

**方案 A（推荐）**：保持 PyInstaller `onedir`，发布为带版本号的 Portable ZIP，附带
SHA-256、Build Report、SBOM、Notice 和 Checklist。W9 不制作 Installer、OneFile、
Auto-update 或系统服务。

**方案 B**：W9 同时建设 Installer 和 Auto-update。用户安装更方便，但会增加安装权限、
升级回滚、卸载残留、签名范围和网络更新安全，超出当前最小发布闭环。

### D80：代码签名门

**方案 A（推荐）**：外部分发必须使用受控 Authenticode 证书签名 `PIG.exe` 和最终
Portable ZIP（如签名系统支持），并使用可信时间戳。没有证书时只能生成 Internal RC，
不得将 Unsigned Build 标记为正式外发版。

**方案 B**：允许未签名正式外发。准备更快，但来源和完整性难以由用户验证，并提高
Windows 警告和供应链风险。

### D81：第三方许可证门

**方案 A（推荐）**：由人工逐项复核 Runtime SBOM/Notice 的 License、Copyright、
Notice Obligation 和 Redistribution 条件，形成签名/日期明确的 Review Record；7-Zip
继续作为外部依赖且不捆绑。自动生成元数据不能替代人工结论。

**方案 B**：把自动生成的 Package Metadata 当作许可证批准。成本更低，但无法证明
复杂或缺失 License 字段已经得到正确解释。

### D82：干净 Windows 主机矩阵

**方案 A（推荐）**：至少使用可还原的干净 Windows x64 环境执行两组验收：未安装
7-Zip；标准位置安装已批准 7-Zip。记录 OS Build、PIG Hash、7-Zip Version/Hash、Host
Application Version 和全部验收结果。开发机结果不能替代干净主机。

**方案 B**：只使用当前开发机。执行更快，但无法发现隐式 PATH、Python、VC Runtime、
Qt Plugin 或已安装软件依赖。

### D83：Project 兼容与升级边界

**方案 A（推荐）**：W9 验证新建 Project，以及 W8 `0008` Project 的备份副本在最终包
中可重开、编辑、恢复和导出。历史 Evidence-era Project 继续明确拒绝。W9 默认不新增
Migration；若发现必须变更 Schema，返回新的重大决策门。

**方案 B**：在 W9 增加历史 Project 自动迁移。会重新引入 ADR-010 已排除的双模型和
误读风险。

### D84：RAR / 7-Zip 发布验收

**方案 A（推荐）**：使用可公开、非敏感的真实 RAR Fixture 验证两条路径：没有 7-Zip
时产生受控错误且不影响 Sibling；标准位置存在受控 7-Zip 时完成 Inspect、Lazy
Materialize、Open/Export，并在 Attempt 中记录 Backend Version/SHA-256。

**方案 B**：只保留 Mock/Test Adapter。自动测试稳定，但不能证明最终 Package、真实
7-Zip CLI 和目标主机组合有效。

### D85：支持与诊断边界

**方案 A（推荐）**：W9 不新增“诊断中心”或自动上传。发布说明明确日志位置、Build
Report、Recovery Run/Item 查询方式和人工收集步骤；任何日志外发由用户选择并先检查
敏感路径/文件名。

**方案 B**：增加一键上传完整日志。支持效率更高，但会引入服务器、隐私、同意、保留
周期和权限范围，当前没有必要。

### D86：W9 退出条件与 V2 边界

**方案 A（推荐）**：License、Signing、Clean-host、真实 RAR、最终 Package Desktop
Acceptance 全部通过后，才把版本标记为 V1 Release；任何一项未通过则保持 Internal RC。
W9 不实现 V2；V1 发布闭环后再为 Content Index 单独提出 ADR 和 Milestone。

**方案 B**：允许带未关闭 Gate 的版本标记为正式 V1，同时开始 V2。短期更快，但发布
状态失去明确含义，风险无法被可靠阻断。

### D87：GitHub 仓库与公开边界

**方案 A（推荐）**：建立单一公开源码仓库，保存源码、双语文档、测试、Issue 和版本
历史；可下载程序通过 GitHub Releases 发布。公开后任何人均可查看和 Fork，因此首次
Push 前必须完成敏感信息和本地项目数据审计。

**方案 B**：开发源码保存在私有仓库，另建只包含公开发布说明与二进制资产的公开下载
仓库。源码控制更严格，但需要维护两套仓库、版本关联和发布权限。

### D88：PIG 自有代码许可证

**方案 A（推荐，仅适用于 D87-A）**：使用 Apache License 2.0，允许使用、修改和分发，
同时提供明确的专利授权与 Notice 要求。第三方组件继续遵守各自许可证，不因 PIG 许可
证而改变。

**方案 B**：使用 MIT License。文本和义务更简单，但没有 Apache-2.0 同等明确的专利
授权条款。

**方案 C**：不授予开源许可证。公开仓库只代表源码可见，不代表他人可合法复制、修改
或分发；若选择 D87-B，则公开二进制还需要单独确定最终用户许可条款。

许可证选择属于产品与法律决策；本 ADR 不是法律意见，正式外发仍受 D81 人工 License
Review 约束。

### D89：GitHub 下载与版本方式

**方案 A（推荐）**：使用语义化版本 Tag 和 GitHub Releases。每个正式 Release 附带
带版本号的 Windows x64 Portable ZIP、SHA-256、SBOM、第三方 Notice、双语 Release
Notes 和验收状态；不得把 `dist/` 二进制直接提交到 Git 历史。

**方案 B**：把每次构建产物直接提交到源码分支。操作直观，但会扩大仓库、混淆源码
历史与发布资产，并使清理错误产物更困难。

### D90：GitHub Actions 自动化边界

**方案 A（推荐）**：Push/Pull Request 只运行确定性测试和构建检查；版本 Tag 可生成
Unsigned Internal RC。正式 Release 仍必须经过 D80 签名、D81 许可证、D82 干净主机和
D86 人工批准门，不把签名证书直接交给尚未审定的通用 CI 流程。

**方案 B**：立即让 GitHub Actions 自动签名并直接发布正式版本。下载更快，但会提前
扩大证书密钥、Workflow 权限和错误发布的风险范围。

### D91：首次 Git 历史与仓库卫生

**方案 A（推荐）**：从当前 W8 源码基线建立干净的首次历史，只纳入产品源码、
Migration、测试、构建脚本和有效双语文档。明确排除 `.venv/`、`build/`、`dist/`、
`acceptance/`、`runtime/`、用户 Project、SQLite、日志、缓存、本机路径、证书与密钥；
首次 Push 前执行文件清单和 Secret Scan。

**方案 B**：直接把当前工作目录整体提交。准备时间更短，但会把构建产物、验收数据和
潜在敏感资料写入不可轻易清除的 Git 历史。

### 推荐组合

推荐：`D78-A、D79-A、D80-A、D81-A、D82-A、D83-A、D84-A、D85-A、D86-A、`
`D87-A、D88-A、D89-A、D90-A、D91-A`。

产品负责人已批准上述推荐组合，并指定公开仓库为
`https://github.com/zhu1635494497-del/PIG.git`。首次公开 Push 前必须先提供精确文件清单
并取得最终确认。W9 实施不代表 D80–D86 人工 Gate 已经通过；Gate 未闭合时只能生成
Unsigned Internal RC，不得标记正式 V1 Release。

## English proposal

### Context

W8 completed recovery, the realistic benchmark, migration
`0008_workbench_recovery`, the Windows `onedir` internal package, and source-run
desktop acceptance. The V1 Workbench product loop is complete, but human license
review, code signing, clean-host package acceptance, and an explicit external
release decision remain open. Entering V2 now would leave V1 permanently in a
state that can be developed but not formally delivered.

W9 should therefore qualify and close V1 without adding user-facing business
features or prematurely implementing content extraction, OCR, RAG, AI, MCP, or
an installation/update platform.

### Planning impact

- **Domain**: no new Project domain object or table; release evidence is a build
  asset.
- **Flow**: freeze candidate -> reproducible build -> compliance/signing ->
  clean-host matrix -> manual acceptance -> release or block.
- **State**: Project state machines are unchanged; the release candidate has an
  evidence-level PASS/BLOCKED result only.
- **Lineage**: Source, Origin, Workspace, and Recovery lineage are unchanged.
- **Log**: retain build report, hashes, SBOM, audit, license review, and
  acceptance evidence; do not write release facts into user Project Events.
- **Permission**: signing keys, external distribution, and diagnostic material
  are manually controlled high-risk boundaries.
- **Tool**: no public Tool; only deterministic release scripts.
- **AI / Automation**: no AI and no release-automation platform.
- **UI**: no new page by default; qualify the existing desktop flow and errors.

### D78 - Next milestone purpose

**Option A (recommended)**: make W9 V1 Release Qualification and Closure, then
decide on V2 separately.

**Option B**: enter V2 Content Index immediately, mixing release failures with a
new product capability.

### D79 - V1 distribution shape

**Option A (recommended)**: retain PyInstaller `onedir` and distribute a
versioned portable ZIP with SHA-256, build report, SBOM, notices, and checklist.
No installer, onefile, auto-update, or service is added in W9.

**Option B**: build an installer and auto-update now, adding install privilege,
rollback, uninstall residue, signing, and network-update security scope.

### D80 - Code-signing gate

**Option A (recommended)**: external release requires a controlled Authenticode
certificate and trusted timestamp. Without a certificate the result remains an
Internal RC, never an official external build.

**Option B**: permit an unsigned official release, weakening provenance and
integrity assurance.

### D81 - Third-party license gate

**Option A (recommended)**: a human reviews every runtime SBOM/Notice entry and
records license, copyright, notice, and redistribution conclusions. 7-Zip stays
external. Generated metadata is evidence, not approval.

**Option B**: treat generated package metadata as legal approval.

### D82 - Clean Windows host matrix

**Option A (recommended)**: test a restorable clean Windows x64 environment both
without 7-Zip and with an approved standard-location 7-Zip. Record OS build, PIG
hash, 7-Zip identity, host-application versions, and results. The development
machine does not substitute for this matrix.

**Option B**: use only the current development machine, leaving hidden runtime
dependencies untested.

### D83 - Project compatibility and upgrade boundary

**Option A (recommended)**: qualify new Projects and backup copies of W8 `0008`
Projects for reopen/edit/recovery/export. Historical Evidence projects remain
explicitly unsupported. W9 adds no migration unless a new major decision is
approved.

**Option B**: add automatic migration for historical Projects, reviving the dual
model and misread risks excluded by ADR-010.

### D84 - RAR and 7-Zip release acceptance

**Option A (recommended)**: use a public non-sensitive real RAR fixture to test
both controlled absence and successful standard-location 7-Zip inspect, lazy
materialize, open/export, and recorded backend version/SHA-256.

**Option B**: rely only on mock adapters, which cannot qualify the final package
and real 7-Zip CLI combination.

### D85 - Support and diagnostics boundary

**Option A (recommended)**: add no diagnostics center or automatic upload.
Document log locations, build/recovery evidence, and manual collection. Users
choose and review any diagnostic material before sharing it.

**Option B**: add one-click full-log upload, requiring a server, consent,
privacy, retention, and permission design.

### D86 - W9 exit and V2 boundary

**Option A (recommended)**: mark V1 released only when license, signing,
clean-host, real-RAR, and final-package desktop gates all pass. Otherwise it
remains Internal RC. Propose V2 Content Index separately after V1 closure.

**Option B**: label a build V1 Release with gates still open and begin V2,
making release status non-authoritative.

### D87 - GitHub repository and public boundary

**Option A (recommended)**: use one public source repository for source code,
bilingual documentation, tests, issues, and version history, with downloadable
applications published through GitHub Releases. Because publication allows
others to view and fork the repository, sensitive information and local Project
data must be audited before the first push.

**Option B**: keep development source in a private repository and maintain a
separate public download repository containing only release notes and binary
assets. This restricts source access but adds two-repository version mapping and
permission overhead.

### D88 - License for PIG-owned code

**Option A (recommended only with D87-A)**: use Apache License 2.0, permitting
use, modification, and distribution with an explicit patent grant and notice
conditions. Third-party components remain governed by their own licenses.

**Option B**: use the MIT License. It is shorter and simpler but does not contain
the same explicit patent grant as Apache-2.0.

**Option C**: grant no open-source license. A public repository makes the source
visible but does not generally grant permission to copy, modify, or distribute
it. With D87-B, separate end-user terms are also required for public binaries.

License selection is a product and legal decision. This ADR is not legal advice,
and D81 human license review still gates an external release.

### D89 - GitHub downloads and versioning

**Option A (recommended)**: use semantic-version tags and GitHub Releases. Each
official release includes a versioned Windows x64 portable ZIP, SHA-256, SBOM,
third-party notices, bilingual release notes, and acceptance status. `dist/`
binaries are never committed directly to Git history.

**Option B**: commit each build output to the source branch. This is direct but
inflates the repository, mixes source history with distribution assets, and
makes accidental artifacts harder to remove.

### D90 - GitHub Actions automation boundary

**Option A (recommended)**: pushes and pull requests run deterministic tests and
build checks; version tags may produce unsigned Internal RCs. An official
release still requires the D80 signing, D81 license, D82 clean-host, and D86
human approval gates. The signing certificate is not placed into an unreviewed
general CI workflow.

**Option B**: immediately let GitHub Actions sign and publish official releases.
This shortens delivery but prematurely expands certificate-secret, workflow-
permission, and accidental-release risk.

### D91 - Initial Git history and repository hygiene

**Option A (recommended)**: create a clean initial history from the current W8
source baseline, including only product source, migrations, tests, build scripts,
and active bilingual documentation. Exclude `.venv/`, `build/`, `dist/`,
`acceptance/`, `runtime/`, user Projects, SQLite files, logs, caches, local paths,
certificates, and keys. Review the file inventory and run a secret scan before
the first push.

**Option B**: commit the current working directory as-is. This is faster but can
write generated artifacts, acceptance data, and sensitive material into Git
history where removal is difficult.

### Recommended combination

Recommended: `D78-A, D79-A, D80-A, D81-A, D82-A, D83-A, D84-A, D85-A, D86-A,`
`D87-A, D88-A, D89-A, D90-A, D91-A`.

The owner approved the complete recommended combination and selected
`https://github.com/zhu1635494497-del/PIG.git` as the public repository. The exact
file inventory and final confirmation are still required before the first public
push. W9 implementation does not imply that the D80-D86 human gates have passed;
until they close, automation may produce only an unsigned Internal RC and must
not label an official V1 Release.
