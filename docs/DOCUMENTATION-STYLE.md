# PIG 文档双语规范 / PIG Bilingual Documentation Standard

- 状态：当前有效 / Status: Active
- 日期：2026-09-21 / Date: 2026-09-21

## 1. 适用范围 / Scope

所有 PIG 自有 Markdown 文档必须同时提供中文和英文。代码标识符、枚举值、
路径、命令、Schema 名称和第三方产品名称保持原样。

All first-party PIG Markdown documents must provide both Chinese and English.
Code identifiers, enum values, paths, commands, schema names, and third-party
product names remain unchanged.

第三方许可证、版权声明和自动生成的依赖 Notice 不得翻译或改写，以免改变其
法律含义。

Third-party licenses, copyright notices, and generated dependency notices must
not be translated or rewritten because doing so could alter their legal meaning.

## 2. 当前有效文档 / Active documents

当前有效的产品、ADR、领域、状态机、里程碑和验收文档应采用“中文在前、英文
紧随其后”的双语结构。两种语言具有同等规范效力；发生歧义时先修正文档，不得
由实现自行选择有利解释。

Active product, ADR, domain, state-machine, milestone, and acceptance documents
use Chinese first with English immediately following. Both languages are equally
normative. If they diverge, fix the document rather than letting implementation
choose a convenient interpretation.

## 3. 历史文档 / Historical documents

历史实现文档保留原始技术正文，并在文首提供中英文状态、适用边界和中文内容
摘要。历史正文只用于代码考古，不得覆盖当前 Workbench 规范。

Historical implementation documents retain their original technical body and
provide bilingual status, applicability, and a Chinese content summary at the
top. The historical body is for code archaeology and never overrides the active
Workbench specification.

## 4. 写作格式 / Writing format

- 标题格式：`中文标题 / English Title`。
- 短规则：中文段落后紧跟英文段落。
- 表格：列标题双语；单元格可用 `<br>` 分隔中英文。
- 代码块只写一次，在前后双语正文中共同引用。
- `MUST`、`MUST NOT`、`SHOULD` 等约束词在中文中使用“必须”“不得”“应该”。

- Title format: `中文标题 / English Title`.
- Short rules: English paragraph immediately follows the Chinese paragraph.
- Tables: bilingual headers; cells may separate languages with `<br>`.
- Code blocks appear once and are referenced by both language paragraphs.
- Normative words such as `MUST`, `MUST NOT`, and `SHOULD` map to clear Chinese
  terms such as “必须”, “不得”, and “应该”.

## 5. 变更检查 / Change check

修改规范性内容时必须同步修改两种语言，并检查领域术语、状态名、事件名、路径和
验收条件是否一致。

When normative content changes, update both languages and verify that domain
terms, state names, event names, paths, and acceptance conditions remain aligned.
