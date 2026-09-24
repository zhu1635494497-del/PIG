# PIG V1 Workbench W9 实施记录 / Implementation Record

- 状态：本地公开源码基线与 Unsigned Internal RC 已就绪；首次 Push 已批准，正式 Release 仍阻断 / Status: local public-source baseline and unsigned Internal RC ready; first push approved, official Release still blocked
- 日期：2026-09-24 / Date: 2026-09-24
- 决策：`ADR-021`，D78-A 至 D91-A / Decisions: `ADR-021`, D78-A through D91-A
- 目标仓库：`https://github.com/zhu1635494497-del/PIG.git` / Target repository: `https://github.com/zhu1635494497-del/PIG.git`

## 中文实施记录

### 1. 完成了什么

- 建立 Apache-2.0、NOTICE、双语 README、CONTRIBUTING 和 SECURITY。
- 扩充 `.gitignore`，排除虚拟环境、Build/Dist、Acceptance、Runtime Project、数据库、
  日志、缓存、证书、密钥和主机生成 Release Evidence。
- 建立 `.gitattributes`，统一源码和文档文本行尾并显式标记常见二进制格式。
- 建立只读权限 Windows Python 3.10 CI。
- 建立只由手工触发或 `v*-rc*` Tag 触发的 Unsigned Internal RC Workflow；它运行测试、
  生成 SBOM/Audit/Notice、构建 `onedir`、执行 Smoke、生成 Hash 并上传短期 Artifact，
  但不创建 GitHub Release、不签名、不接触证书。
- 建立 W9 Release Checklist 和第三方许可证人工复核模板。
- 将 `pyproject.toml` 连接到公开仓库并声明 PIG 自有代码 Apache-2.0。
- 初始化本地 Git `main`，设置目标 `origin`；尚无 Commit 或 Push。

### 2. 涉及的领域对象

不新增或修改 Project、Original Snapshot、Source Node、Workspace Item、Working Artifact、
Recovery Run 或 Processing Event。Release Evidence 是构建资产，不进入 Project SQLite。

### 3. 数据完整流向

```text
受审计源码与文档
  -> 本地 Git Candidate Inventory
  -> GitHub CI 测试
  -> v*-rc* 或手工 Candidate Build
  -> SBOM / Audit / Notice / Build Report / SHA-256
  -> Unsigned Internal RC Artifact
  -> 人工 License / Signing / Clean-host / RAR / Desktop Gates
  -> 正式 GitHub Release 或 BLOCKED
```

### 4. 状态、Event 与 Log

- Project 与 Workspace 状态机不变。
- W9 当前发布判定仍为 `BLOCKED`；本机构建只达到 `PASS_INTERNAL_ACCEPTANCE`。
- CI Log、Build Report、Package Inventory、SBOM、Audit、Notice 和 Checklist 是 Release
  Evidence，不写入业务 Processing Event。

### 5. Tool / Action

不新增业务 Tool 或 Desktop Action。GitHub Actions 是确定性发布校验，不是 PIG
Workflow/Automation Engine，也不对 Agent 或 MCP 暴露能力。

### 6. 安全与权限

- Workflow 只授予 `contents: read`。
- 不在 Workflow 中保存 Authenticode 私钥，不自动发布正式 Release。
- 首次候选清单不包含本地 Project、SQLite、验收数据、构建二进制或常见 Secret Marker。
- 公开 Push 是不可逆外发边界；必须在精确暂存清单和 Commit 作者身份确认后执行。
- GitHub Actions 版本和 Commit SHA Pin 策略仍需在正式 Release 前复核。

### 7. 测试结果

- 自动化：`146 passed, 95 skipped, 1 warning`。
- Skip：ADR-010 后隔离的历史 Evidence Contract，以及当前主机无法创建测试 Symbolic
  Link 的两个用例。
- Editable Install：使用本地 Build Backend 成功。
- PyInstaller W9 `onedir` Build：成功。
- `--runtime-smoke-test`：Exit 0。
- `--acceptance-smoke-test`：Exit 0。
- 首次公开 Git 暂存清单：215 个文件，约 2.1 MB；无 Build/Dist/Project 数据。
- W9 本机 Package：922 个文件、113,093,576 Bytes，不含 `7z.exe`，Build SHA-256
  `6dff8f014c9fb2955c0477cafb7a23f877401092c4fb4636df0b8147dd86bf61`。
- 常见 GitHub/AWS Token 和 Private Key Marker：公开候选零命中。

### 8. 尚未闭环

- Git 作者 `Littlie pig <zhu1635494497@gmail.com>` 与首次公开 Push 已获明确批准；首次
  Commit 尚待执行。
- 目标 GitHub 仓库因当前环境网络重置无法只读确认远程状态。
- 首次公开 Push、远程 CI 和远程 Unsigned Internal RC 尚未执行。
- 第三方许可证人工复核未完成；GPL/LGPL、Qt/PySide 与 `extract-msg` 链需要书面结论。
- Authenticode 证书、可信时间戳、干净 Windows 主机矩阵、真实 RAR 和最终签名包桌面
  验收未完成。

### 9. 技术债务

- Release Lock 固定版本但尚未固定目标 Wheel Hash。
- GitHub Actions 当前使用 GitHub-owned Major Version Tag，正式发布前需要决定并记录
  Commit SHA Pin。
- W9 不建设 Installer 或应用内 Auto-update；用户通过 GitHub Releases 手工获取更新。

## English implementation record

### 1. Completed work

- Added Apache-2.0, NOTICE, and bilingual README, CONTRIBUTING, and SECURITY files.
- Expanded `.gitignore` to exclude environments, build/dist output, acceptance
  data, runtime Projects, databases, logs, caches, certificates, keys, and
  host-generated release evidence.
- Added `.gitattributes` for normalized source/document line endings and explicit
  binary formats.
- Added read-only-permission Windows Python 3.10 CI.
- Added an unsigned Internal RC workflow triggered only manually or by `v*-rc*`
  tags. It tests, generates SBOM/audit/notices, builds `onedir`, runs smoke modes,
  hashes, and uploads a short-lived artifact. It does not create a GitHub Release,
  sign, or access a certificate.
- Added the W9 release checklist and third-party human license-review template.
- Linked `pyproject.toml` to the public repository and declared Apache-2.0 for
  PIG-owned code.
- Initialized local Git `main` and configured the target `origin`; no commit or
  push exists yet.

### 2. Domain objects

No Project, Original Snapshot, Source Node, Workspace Item, Working Artifact,
Recovery Run, or Processing Event changes. Release Evidence is a build asset and
does not enter Project SQLite.

### 3. Complete data flow

```text
audited source and documentation
  -> local Git candidate inventory
  -> GitHub CI tests
  -> v*-rc* or manual candidate build
  -> SBOM / audit / notices / build report / SHA-256
  -> unsigned Internal RC artifact
  -> human license / signing / clean-host / RAR / desktop gates
  -> official GitHub Release or BLOCKED
```

### 4. State, Events, and logs

- Project and Workspace state machines are unchanged.
- W9 remains `BLOCKED` for official release; the local build reaches only
  `PASS_INTERNAL_ACCEPTANCE`.
- CI logs, build report, package inventory, SBOM, audit, notices, and checklist
  are Release Evidence, not business Processing Events.

### 5. Tool and Action impact

No business Tool or Desktop Action is added. GitHub Actions is deterministic
release validation, not a PIG Workflow/Automation Engine and not an Agent or MCP
surface.

### 6. Safety and permission

- Workflows grant only `contents: read`.
- No Authenticode private key is stored in a workflow and no official Release is
  published automatically.
- The initial candidate excludes local Projects, SQLite, acceptance data, build
  binaries, and common secret markers.
- A public push is an irreversible external boundary and requires confirmation
  of the exact staged inventory and commit-author identity.
- GitHub Actions versions and the commit-SHA pinning strategy remain subject to
  review before an official Release.

### 7. Test results

- Automated: `146 passed, 95 skipped, 1 warning`.
- Skips: historical Evidence contracts quarantined after ADR-010 and two
  symbolic-link cases unsupported by the current host.
- Editable install with the local build backend: passed.
- PyInstaller W9 `onedir` build: passed.
- `--runtime-smoke-test`: exit 0.
- `--acceptance-smoke-test`: exit 0.
- Initial public Git staging inventory: 215 files, approximately 2.1 MB, with no
  build/dist or Project data.
- Local W9 package: 922 files and 113,093,576 bytes, no `7z.exe`, build SHA-256
  `6dff8f014c9fb2955c0477cafb7a23f877401092c4fb4636df0b8147dd86bf61`.
- Common GitHub/AWS token and private-key markers: zero candidate hits.

### 8. Open boundaries

- Git author `Littlie pig <zhu1635494497@gmail.com>` and the first public push
  are explicitly approved; the initial commit is not yet executed.
- The target repository's remote state could not be read because this environment
  reset the GitHub connection.
- First public push, remote CI, and remote unsigned Internal RC are not run.
- Human third-party license review remains incomplete; GPL/LGPL, Qt/PySide, and
  the `extract-msg` chain require written conclusions.
- Authenticode certificate/timestamp, clean-Windows matrix, real RAR, and final
  signed-package desktop acceptance remain incomplete.

### 9. Technical debt

- The release lock pins versions but not target wheel hashes.
- GitHub-owned Actions currently use major-version tags; the official release
  must decide and record commit-SHA pinning.
- W9 does not build an installer or in-application updater; users obtain updates
  manually through GitHub Releases.
