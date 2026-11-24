# PDF Skill 评审与改进 / pdf-skill-review

一次技能（Agent Skill）推荐作业：我推荐 Anthropic 官方仓库中的 **`pdf` skill**，并给出它的改进方案与可运行的验证脚本。

- 原始仓库：<https://github.com/anthropics/skills>
- 被推荐的 skill 目录：<https://github.com/anthropics/skills/tree/main/skills/pdf>

---

## 一、这个 skill 能解决我的什么问题

我日常处理 PDF 的痛点非常具体，都属于"信息被锁在页面里"这一类：

| 痛点 | 手工的代价 | 这个 skill 给出的路径 |
|---|---|---|
| 复制文本格式全乱，多栏排版塌成一行 | 逐段重排，一份 20 页资料要半小时 | `pdfplumber.extract_text()` 按版面取字 |
| 扫描件根本无法复制的文字（图片型 PDF） | 只能一页页肉眼读入 | `pdf2image` + `pytesseract` OCR 成可检索文本 |
| 表格要重新录入 Excel | 几十行手工敲，必错行 | `extract_tables()` 直接落 `xlsx` |
| 拆分 / 合并 / 加水印 / 去密码 | 找在线工具，还得上传文件 | `qpdf`、`pypdf` 本地完成，不出网 |

对我来说真正省下的不是"写代码的时间"，而是**找工具、试参数、反复对格式**的时间；而且整个链路在本地跑，敏感文件不必上传第三方网站。

它设计上有一点值得单独学：主 `SKILL.md` 只放高频路径，表单场景拆到 `FORMS.md`，进阶 API 拆到 `REFERENCE.md`——**渐进式加载**，按需读取，不一次性把知识全塞进上下文。

## 二、GitHub 网址

```
https://github.com/anthropics/skills/tree/main/skills/pdf
```

- 上级仓库：`anthropics/skills`，含 `docx` / `pdf` / `pptx` / `xlsx` 四个文档技能、`spec` 规范、`template` 模板
- 许可证：Apache-2.0，可自由阅读、修改、二次分发
- 身份：它也是 Claude 文档能力背后的实际实现，属于"生产在用"而非玩具示例

## 三、我认为需要改进的地方

### ① 依赖没有前置探测，Windows 上第一步就会失败

`SKILL.md` 直接给出 `pdftotext`、`qpdf`、`pdfimages` 命令，却没说"先检测二进制是否存在"。poppler 在 Windows 默认没有，模型会很自然地敲一条命令、吃到报错、再猜着换方案，白白消耗好几轮。

**改进**：新增 [`skills/pdf/scripts/check_env.py`](skills/pdf/scripts/check_env.py)——开跑前输出可用能力清单、缺失项、以及每项的纯 Python 降级路径，`--json` 供 agent 直接决策。

```bash
python skills/pdf/scripts/check_env.py --json
# {"ok": false, "missing_core": ["pdfplumber"], "missing_ocr": ["chi_sim"], "advice": [...]}
```

### ② 表格抽取缺少校验闭环（最危险的一点）

合并单元格、跨页表格、无线框表格上，`extract_tables()` 会**安静地返回错位的行列**：不抛异常，后面 `to_excel` 照样落地，人还以为成功了。这是"看起来跑通了、结果却是错的"的典型场景，也正是技能最该兜住的地方。

值得注意的是，仓库里已经有 `scripts/create_validation_image.py`，但只服务于表单填写，没有扩展到表格/正文抽取。

**改进**：新增 [`skills/pdf/scripts/verify_tables.py`](skills/pdf/scripts/verify_tables.py)，把校验变成强制步骤：

- 结构层：行列数、锯齿行、空单元格比例 → 给出 `risk: low/medium/high`
- 视觉层：渲染原页并在表格 bbox 上画红框，产出 `out/in_p06_tables.png`，确认"框住的到底是不是表"
- 高风险表给出显式线条重抽的代码模板（`explicit_vertical_lines`）

```bash
python skills/pdf/scripts/verify_tables.py report.pdf -p 3-9 -o out
```

### ③ OCR 段落太单薄，中文场景近乎不可用

原版只给了 `pytesseract.image_to_string(image)` 的默认写法，没提：

- `lang="chi_sim+eng"`——不写就只认英文，中文整段丢失；
- `dpi`——低于 200 时中文识别率骤降；
- `--psm`——公文/教材适合 `6`，表格适合 `4`。

**改进**：在 `SKILL.md` 的 OCR 段落中写死这三项，并让 `check_env.py` 顺带探测 `chi_sim` 语言包是否存在；缺失时要求**直接告知用户装包**，而不是让模型空转重试。

### ④ 上下文成本还能再降

主文件里有不少完整样板代码（例如 reportlab 的 hello world），对模型而言属于常识，却占用每次触发的固定 token。建议把"任务 → 工具"决策表前置为主体，代码片段按需从子文档取——本次改进版已按此调整。

### ⑤ 缺少"不覆盖输入"的硬约束

示例输出文件名（`merged.pdf`、`rotated.pdf`）随手起，连续操作时产物散落、甚至可能与源文件重名。改进版统一约定：产物写入 `out/`、命名 `out/<原名>_<动作>.<ext>`、**禁止写入源文件路径**，并在 `verify_tables.py` 中用代码强制拒绝输出到源目录。

---

## 仓库结构

```
pdf-skill-review/
├── README.md                     # 本文：推荐理由 + 改进方案
├── NOTICE.md                     # 衍生声明与许可
└── skills/pdf/
    ├── SKILL.md                  # 改进版技能说明（决策表 + 校验闭环 + 硬约束）
    └── scripts/
        ├── check_env.py          # 环境能力探测（改进点 ①③）
        └── verify_tables.py      # 表格抽取校验（改进点 ②⑤）
```

## 如何试用

```bash
pip install pypdf pdfplumber pandas pyyaml
python skills/pdf/scripts/check_env.py            # 先看环境
python skills/pdf/scripts/verify_tables.py 你的文件.pdf -o out
```

## 说明

`SKILL.md` 中的基础用法（pypdf / pdfplumber / reportlab / qpdf 命令）整理自上游 `anthropics/skills`（Apache-2.0），本仓库的工作是**评审 + 补齐环境探测与校验环节**，未复制其 `FORMS.md`、`REFERENCE.md` 与脚本。
