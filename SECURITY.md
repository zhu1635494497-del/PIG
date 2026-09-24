# PIG 安全策略 / PIG Security Policy

## 支持状态 / Supported status

PIG 目前处于 V1 Release Qualification。`main` 是开发分支，尚无正式签名的公共二进制
版本。正式 Release 后，仅最新受支持版本接收安全修复，具体范围会在本文件更新。

PIG is currently in V1 Release Qualification. `main` is a development branch and
there is no officially signed public binary yet. After the first official
Release, only the latest supported version will receive security fixes; this
file will be updated with the exact support window.

## 报告漏洞 / Reporting a vulnerability

请使用仓库的 GitHub **Private vulnerability reporting / Security Advisory** 私下报告安全
问题。不要先创建公开 Issue，也不要上传真实业务文件、Project 数据库、邮件、附件、
日志全文、客户名称、内部路径、凭据或签名材料。

Please report vulnerabilities privately through the repository's GitHub
**Private vulnerability reporting / Security Advisory** feature. Do not begin
with a public Issue and do not upload real business files, Project databases,
email, attachments, complete logs, customer names, internal paths, credentials,
or signing material.

报告中请包含最小复现步骤、受影响版本、预期与实际行为，以及不含敏感数据的测试样例。
维护者会先确认收到，再评估严重性、修复范围和披露时间。不要在修复或缓解措施可用前
公开细节。

Include minimal reproduction steps, the affected version, expected and actual
behavior, and a synthetic non-sensitive fixture. Maintainers will acknowledge
the report, assess severity and scope, and coordinate disclosure timing. Do not
publish details before a fix or mitigation is available.

## 重点安全边界 / Key security boundaries

PIG 把所有导入文件视为不可信，集中限制 Path Traversal、Archive Bomb、Symbolic Link、
恶意名称、深度、数量和大小。Original Snapshot 不可变；外部打开受格式策略控制；RAR
仅使用经过校验的外部 7-Zip，PIG 不捆绑 `7z.exe`。

PIG treats every imported file as untrusted and centrally limits path traversal,
archive bombs, symbolic links, malicious names, depth, count, and size. Original
Snapshots are immutable, external opening is format-controlled, and RAR uses
only a validated external 7-Zip that PIG does not bundle.
