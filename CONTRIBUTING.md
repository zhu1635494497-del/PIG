# 为 PIG 贡献 / Contributing to PIG

## 中文

感谢参与 PIG。提交变更前请先阅读：

1. `PIG Project Rules.md`；
2. `docs/PIG-V1-planning-index.md`；
3. 与变更相关的当前 ADR、领域和 Milestone 文档。

贡献必须遵守以下边界：

- 先说明 Domain、Flow、State、Lineage、Log、Permission、Tool、AI、Automation 和 UI
  影响；
- 不得越过当前授权 Milestone，或静默改变已经批准的 ADR；
- 不得提交真实客户文件、Project SQLite、验收输出、日志、密钥、证书或本机路径；
- PIG 自有 Markdown 必须同步提供中文和英文；
- 新行为必须有与风险相称的自动化测试；
- 不得为当前无价值的 AI、微服务、消息队列或其他平台扩大范围。

建议流程：先创建说明问题和边界的 Issue，再从短生命周期分支提交 Pull Request。PR
应说明测试命令、结果、未闭环边界和安全影响。涉及核心领域、数据库、GUI Framework、
Original Policy、Workspace Layout、AI Framework 或发布安全的变化必须先提出 ADR。

## English

Thank you for contributing to PIG. Before changing the repository, read:

1. `PIG Project Rules.md`;
2. `docs/PIG-V1-planning-index.md`;
3. the active ADR, domain, and milestone documents relevant to the change.

Contributions must follow these boundaries:

- state Domain, Flow, State, Lineage, Log, Permission, Tool, AI, Automation, and
  UI impact first;
- do not cross the authorized milestone or silently override an accepted ADR;
- never commit real customer files, Project SQLite databases, acceptance output,
  logs, keys, certificates, or local paths;
- keep all first-party PIG Markdown synchronized in Chinese and English;
- cover new behavior with tests proportionate to its risk;
- do not expand into premature AI, microservices, message queues, or other
  platforms without current product value.

Prefer an Issue that defines the problem and boundary, followed by a short-lived
branch and Pull Request. The PR should report test commands/results, remaining
gaps, and safety impact. Changes to the core domain, database, GUI framework,
Original Policy, Workspace Layout, AI framework, or release security require an
ADR first.
