# PIG Workbench W9 发布检查表 / Release Checklist

- 状态：发布资格实施中；正式外发仍阻断 / Status: release qualification in progress; official distribution remains blocked
- 目标：Windows x64 Portable `onedir` ZIP / Target: Windows x64 portable `onedir` ZIP
- 当前版本：`0.1.0` Pre-release / Current version: `0.1.0` pre-release

## 源码仓库门 / Source repository gates

- [x] D78-A 至 D91-A 已批准。 / D78-A through D91-A are approved.
- [x] Apache-2.0、README、SECURITY 和 CONTRIBUTING 已建立。 / Apache-2.0, README, SECURITY, and CONTRIBUTING are present.
- [x] 本地 Project、Acceptance、Runtime、Build、Dist、数据库、日志、证书与密钥已从 Git 候选清单排除。 / Local Project, acceptance, runtime, build, dist, database, log, certificate, and key data are excluded from the Git candidate inventory.
- [x] GitHub CI 只使用 `contents: read`，运行 Windows Python 3.10 测试。 / GitHub CI uses `contents: read` only and runs Windows Python 3.10 tests.
- [x] Candidate Workflow 只生成明确标记的 Unsigned Internal RC，不创建 GitHub Release。 / The candidate workflow produces an explicitly labeled unsigned Internal RC and does not create a GitHub Release.
- [ ] GitHub-owned Actions 的版本与最终 Commit SHA Pin 策略已复核。 / GitHub-owned Action versions and the final commit-SHA pinning policy are reviewed.
- [x] 首次公开 Push 的精确文件清单已由产品负责人最终确认。 / The exact first-public-push inventory has final product-owner confirmation.
- [x] 首次公开 `main` Push 已完成；当前源码修复提交为 `3caddb7`，作者使用 GitHub noreply 身份。 / The first public `main` push is complete; the current source-fix commit is `3caddb7` and uses the GitHub noreply author identity.
- [ ] 公开仓库的默认分支、安全设置和 Private Vulnerability Reporting 已人工确认。 / The public repository default branch, security settings, and private vulnerability reporting are manually confirmed.

## 自动证据门 / Automated evidence gates

- [x] Migration Head 为 `0008_workbench_recovery`。 / Migration head is `0008_workbench_recovery`.
- [x] 当前源码自动测试在参考 Windows 主机通过。 / Current source tests pass on the reference Windows host.
- [x] Workbench 真实规模性能基线已生成。 / The realistic Workbench performance baseline is generated.
- [x] 精确 Release Lock、Runtime Inventory、SBOM、Audit 和 Third-party Notice 生成流程存在。 / Exact release lock, runtime inventory, SBOM, audit, and third-party notice generation are available.
- [x] PyInstaller `onedir`、No-UPX、无 Console 构建流程存在。 / The PyInstaller `onedir`, no-UPX, no-console build flow is available.
- [x] Runtime Smoke 与当前 Workbench Packaged Flow 已在开发主机通过。 / Runtime smoke and the current Workbench packaged flow passed on the development host.
- [x] Package Inventory 确认不捆绑 `7z.exe`。 / Package inventory confirms that `7z.exe` is not bundled.
- [x] GitHub Actions CI 已在修复测试主机依赖后远程通过（`3caddb7`：`148 passed, 93 skipped, 1 warning`）。 / GitHub Actions CI passed remotely after isolating the host-dependent test (`3caddb7`: `148 passed, 93 skipped, 1 warning`).
- [ ] GitHub Actions Unsigned Internal RC 首次远程运行通过。 / The first remote GitHub Actions unsigned Internal RC run passes.

## 人工许可证与签名门 / Human license and signing gates

- [ ] `release/THIRD_PARTY-LICENSE-REVIEW.md` 由有权限人员逐项完成并签名。 / An authorized reviewer completes and signs `release/THIRD_PARTY-LICENSE-REVIEW.md` item by item.
- [ ] GPL/LGPL、Qt/PySide、`extract-msg` 及其传递依赖的分发义务已有书面结论。 / Distribution obligations for GPL/LGPL, Qt/PySide, `extract-msg`, and its transitive dependencies have a written conclusion.
- [ ] Authenticode 证书主体、私钥保管、签名步骤和可信时间戳已批准。 / The Authenticode subject, private-key custody, signing procedure, and trusted timestamp are approved.
- [ ] 最终 `PIG.exe` 的 Authenticode 签名验证通过。 / Authenticode verification passes for the final `PIG.exe`.
- [ ] 最终 Portable ZIP、SHA-256、SBOM 和 Notice 之间身份一致。 / The final portable ZIP, SHA-256, SBOM, and notices identify the same build.

## 干净主机与真实格式门 / Clean-host and real-format gates

- [ ] 干净 Windows x64 主机：没有 Python、没有开发目录、没有 7-Zip。 / Clean Windows x64 host: no Python, development tree, or 7-Zip.
- [ ] 无 7-Zip 时 ZIP/7z 正常，RAR 返回受控可解释错误且 Sibling 可用。 / Without 7-Zip, ZIP/7z work while RAR returns a controlled explainable error and siblings remain usable.
- [ ] 标准位置安装批准的 7-Zip 后，真实非敏感 RAR 完成 Inspect、Lazy Materialize、Open 和 Export。 / With an approved standard-location 7-Zip, a real non-sensitive RAR completes inspect, lazy materialize, open, and export.
- [ ] 记录 OS Build、PIG Hash、7-Zip Version/Hash 和 Host Application Version。 / OS build, PIG hash, 7-Zip version/hash, and host-application versions are recorded.
- [ ] 新建 Project 和 W8 `0008` Project 备份副本可重开、编辑、恢复和导出。 / A new Project and a backup copy of a W8 `0008` Project reopen, edit, recover, and export.
- [ ] 最终签名包完成 `docs/application/PIG-V1-desktop-acceptance.md` 的人工流程。 / The final signed package completes the manual flow in `docs/application/PIG-V1-desktop-acceptance.md`.

## 发布判定 / Release decision

任何未完成项都使正式 V1 Release 保持 **BLOCKED**。Unsigned Internal RC 可以用于内部
验证，但不得上传为正式 GitHub Release，不得宣称已签名或已通过许可证审查。

Any incomplete item keeps the official V1 Release **BLOCKED**. An unsigned
Internal RC may be used for internal validation but must not be uploaded as an
official GitHub Release or described as signed or license-approved.
