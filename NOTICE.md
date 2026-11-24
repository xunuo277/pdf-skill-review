# NOTICE

本仓库是以下开源项目的评审与衍生作品：

- 上游：**anthropics/skills**
  - 仓库：https://github.com/anthropics/skills
  - 被评审目录：https://github.com/anthropics/skills/tree/main/skills/pdf
  - 许可证：Apache License 2.0

## 本仓库新增内容（原创作）

| 文件 | 说明 |
|---|---|
| `README.md` | 对上游 `pdf` skill 的推荐说明与改进分析 |
| `skills/pdf/SKILL.md` | 重写的技能说明：前置环境探测、任务决策表、抽取校验闭环、输出目录与不覆盖输入约束 |
| `skills/pdf/scripts/check_env.py` | 环境能力探测脚本（新增） |
| `skills/pdf/scripts/verify_tables.py` | 表格抽取结构与可视化双重校验脚本（新增） |

## 引用与边界

- 上游以 Apache-2.0 发布，本仓库对其中基础 API 用法的整理遵循同一许可。
- 本仓库**未包含**上游的 `FORMS.md`、`REFERENCE.md`、`LICENSE.txt` 及 `scripts/` 下原有脚本；如需完整能力，请直接使用上游仓库。
- 上游 README 声明其技能"仅用于演示与教学目的"，本仓库同样仅供参考，请在自身环境中充分测试后再用于关键任务。
