# PIG V1 发布检查表 / Release Checklist

> 这是 Evidence-oriented Milestone 10 Package 的历史检查表，不是 Workbench Release
> Gate。新的 Release Qualification 从 Workbench W8 开始。
>
> This is the historical checklist for the evidence-oriented Milestone 10
> package, not a Workbench release gate. New release qualification begins at W8.

勾选技术项不能替代尚未完成的人工批准。

A checked technical item does not waive unchecked human approval items.

- [x] Clean Alembic Migration 达到 Schema Head `0005`。<br>
  Clean Alembic migration reaches schema head `0005`.
- [x] Automated Test 在 Windows Reference Host 通过。<br>
  Automated tests pass on the Windows reference host.
- [x] 已记录 10,000-Node Performance Baseline。<br>
  The 10,000-Node performance baseline is captured.
- [x] 已生成 Runtime Dependency Inventory、CycloneDX JSON SBOM 并完成验证。<br>
  Runtime dependency inventory and validated CycloneDX JSON SBOM are generated.
- [x] `pip-audit` 对捕获的 Runtime Set 未发现已知漏洞。<br>
  `pip-audit` found no known vulnerabilities in the captured runtime set.
- [x] PyInstaller `onedir`、Windowed、No-UPX Build 完成。<br>
  The PyInstaller `onedir`, windowed, no-UPX build completed.
- [x] Packaged Runtime Self-test 返回 0。<br>
  The packaged runtime self-test returned exit code 0.
- [x] 旧 V1 Nested Ingestion、Lineage、Search、Controlled Open、Manifest 和 Recovery
  Pre-acceptance 返回 0。<br>
  Historical V1 nested ingestion, Lineage, Search, controlled Open, Manifest,
  and Recovery pre-acceptance returned exit code 0.
- [x] Distribution 中没有 Bundled 7-Zip Binary，并已记录 Build SHA-256/Size。<br>
  Distribution contains no bundled 7-Zip binary and build SHA-256/size are recorded.
- [x] Custom Workspace Root、Safe Layout 和 Project Path 已由 Application/UI Test 覆盖。<br>
  Custom Workspace root, safe layout, and visible Project path are covered.
- [x] ADR-009 Archive Hierarchy、Multi-format Search、Typed Open、Local Event Time 和
  Manifest Confirmation 已覆盖。<br>
  ADR-009 archive hierarchy, multi-format Search, typed Open, local Event time,
  and Manifest confirmation are covered.
- [ ] 使用 Prepared Data 完成新的 Workbench Desktop Acceptance。<br>
  Complete the new Workbench desktop acceptance with prepared data.
- [ ] 人工审查所有 `UNKNOWN` 或不明确 License Metadata。<br>
  Human-review every `UNKNOWN` or ambiguous license metadata entry.
- [ ] 确认 External Distribution 的 Notice/License 义务。<br>
  Confirm notice/license obligations for external distribution.
- [ ] 应用并验证组织批准的 Authenticode Signing。<br>
  Apply and verify organization-approved Authenticode signing.
- [ ] 使用组织 Endpoint Tool 扫描最终 Signed Directory。<br>
  Scan the final signed directory with organization endpoint tooling.
- [ ] 在干净 Windows VM 测试 Copy/Launch/Processing/Recovery/Uninstall。<br>
  Test copy, launch, processing, recovery, and uninstall on a clean Windows VM.
- [ ] 分别在 Native macOS 和 Linux 构建并验证。<br>
  Build and verify separately on native macOS and Linux.

外部分发状态：在适用的未勾选 Gate 完成前为 **BLOCKED**。

External distribution status: **BLOCKED** until applicable unchecked gates are
complete.

本检查表对应旧 Package。ADR-010 之后的 Workbench 不兼容旧 Project，必须在 W8
生成新的 Build Report 和 Release Checklist。

This checklist belongs to the historical package. The ADR-010 Workbench does
not support old Projects and must produce a new build report and checklist at W8.
