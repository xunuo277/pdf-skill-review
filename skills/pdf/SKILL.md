---
name: pdf
description: 处理 PDF 的全流程技能：抽取正文/表格、合并拆分旋转、加水印、加解密、导出内嵌图片、对扫描件做 OCR。相比原版增加了"先探测环境、再动手"和"抽取后必须校验"两个硬性环节，避免在缺依赖时反复试错、在表格错位时静默交付错误结果。只要用户提到 .pdf 文件，或要求产出 PDF，就使用本技能。
license: Apache-2.0（衍生自 anthropics/skills，详见 NOTICE.md）
---

# PDF 处理指南（校验优先版）

## 使用前必做两件事

1. **探测环境**：`python scripts/check_env.py --json`
   看 `missing_core` / `missing_ocr`，再决定走哪条路径。不要在缺 `qpdf`、`pdftotext` 时反复试错。
2. **确定输出目录**：所有产物写入 `out/`，**禁止覆盖输入文件**。命名规则 `out/<原名>_<动作>.<ext>`。

> 为什么要有这两条：原版 skill 直接给 `pdftotext`、`qpdf` 命令，但 Windows 默认没有 poppler；
> 而 `extract_tables()` 在合并单元格/跨页表上会"成功返回错位数据"，不校验就等于交付错误。

## 任务 → 工具 决策表

| 任务 | 首选 | 备选 / 降级 |
|---|---|---|
| 读页数、元数据 | `pypdf` | — |
| 抽正文（单栏、版式简单） | `pdftotext -layout` | `pdfplumber` `extract_text()` |
| 抽正文（多栏、需要版面） | `pdfplumber` | `pypdfium2` 渲染后 OCR |
| 抽表格 | `pdfplumber` + **必跑 `verify_tables.py`** | 转图 OCR（无线框表） |
| 合并 / 拆分 / 旋转 / 加密 | `qpdf` | `pypdf`（大文件较慢） |
| 加水印 | `pypdf` `merge_page` | — |
| 从零生成 PDF | `reportlab` | HTML → PDF |
| 导出内嵌图片 | `pdfimages -j` | `pypdfium2` 逐页渲染裁剪 |
| 扫描件 OCR | `pytesseract`（`lang="chi_sim+eng"`） | 无 tesseract 时**直接告知用户**，不要空转 |
| 填表单 | 见 `FORMS.md` | — |

## 核心路径

### 1. 抽取正文

```python
import pdfplumber

with pdfplumber.open("in.pdf") as pdf:
    for i, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        # 先做质量判断，再决定是否需要 OCR
        if len(text.strip()) < 30:
            print(f"p{i} 文本过少（{len(text)} 字），疑似图片型页面 → 走 OCR 分支")
```

**判据**：单页提取字符数 < 30 且页面有图像对象 ⇒ 图片型 PDF，别硬抽，转 OCR。

### 2. 抽取表格（必须校验）

```bash
# 结构风险检查 + 在页面上用红框标出表格位置
python scripts/verify_tables.py in.pdf -p 3-9 -o out
```

脚本会输出：
- `out/in_tables.json`：每张表的行列数、锯齿行数、空单元格比例、`risk: low/medium/high`
- `out/in_p06_tables.png`：原页 + 红框，用来确认"框住的到底是不是表"

**规则**：
- `risk: high` 的表**不得直接交付**。要么打开原页核对，要么用显式线条参数重抽：
  ```python
  pdfplumber.open("in.pdf").pages[0].extract_tables(
      table_settings={"vertical_strategy": "explicit",
                      "explicit_vertical_lines": [x1, x2, ...],
                      "horizontal_strategy": "text"}
  )
  ```
- 跨页表格先按页抽，再按表头字段对齐拼接；不要假设 `extract_tables()` 会跨页。
- 落地为 xlsx 前，先打印前 3 行给人看。字段数对不上就先停下来。

### 3. 扫描件 OCR（中文必须显式指定语言）

```python
import pytesseract
from pdf2image import convert_from_path

images = convert_from_path("scan.pdf", dpi=300)  # dpi 低于 200 中文识别率骤降
text = ""
for i, img in enumerate(images, 1):
    text += f"--- p{i} ---\n"
    text += pytesseract.image_to_string(img, lang="chi_sim+eng", config="--psm 6")
```

- 不写 `lang` 默认只认英文，中文会整段丢失；
- `--psm`：`6` 假定为单块文本（公文/教材常用），`3` 为自动版面分析，表格用 `4`；
- `chi_sim` 未安装时 `check_env.py` 会报 `missing_ocr`，此时应直接告知用户装语言包。

### 4. 页面操作

```bash
qpdf --empty --pages a.pdf b.pdf -- out/merged.pdf      # 合并
qpdf in.pdf --pages . 1-5 -- out/part1.pdf              # 拆分
qpdf in.pdf out/rotated.pdf --rotate=+90:1              # 旋转第 1 页
qpdf --password=PW --decrypt enc.pdf out/dec.pdf        # 解密
```

```python
from pypdf import PdfReader, PdfWriter

wm = PdfReader("watermark.pdf").pages[0]
reader, writer = PdfReader("in.pdf"), PdfWriter()
for page in reader.pages:
    page.merge_page(wm)
    writer.add_page(page)
with open("out/watermarked.pdf", "wb") as f:
    writer.write(f)
```

### 5. 生成 PDF 的两个坑

- **禁用 Unicode 上下标字符**（₀¹²、⁰¹²），reportlab 内置字体没有这些字形，会渲染成黑方块。用 `<sub>` / `<super>` 标签：
  ```python
  from reportlab.platypus import Paragraph
  Paragraph("H<sub>2</sub>O", styles["Normal"])
  ```
- 中文字体需显式注册（如 `STSong-Light` + `UnicodeCIDFont`），否则中文全是方框。

## 交付前自检清单

- [ ] `check_env.py` 报的核心依赖齐全，或已说明降级理由
- [ ] 表格：`verify_tables.py` 无 `high` 风险，或已人工核对
- [ ] OCR：`lang` 已按语种设置，抽样 1 页与原图逐行比对
- [ ] 产物在 `out/`，源文件未被修改
- [ ] 数字类结果（金额、日期、编号）已回原文核对，未凭上下文"推测补全"

## 进一步阅读

- 表单填写：`FORMS.md`
- 进阶 API、JavaScript 方案（pdf-lib）：`REFERENCE.md`
- 上游原版：https://github.com/anthropics/skills/tree/main/skills/pdf
