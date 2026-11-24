#!/usr/bin/env python3
"""环境能力探测 / Environment capability probe.

在动手处理任何 PDF 之前先跑一遍，输出"哪些能力可用 / 缺什么 / 用什么降级"。
目的是避免模型在缺失二进制时反复试错（例如 Windows 上默认没有 poppler）。

用法:
    python check_env.py            # 人类可读表格
    python check_env.py --json     # 机器可读，便于 agent 决策

退出码: 始终为 0（探测不是断言），是否可继续由调用方根据输出决定。
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
from dataclasses import dataclass, asdict

# ---------------------------------------------------------------- 依赖清单
# (显示名, import 名, 重要性, 提供的能力, 缺失时的降级方案)
PY_LIBS = [
    ("pypdf", "pypdf", "core", "页数/合并/拆分/旋转/加密/元数据", "无替代，建议 pip install pypdf"),
    ("pdfplumber", "pdfplumber", "core", "按版面抽取文本与表格", "降级到 pdftotext -layout（无表格结构）"),
    ("reportlab", "reportlab", "optional", "从零生成 PDF", "降级到 html->PDF 或 docx 转换"),
    ("pypdfium2", "pypdfium2", "optional", "渲染页面为图片", "降级到 pdf2image（需 poppler）"),
    ("pdf2image", "pdf2image", "optional", "PDF 转图片（OCR 前置）", "需 poppler；无则改用 pypdfium2"),
    ("pytesseract", "pytesseract", "ocr", "OCR 识别", "需 tesseract 二进制；无则无法 OCR"),
    ("pandas", "pandas", "optional", "表格落地为 xlsx/csv", "降级到 csv 标准库"),
    ("PIL", "PIL", "optional", "图像后处理/校验图标注", "无则跳过可视化校验"),
]

# (命令名, 重要性, 提供的能力, 缺失时的降级方案)
BINARIES = [
    ("pdftotext", "optional", "快速纯文本抽取（poppler-utils）", "用 pdfplumber 代替"),
    ("pdftoppm", "optional", "PDF 转图（poppler-utils）", "用 pypdfium2 代替"),
    ("pdfimages", "optional", "批量导出内嵌图片（poppler-utils）", "用 pypdfium2 逐页渲染后裁剪"),
    ("qpdf", "optional", "命令行合并/拆分/解密，速度快、体积小", "用 pypdf 代替（大文件较慢）"),
    ("pdftk", "optional", "表单与页面操作", "用 pypdf + pdf-lib 代替"),
    ("tesseract", "ocr", "OCR 引擎", "无则无法处理扫描件，只能提示用户"),
    ("soffice", "optional", "Office 文档互转", "无则跳过转换链路"),
]

_ZH_ALIAS = {"chi_sim", "chi_tra", "chi_sim_vert", "chi_tra_vert"}


@dataclass
class Item:
    kind: str          # lib / bin / ocr-lang
    name: str
    ok: bool
    level: str
    provides: str
    fallback: str


def _check_lib(import_name: str) -> bool:
    try:
        importlib.import_module(import_name)
        return True
    except Exception:
        return False


def _tesseract_langs() -> list[str]:
    """读取 tesseract 已安装语言包；未安装引擎则返回空。"""
    if not shutil.which("tesseract"):
        return []
    try:
        import subprocess

        out = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15
        )
        lines = [ln.strip() for ln in (out.stdout or "").splitlines()]
        return [ln for ln in lines[1:] if ln and " " not in ln]
    except Exception:
        return []


def probe(with_ocr_langs: bool = True) -> list[Item]:
    items: list[Item] = []
    for disp, imp, level, provides, fallback in PY_LIBS:
        items.append(Item("lib", disp, _check_lib(imp), level, provides, fallback))
    for cmd, level, provides, fallback in BINARIES:
        items.append(Item("bin", cmd, shutil.which(cmd) is not None, level, provides, fallback))
    if with_ocr_langs:
        langs = _tesseract_langs()
        for lang in ("eng", "chi_sim"):
            items.append(
                Item(
                    "ocr-lang",
                    lang,
                    lang in langs,
                    "ocr" if lang == "chi_sim" else "optional",
                    f"OCR 语言包 {lang}",
                    "无则中文扫描件会大面积漏字，需安装对应 traineddata"
                    if lang == "chi_sim"
                    else "无则英文 OCR 不可用",
                )
            )
        if langs:
            zh = sorted(set(langs) & _ZH_ALIAS)
            items.append(
                Item(
                    "ocr-lang",
                    "中文语言包总览",
                    bool(zh),
                    "ocr",
                    f"已安装中文包: {', '.join(zh) if zh else '无'}",
                    "建议 tesseract 追加 chi_sim",
                )
            )
    return items


def to_json(items: list[Item]) -> str:
    missing_core = [i.name for i in items if not i.ok and i.level == "core"]
    missing_ocr = [i.name for i in items if not i.ok and i.level == "ocr"]
    payload = {
        "ok": not missing_core,
        "missing_core": missing_core,
        "missing_ocr": missing_ocr,
        "items": [asdict(i) for i in items],
        "advice": _advice(missing_core, missing_ocr),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _advice(missing_core: list[str], missing_ocr: list[str]) -> list[str]:
    tips: list[str] = []
    if missing_core:
        tips.append("安装核心依赖后再继续: pip install " + " ".join(missing_core))
    if "pdfplumber" in missing_core:
        tips.append("表格抽取不可用；若只需正文文本，可走 pdftotext -layout 降级路径。")
    if missing_ocr:
        tips.append("OCR 链路不完整；遇到纯图片型 PDF 应直接告知用户而非空转重试。")
    if not tips:
        tips.append("核心能力齐全，可直接按 SKILL.md 主路径处理。")
    return tips


def print_table(items: list[Item]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(title="PDF 环境能力探测", show_lines=False)
        table.add_column("类型", style="dim")
        table.add_column("名称")
        table.add_column("状态")
        table.add_column("提供的能力")
        table.add_column("缺失时的降级", style="dim")
        for i in items:
            table.add_row(
                i.kind,
                i.name,
                "[green]OK[/green]" if i.ok else "[red]MISSING[/red]",
                i.provides,
                "-" if i.ok else i.fallback,
            )
        Console().print(table)
    except Exception:
        width = max(len(i.name) for i in items) + 2
        for i in items:
            print(f"{i.name:<{width}} {'OK' if i.ok else 'MISSING':<8} {i.provides}")


def main() -> int:
    ap = argparse.ArgumentParser(description="探测 PDF 处理所需的环境能力")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--no-ocr-langs", action="store_true", help="跳过 OCR 语言包探测")
    args = ap.parse_args()

    items = probe(with_ocr_langs=not args.no_ocr_langs)
    if args.json:
        print(to_json(items))
    else:
        print_table(items)
        missing_core = [i.name for i in items if not i.ok and i.level == "core"]
        missing_ocr = [i.name for i in items if not i.ok and i.level == "ocr"]
        print("\n建议:")
        for tip in _advice(missing_core, missing_ocr):
            print("  - " + tip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
