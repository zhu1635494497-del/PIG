# PIG 第三方许可证人工复核 / Third-Party License Review

- 状态：未完成，阻断正式外发 / Status: incomplete; blocks official distribution
- 输入：`THIRD_PARTY_NOTICES.md`、`THIRD_PARTY_NOTICES.json`、SBOM 和最终 Package Inventory / Inputs: `THIRD_PARTY_NOTICES.md`, `THIRD_PARTY_NOTICES.json`, SBOM, and final package inventory

## 复核规则 / Review rule

自动生成的 License Metadata 只用于定位，不构成法律或合规结论。复核者必须以最终实际
捆绑文件为范围，确认每个组件的 License Text、Copyright、Notice、Source Offer、
Relinking/Replacement 和其他分发义务。本模板不是法律意见。

Generated license metadata is discovery evidence, not a legal or compliance
conclusion. The reviewer must use the final bundled-file inventory and verify
license text, copyright, notice, source-offer, relinking/replacement, and other
distribution obligations for every component. This template is not legal advice.

## 必须单独形成书面结论的依赖 / Dependencies requiring explicit written conclusions

- [ ] `extract-msg` 及其 GPL/LGPL 传递依赖。
- [ ] `pcodedmp` GPL 声明及其是否进入最终 Runtime。
- [ ] `py7zr`、`inflate64`、`multivolumefile`、`pybcj`、`pyppmd` 的 LGPL 条款。
- [ ] `PySide6-Essentials`、`shiboken6` 与 Qt 的 LGPL/GPL 商业分发条件。
- [ ] 外部 7-Zip 的发现、调用和不捆绑结论。
- [ ] Apache-2.0 PIG 自有代码与最终组合分发说明。

- [ ] `extract-msg` and its GPL/LGPL transitive dependencies.
- [ ] The `pcodedmp` GPL declaration and whether it enters the final runtime.
- [ ] LGPL terms for `py7zr`, `inflate64`, `multivolumefile`, `pybcj`, and `pyppmd`.
- [ ] LGPL/GPL commercial-distribution conditions for `PySide6-Essentials`,
  `shiboken6`, and Qt.
- [ ] External 7-Zip discovery, invocation, and non-bundling conclusion.
- [ ] Final combined-distribution notice for Apache-2.0 PIG-owned code.

## 逐项记录 / Item-by-item record

| Package / 组件 | Version / 版本 | Final license conclusion / 最终许可结论 | Required action / 必要动作 | Evidence / 证据 | Reviewed / 已复核 |
|---|---:|---|---|---|---|
| _Complete from final SBOM / 按最终 SBOM 填写_ |  |  |  |  | [ ] |

## 批准 / Approval

- Reviewer / 复核者：
- Authority or role / 权限或角色：
- Review date / 复核日期：
- Final build SHA-256 / 最终构建 SHA-256：
- Decision / 决定：`APPROVED` / `BLOCKED`
- Signature or recorded approval / 签名或留痕批准：
