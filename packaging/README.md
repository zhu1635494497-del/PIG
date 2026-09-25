# PIG Workbench W9 打包 / PIG Workbench W9 Packaging

## 发布边界 / Release boundary

Windows 包使用 PyInstaller `onedir`、`console=False`、`upx=False`。PyInstaller 不是
交叉编译器，因此必须在目标操作系统构建。ZIP 使用 Python 标准库，7z 使用 `py7zr`；
RAR 只调用用户或管理员已安装且通过校验的外部 7-Zip，安装包不得捆绑 `7z.exe`。

The Windows package uses PyInstaller `onedir`, `console=False`, and `upx=False`.
PyInstaller is not a cross-compiler, so builds must run on the target OS. ZIP
uses the Python standard library and 7z uses `py7zr`; RAR uses only a validated,
operator-installed external 7-Zip. The package must not bundle `7z.exe`.

候选版使用标准语义化 Git Tag，例如 `v1.0.0-rc.1`；Python 包元数据使用
对应的 PEP 440 版本 `1.0.0rc1`。GitHub Release 必须标记为 Pre-release，资产名称
保留 `-unsigned`，直到签名和其他人工 Gate 全部完成。

Candidates use standard semantic Git tags such as `v1.0.0-rc.1`, with the
corresponding PEP 440 package version `1.0.0rc1`. The GitHub Release must be
marked as a pre-release and asset names retain `-unsigned` until signing and all
other human gates are complete.

## 可复现输入与证据 / Reproducible inputs and evidence

在干净的 Python 3.10 环境安装精确锁文件，再生成 runtime requirements、第三方声明、
SBOM 和漏洞审计：

Install the exact lock in a clean Python 3.10 environment, then regenerate the
runtime requirements, notices, SBOM, and vulnerability audit:

```powershell
python -m pip install -r release\requirements-release.lock
python -m pip install --no-deps -e .
python tools\generate_release_metadata.py --output-dir release
cyclonedx-py requirements release\requirements-runtime.txt --pyproject pyproject.toml --output-reproducible --of JSON -o release\pig-runtime.cdx.json
pip-audit -r release\requirements-runtime.txt --format json --output release\pip-audit.json
```

锁文件固定版本但不固定 wheel Hash；需要更高供应链等级的外部分发，必须另行生成并
复核目标平台 Hash Lock。

The lock pins versions but not wheel hashes. External distribution requiring a
stronger supply-chain level must additionally generate and review a
target-specific hash-pinned lock.

## Windows 构建与机器验收 / Windows build and machine acceptance

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist\workbench-w9 --workpath build\workbench-w9 packaging\PIG.spec
$runtime = Start-Process .\dist\workbench-w9\PIG\PIG.exe -ArgumentList '--runtime-smoke-test' -WindowStyle Hidden -Wait -PassThru
$runtime.ExitCode
$acceptanceRoot = Join-Path (Resolve-Path '.') 'acceptance\workbench-w9'
$flow = Start-Process .\dist\workbench-w9\PIG\PIG.exe -ArgumentList @('--acceptance-smoke-test',$acceptanceRoot) -WindowStyle Hidden -Wait -PassThru
$flow.ExitCode
.\.venv\Scripts\python.exe tools\generate_release_metadata.py --output-dir release --distribution-dir dist\workbench-w9\PIG
```

`--runtime-smoke-test` 和 `--acceptance-smoke-test` 均运行当前 Workbench 闭环：项目创建、
文件夹导入、结构树、Working 物化/修改、保结构导出、恢复与重新打开。它们不替代
干净虚拟机和人工 GUI 验收。

Both smoke modes exercise the current Workbench loop: Project creation, folder
import, structure tree, Working materialization/edit, structure-preserving
export, recovery, and reopen. They do not replace clean-VM or manual GUI
acceptance.

## 发布门 / Release gates

必须使用 `release/WORKBENCH-W9-RELEASE-CHECKLIST.md`。在人工许可证复核、代码签名、
干净 Windows 主机测试和桌面人工验收完成前，构建状态只能是 Unsigned Internal RC。

Use `release/WORKBENCH-W9-RELEASE-CHECKLIST.md`. Until human license review,
code signing, clean-Windows-host testing, and manual desktop acceptance are
complete, the build is an unsigned Internal RC only.

GitHub Actions 的 `unsigned-release-candidate.yml` 复用相同输入，只生成短期 Artifact；
它不创建 GitHub Release，也不接触 Authenticode 私钥。

The GitHub Actions `unsigned-release-candidate.yml` workflow reuses the same
inputs and produces only a short-lived artifact. It does not create a GitHub
Release or access an Authenticode private key.

## 下载包边界 / Download-package boundary

PyInstaller 运行目录只嵌入程序启动所需的 Alembic 配置与明确列出的 Migration 文件。
候选 ZIP 在独立 Staging 目录组装，并在根目录额外放置 `README.md`、`LICENSE`、
`NOTICE`、第三方声明、SBOM 和漏洞审计结果。源码、测试、本地 Project、Acceptance、
Build Cache 和内部发布检查表不得进入下载 ZIP。

The PyInstaller runtime embeds only the Alembic configuration and explicitly
listed migration files needed to start the application. The candidate ZIP is
assembled in a separate staging directory and adds `README.md`, `LICENSE`,
`NOTICE`, third-party notices, the SBOM, and vulnerability-audit output at its
root. Source, tests, local Projects, acceptance data, build caches, and internal
release checklists must not enter the download ZIP.
