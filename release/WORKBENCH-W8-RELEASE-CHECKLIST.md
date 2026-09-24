# PIG Workbench W8 发布检查表 / Release Checklist

- 状态：内部验收包门；外部分发未批准 / Status: internal acceptance package gate; external distribution not approved
- 构建模式：Windows `onedir`，UPX 关闭，GUI 无控制台 / Build mode: Windows `onedir`, UPX disabled, GUI without console

## 自动证据 / Automated evidence

- [x] Migration Head 为 `0008_workbench_recovery`。 / Migration head is `0008_workbench_recovery`.
- [x] W8 Recovery、UI 与打包闭环自动测试通过。 / W8 recovery, UI, and packaged-flow automated tests pass.
- [x] 正式 Workbench 性能基线运行 3 次并记录中位数。 / Formal Workbench benchmark ran three times and records medians.
- [x] Runtime SBOM 已生成。 / Runtime SBOM is generated.
- [x] `pip-audit` 证据已生成且当前无已知漏洞。 / `pip-audit` evidence is generated with no currently known vulnerabilities.
- [x] 第三方组件声明已生成。 / Third-party notices are generated.
- [x] Windows onedir 构建、Runtime Smoke、Workbench Packaged Flow 和文件清单全部成功。 / Windows onedir build, runtime smoke, Workbench packaged flow, and file inventory all succeed.
- [x] 文件清单确认没有捆绑 `7z.exe`。 / File inventory confirms that `7z.exe` is not bundled.

## 人工发布门 / Human release gates

- [ ] 人工复核所有第三方许可证与 Notice。 / Human review of every third-party license and notice is complete.
- [ ] 明确代码签名证书、签名主体和时间戳策略。 / Code-signing certificate, signer identity, and timestamp policy are defined.
- [ ] 在干净 Windows 主机安装/解压并完成 W8 桌面验收。 / W8 desktop acceptance completes on a clean Windows host.
- [ ] 验证没有安装 7-Zip 时 ZIP/7z 正常、RAR 给出受控错误。 / Without 7-Zip, ZIP/7z work and RAR returns a controlled error.
- [ ] 验证标准位置安装 7-Zip 时 RAR 成功并记录 Version/SHA-256。 / With 7-Zip in a standard location, RAR succeeds and records Version/SHA-256.
- [ ] 产品负责人明确批准外部分发。 / Product owner explicitly approves external distribution.

## 阻断条件 / Blocking conditions

任何未完成的人工发布门、审计发现、清单中出现捆绑 `7z.exe`、恢复可能覆盖已知 Working
字节，或打包流程仍调用历史 Evidence Contract，均阻断外部分发。

External distribution is blocked by any incomplete human gate, audit finding,
bundled `7z.exe`, recovery behavior that can overwrite known Working bytes, or a
packaged flow that still invokes the historical Evidence contract.
