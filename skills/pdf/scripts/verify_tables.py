#!/usr/bin/env python3
"""表格抽取校验 / Table-extraction verification loop.

解决的问题：extract_tables() 在合并单元格、跨页表格、无线框表格上会"安静地"
返回错位的行列——代码不报错，结果却已经错了。本脚本给出可视化+结构双重校验，
让"抽取是否可信"成为一个可检查的步骤，而不是一个假设。

输出（默认写入 ./out/，绝不覆盖源文件）：
  out/<name>_p06_tables.png   页面上用红框标出每个表格的 bbox，供人眼/模型比对
  out/<name>_tables.json      每页每个表格的行列数、锯齿行、空单元格比例、风险等级

用法:
    python verify_tables.py in.pdf                 # 全部页
    python verify_tables.py in.pdf -p 3-7          # 指定页
    python verify_tables.py in.pdf --json          # 只输出 JSON 摘要
    python verify_tables.py in.pdf --no-image      # 跳过渲染（仅结构检查）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ------------------------------------------------------------------ 结构检查
@dataclass
class TableReport:
    page: int
    index: int
    rows: int
    cols_max: int
    cols_min: int
    ragged_rows: int            # 列数与该表众数不一致的行
    empty_ratio: float          # 空单元格比例
    bbox: list[float]
    risk: str                   # low / medium / high
    reasons: list[str] = field(default_factory=list)


def _analyze(page: int, idx: int, table: list[list[str | None]], bbox) -> TableReport:
    rows = len(table)
    widths = [len(r) for r in table] or [0]
    cols_max, cols_min = max(widths), min(widths)
    mode = max(set(widths), key=widths.count) if widths else 0
    ragged = sum(1 for w in widths if w != mode)

    cells = [c for r in table for c in r]
    empty = sum(1 for c in cells if c is None or str(c).strip() == "")
    empty_ratio = round(empty / len(cells), 3) if cells else 1.0

    reasons: list[str] = []
    if rows <= 1:
        reasons.append("只有 1 行，可能把表头/装饰线误判为表格")
    if ragged:
        reasons.append(f"{ragged} 行列数与众数 {mode} 不一致，疑似合并单元格或串行")
    if empty_ratio > 0.35:
        reasons.append(f"空单元格占比 {empty_ratio:.0%}，疑似误识别或跨页断裂")
    if cols_max > 20:
        reasons.append(f"列数 {cols_max} 异常偏多，可能把正文按空格切成了多列")

    high = len(reasons) >= 2 or empty_ratio > 0.6 or rows <= 1
    risk = "high" if high else ("medium" if reasons else "low")
    return TableReport(
        page=page,
        index=idx,
        rows=rows,
        cols_max=cols_max,
        cols_min=cols_min,
        ragged_rows=ragged,
        empty_ratio=empty_ratio,
        bbox=[round(float(v), 1) for v in bbox],
        risk=risk,
        reasons=reasons,
    )


# ------------------------------------------------------------------ 渲染与标注
def _render_page(pdf_path: Path, page_no: int, scale: float = 2.0):
    """把第 page_no 页渲染为 PIL.Image（1-based）。优先 pypdfium2，回退 pdf2image。"""
    try:
        import pypdfium2 as pdfium  # type: ignore

        pdf = pdfium.PdfDocument(str(pdf_path))
        bitmap = pdf[page_no - 1].render(scale=scale)
        return bitmap.to_pil()
    except Exception:
        pass
    try:
        from pdf2image import convert_from_path  # type: ignore

        imgs = convert_from_path(
            str(pdf_path), dpi=int(72 * scale), first_page=page_no, last_page=page_no
        )
        return imgs[0]
    except Exception:
        return None


def _annotate(img, boxes: list[tuple[list[float], int]], page=None):
    """在渲染图上画红框。PDF 坐标原点在左下，图像原点在左上，需翻转 y。"""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    sx = img.width / float(page.width) if page is not None else 1.0
    sy = img.height / float(page.height) if page is not None else 1.0
    for bbox, idx in boxes:
        x0, top, x1, bottom = bbox
        if page is not None:
            top, bottom = page.height - bottom, page.height - top
        rect = [x0 * sx, top * sy, x1 * sx, bottom * sy]
        draw.rectangle(rect, outline=(220, 38, 38), width=3)
        draw.text((rect[0] + 6, max(rect[1] - 16, 0)), f"table #{idx}", fill=(220, 38, 38))
    return img


# ------------------------------------------------------------------ 主流程
def run(
    pdf_path: Path,
    pages: str | None,
    out_dir: Path,
    make_image: bool,
    scale: float,
) -> dict:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        print(
            "缺少 pdfplumber，无法做表格检查。请先: pip install pdfplumber",
            file=sys.stderr,
        )
        raise SystemExit(2)

    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[TableReport] = []
    images: list[str] = []
    warnings: list[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        total = len(pdf.pages)
        want = set(range(1, total + 1))
        if pages:
            want = set()
            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    want |= set(range(int(a), int(b) + 1))
                elif part:
                    want.add(int(part))
        want = {p for p in want if 1 <= p <= total}

        for pno in sorted(want):
            page = pdf.pages[pno - 1]
            try:
                tables = page.find_tables()
            except Exception as exc:  # 表格检测本身可能失败，不应中断全文
                warnings.append(f"第 {pno} 页表格检测失败: {exc}")
                continue
            if not tables:
                continue

            boxes: list[tuple[list[float], int]] = []
            for i, t in enumerate(tables, 1):
                data = t.extract()
                rep = _analyze(pno, i, data or [], t.bbox)
                reports.append(rep)
                if rep.risk != "low":
                    warnings.append(
                        f"第 {pno} 页表格#{i} 风险 {rep.risk}: " + "；".join(rep.reasons)
                    )
                boxes.append((list(t.bbox), i))

            if make_image:
                img = _render_page(pdf_path, pno, scale=scale)
                if img is None:
                    warnings.append(f"第 {pno} 页渲染失败（缺 pypdfium2/pdf2image），已跳过校验图")
                else:
                    img = _annotate(img, boxes, page)
                    target = out_dir / f"{pdf_path.stem}_p{pno:02d}_tables.png"
                    img.save(target)
                    images.append(str(target))

    summary = {
        "source": str(pdf_path.resolve()),
        "pages_checked": sorted(want),
        "table_count": len(reports),
        "high_risk": [f"p{r.page}#{r.index}" for r in reports if r.risk == "high"],
        "medium_risk": [f"p{r.page}#{r.index}" for r in reports if r.risk == "medium"],
        "warnings": warnings,
        "images": images,
        "tables": [asdict(r) for r in reports],
        "next_step": (
            "先看 images 里的红框是否真的框住了表格；对 high_risk 的表必须打开原页人工核对，"
            "或改用 extra_table_settings（explicit vertical/horizontal lines）重抽。"
            if reports
            else "未检测到表格；若人工能看到表格，属无线框表，请改用 explicit 线条参数或转图后 OCR。"
        ),
    }
    (out_dir / f"{pdf_path.stem}_tables.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="表格抽取校验：结构风险 + 可视化标注")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("-p", "--pages", default=None, help="如 3-7 或 1,4,9")
    ap.add_argument("-o", "--out", type=Path, default=Path("out"))
    ap.add_argument("--no-image", action="store_true", help="跳过渲染标注图")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"文件不存在: {args.pdf}", file=sys.stderr)
        return 1
    if args.out.resolve() == args.pdf.parent.resolve():
        print("拒绝直接写入源文件目录，请用 -o 指定独立输出目录", file=sys.stderr)
        return 1

    summary = run(args.pdf, args.pages, args.out, not args.no_image, args.scale)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"检查页: {summary['pages_checked']}  表格数: {summary['table_count']}")
        for w in summary["warnings"]:
            print("  ! " + w)
        print(summary["next_step"])
        for img in summary["images"]:
            print("  图: " + img)
    return 0


if __name__ == "__main__":
    sys.exit(main())
