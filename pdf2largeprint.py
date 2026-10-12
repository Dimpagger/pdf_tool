#!/usr/bin/env python3
"""pdf2largeprint — 把文本型 PDF 转成墨水屏大字版 PDF。

用法:
    python3 pdf2largeprint.py book.pdf                          # 默认 10.3" 设备, 30pt 字号
    python3 pdf2largeprint.py book.pdf --device 6 --font-size 22
    python3 pdf2largeprint.py book.pdf -o out.pdf --device 13.3 --font-size 36
    python3 pdf2largeprint.py --devices                        # 列出设备预设

设计要点 (来自实战经验):
  * PDF 的 pt 是物理单位 (1pt = 1/72 英寸), 页面必须按墨水屏物理尺寸设置,
    阅读器"适配页面"模式下文字即为真实大小, 不会被缩放。
  * 排版引擎 (MuPDF Story) 在段落跨页时有丢内容的确定性 bug, 且对超页段落
    会静默截断 —— 因此采用"测量-装填"法: 每段先量高, 恰好放得下的段组
    整组放置, 段落永不跨页; 超长段落按句子边界拆分。
  * 生成后自动做词级完整性校验 (输出词数 vs 原文词数)。

适用: 纯文本型 PDF (网页打印、论文、小说、演讲稿)。扫描版 (纯图片) 需要先
OCR, 不在本工具范围内。
"""
import argparse
import html
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # 旧版
    import fitz

# ---------------------------------------------------------------- 设备预设
# (物理尺寸 pt = 英寸 x 72, 均为 3:4 竖屏主流比例)
DEVICES = {
    "6":     (258, 344, 'Kindle 6" (600x800 @167PPI)'),
    "6.8":   (297, 396, 'Kindle Paperwhite 6.8" (1236x1648 @300PPI)'),
    "7":     (303, 403, 'Kobo Libra 7" (1264x1680 @300PPI)'),
    "7.8":   (337, 449, 'Kobo Aura ONE / Boox Nova 7.8" (1872x1404 @300PPI)'),
    "10.2":  (446, 595, 'Kindle Scribe 10.2" (1860x2480 @300PPI)'),
    "10.3":  (445, 594, 'Boox Note / Kobo Elipsa / 掌阅 Smart 10.3" (1404x1872 @227PPI)'),
    "13.3":  (574, 765, 'Boox Max / Sony DPT 13.3" (1650x2200 @207PPI)'),
}
DEFAULT_FONT_SIZE = {"6": 20, "6.8": 22, "7": 22, "7.8": 24,
                     "10.2": 30, "10.3": 30, "13.3": 32}

# ---------------------------------------------------------------- 字体发现
def find_fonts():
    """优先系统衬线字体 (Georgia/Times/Liberation), 找不到则用 PDF 内置
    Times (fitz.Font('tiro'/'tibo'/'tiit') 的字体缓冲, 任何平台可用)。"""
    sys_candidates = [
        ("/System/Library/Fonts/Supplemental/Georgia.ttf",
         "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
         "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"),
        ("C:/Windows/Fonts/georgia.ttf",
         "C:/Windows/Fonts/georgiab.ttf",
         "C:/Windows/Fonts/georgiai.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        ("/usr/share/fonts/TTF/Times New Roman.ttf",) * 3,
        ("/Library/Fonts/Times New Roman.ttf",) * 3,
    ]
    for reg, bold, ita in sys_candidates:
        if Path(reg).exists() and Path(bold).exists() and Path(ita).exists():
            return (("georgia", reg), ("georgia-bold", bold), ("georgia-italic", ita)), "系统衬线字体"
    # fallback: PDF 内置 Times (base14)
    try:
        buf = [(n, fitz.Font(fontname=n).buffer) for n in ("tiro", "tibo", "tiit")]
        return (("georgia", buf[0][1]), ("georgia-bold", buf[1][1]), ("georgia-italic", buf[2][1])), "内置 Times 字体"
    except Exception:
        return None, None


# ---------------------------------------------------------------- 文本提取
def extract_text(pdf_path):
    """pdftotext -layout 优先 (保序输出, 适合启发式分段), 缺失时回退 PyMuPDF。"""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    doc = fitz.open(pdf_path)
    return "\f".join(page.get_text() for page in doc)


# ---------------------------------------------------------------- 清理与分段
TERMINAL = set(".!?”’…:")          # 行尾这些标点 + 下行非小写开头 → 段尾
SECTION_MARKS = set("§✦✳⁂*·—")     # 单独成行的符号 → 章节分隔


def clean_and_split(raw, drop_header_footer=True):
    """网页打印噪音清理 + 段落重建。返回 (title, [(kind, text), ...])。"""
    pages = raw.split("\f")
    page_lines = [[l.strip() for l in p.splitlines() if l.strip()] for p in pages]
    page_lines = [p for p in page_lines if p]

    # 页眉/页脚: 相同行出现在 >=60% 页面的首/末 3 行 → 删除; 纯数字行 (页码) 删除
    skip = set()
    if drop_header_footer and len(page_lines) >= 3:
        head_cands, tail_cands = Counter(), Counter()
        for pl in page_lines:
            for l in pl[:3]:
                head_cands[l] += 1
            for l in pl[-3:]:
                tail_cands[l] += 1
        thr = max(3, int(len(page_lines) * 0.6))
        skip |= {l for l, c in head_cands.items() if c >= thr and len(l) <= 60}
        skip |= {l for l, c in tail_cands.items() if c >= thr and len(l) <= 60}
        skip |= {l for pl in page_lines for l in pl
                 if re.fullmatch(r"[\d\-–—\s]{1,8}", l)}

    lines = [l for pl in page_lines for l in pl if l not in skip]
    if not lines:
        raise SystemExit("提取不到文本: 该 PDF 可能是扫描版 (纯图片), 请先 OCR")

    # 标题 = 前几行中第一个"像标题"的行: 4-12 词、不以句末标点结尾。
    # 网页打印的 PDF 开头常有 1-3 词的导航行 (作者名/语言切换), 据此跳过。
    title, title_idx = lines[0], 0
    for i, cand in enumerate(lines[:15]):
        words = cand.split()
        if 4 <= len(words) <= 12 and cand[-1] not in TERMINAL \
                and not cand.startswith(("http", "www")):
            title, title_idx = cand, i
            break

    items, buf = [], []
    for i, s in enumerate(lines):
        if i <= title_idx:
            continue  # 标题行及其之前的导航噪音不进正文
        if s in SECTION_MARKS and len(s) <= 2:
            if buf:
                items.append(("para", " ".join(buf)))
                buf = []
            items.append(("section", None))
            continue
        if buf and buf[-1].endswith("-"):
            # 硬连字符折行: 保留连字符拼接 (如 Stratford- + upon-Avon)
            buf[-1] = buf[-1] + s
            continue
        buf.append(s)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if s[-1] in TERMINAL and not (nxt and nxt[0].islower()):
            items.append(("para", " ".join(buf)))
            buf = []
    if buf:
        items.append(("para", " ".join(buf)))
    return title, items


# ---------------------------------------------------------------- 排版引擎
class Composer:
    """测量-装填排版: 段落永不跨页 (绕开引擎分页 bug), 超长段按句拆分。"""

    def __init__(self, page_w, page_h, font_size, line_height,
                 margin_x, margin_y, fonts, css_extra=""):
        self.mediabox = fitz.Rect(0, 0, page_w, page_h)
        self.mx, self.my = margin_x, margin_y
        self.cw = page_w - 2 * margin_x
        self.top, self.bottom = margin_y, page_h - margin_y
        self.fs, self.lh = font_size, line_height
        # 字号层级: 正文 / 前言 / 标题 / 章节标记 / 版权
        self.preamble_fs = max(10, round(font_size * 0.75))
        self.title_fs = min(font_size + 6, 60)
        self.mark_fs = font_size + 8
        self.copy_fs = max(9, round(font_size * 0.6))
        self.arch = fitz.Archive()
        for name, src in fonts:
            self.arch.add(src, f"{name}.ttf")
        self.css = f"""
@font-face {{font-family: georgia; src: url(georgia.ttf);}}
@font-face {{font-family: georgia-bold; src: url(georgia-bold.ttf);}}
@font-face {{font-family: georgia-italic; src: url(georgia-italic.ttf);}}
* {{font-family: georgia; color: #000000;}}
h1 {{font-family: georgia-bold; font-size: {self.title_fs}pt;
    text-align: center; margin: 0 0 {max(4, font_size//5)}pt 0;}}
p.sub {{text-align: center; font-size: {self.preamble_fs}pt; margin: 0 0 {font_size}pt 0;}}
p.preamble {{font-size: {self.preamble_fs}pt; line-height: {line_height * 0.9:.2f};
    margin: 0 0 {font_size // 3}pt 0; text-align: left;}}
p.mark {{font-family: georgia-bold; font-size: {self.mark_fs}pt;
    text-align: center; margin: 0 0 {font_size // 2}pt 0;}}
p.body {{font-size: {font_size}pt; line-height: {line_height};
    margin: 0 0 {max(8, font_size // 2)}pt 0; text-align: left;}}
p.copyright {{font-size: {self.copy_fs}pt; line-height: {line_height * 0.9:.2f};
    margin: 0 0 {max(4, font_size // 5)}pt 0;}}
""" + css_extra
        self.cache = {}
        self.cap = self.bottom - self.top

    # ---- 基础操作 ----
    def measure(self, html_str):
        if html_str in self.cache:
            return self.cache[html_str]
        story = fitz.Story(html=html_str, user_css=self.css, archive=self.arch, em=0)
        more, filled = story.place(fitz.Rect(0, 0, self.cw, 1_000_000))
        assert not more, "单段 place 不应溢出"
        h = fitz.Rect(filled).height
        self.cache[html_str] = h
        return h

    def split_long(self, html_str):
        """超页段落先按句拆, 超长单句再按词拆 (引擎对超页段会静默截断)。"""
        if self.measure(html_str) <= self.cap:
            return [html_str]
        cls = re.search(r"class='(\w+)'", html_str).group(1)
        text = html.unescape(re.sub(r"<[^>]+>", "", html_str))
        sents = re.split(r"(?<=[.!?”])\s+", text)
        groups, cur = [], []
        for s in sents:
            if cur and self.measure(f"<p class='{cls}'>{html.escape(' '.join(cur + [s]))}</p>") > self.cap:
                groups.append(" ".join(cur))
                cur = [s]
            else:
                cur.append(s)
        if cur:
            groups.append(" ".join(cur))
        final = []
        for g in groups:
            piece = f"<p class='{cls}'>{html.escape(g)}</p>"
            if self.measure(piece) <= self.cap:
                final.append(piece)
                continue
            words = g.split()
            subs, curw = [], []
            for w in words:
                if curw and self.measure(f"<p class='{cls}'>{html.escape(' '.join(curw + [w]))}</p>") > self.cap:
                    subs.append(html.escape(" ".join(curw)))
                    curw = [w]
                else:
                    curw.append(w)
            if curw:
                subs.append(html.escape(" ".join(curw)))
            final.extend(f"<p class='{cls}'>{x}</p>" for x in subs)
        return final

    # ---- 输出编排 ----
    def compose(self, title, items, out_path, no_title=False):
        writer = fitz.DocumentWriter(str(out_path))
        dev = writer.begin_page(self.mediabox)
        y_cursor = self.top
        page_count = 1
        state = {"dev": dev, "y": y_cursor, "page": page_count}

        def new_page():
            nonlocal y_cursor, dev, page_count
            writer.end_page()
            page_count += 1
            dev = writer.begin_page(self.mediabox)
            y_cursor = self.top

        def draw_batch(pieces, at_top):
            story = fitz.Story(html="\n".join(pieces), user_css=self.css,
                               archive=self.arch, em=0)
            rect = fitz.Rect(self.mx, at_top, self.mx + self.cw, self.bottom)
            more, _ = story.place(rect)
            if more:
                return False
            story.draw(dev, fitz.Matrix(1, 0, 0, 1, self.mx, at_top))
            return True

        def emit_piece(html_str):
            nonlocal y_cursor
            h = self.measure(html_str)
            if y_cursor + h > self.bottom and y_cursor > self.top:
                new_page()
            assert draw_batch([html_str], y_cursor), "单段 place 意外溢出"
            y_cursor += h

        def emit_batch(pieces):
            nonlocal y_cursor
            while pieces:
                pieces = [sub for piece in pieces for sub in self.split_long(piece)]
                acc, take = 0.0, 0
                for html_str in pieces:
                    h = self.measure(html_str)
                    if y_cursor + acc + h <= self.bottom + 0.5:
                        acc += h
                        take += 1
                    else:
                        break
                if take == 0:
                    new_page()
                    continue
                if not draw_batch(pieces[:take], y_cursor):
                    for html_str in pieces[:take]:
                        emit_piece(html_str)
                else:
                    y_cursor += acc  # 用 measure 之和, 不用 filled (组满页时 filled=整个 rect)
                pieces = pieces[take:]

        esc = html.escape

        def wrap(cls, text):
            return f"<p class='{cls}'>{esc(text)}</p>"

        preamble, chapters, tail = [], [], []
        cur = preamble
        seen_copyright = False
        for kind, text in items:
            if text and re.search(r"copyright|©", text, re.I):
                seen_copyright = True
            if kind == "section" and not seen_copyright:
                chapters.append([])
                cur = chapters[-1]
            elif text == "...":
                (chapters[-1] if chapters else preamble).append(wrap("body", text))
            elif seen_copyright:
                tail.append(wrap("copyright", text))
            elif cur is preamble:
                preamble.append(wrap("preamble", text))
            else:
                cur.append(wrap("body", text))

        # 前言页: 标题 + 前言; 各章新页; 尾部独立页
        head = [] if no_title else [f"<h1>{esc(title)}</h1>"]
        emit_batch(head + preamble)
        for ch in chapters:
            if y_cursor > self.top:
                new_page()
            emit_batch(["<p class='mark'>§</p>"] + ch)
        if tail:
            if y_cursor > self.top:
                new_page()
            emit_batch(tail)
        writer.end_page()
        writer.close()
        return page_count


# ---------------------------------------------------------------- 完整性校验
def verify(out_pdf, src_text, cjk=False):
    """词级对比 (CJK 文本无空格分词, 折行拆字会误报, 改用字符级)。"""
    doc = fitz.open(out_pdf)
    out_flat = " ".join(" ".join(p.get_text().split()) for p in doc)
    src_flat = " ".join(src_text.split())
    if cjk:
        out_n = re.sub(r"\s+", "", out_flat)
        src_n = re.sub(r"\s+", "", src_flat)
        return {
            "src_chars": len(src_n),
            "out_chars": len(out_n),
            "missing": [], "extra": [],
        }
    wo, ws = Counter(out_flat.split()), Counter(src_flat.split())
    missing = list((ws - wo).items())[:10]
    extra = list((wo - ws).items())[:10]
    return {
        "src_words": sum(ws.values()),
        "out_words": sum(wo.values()),
        "missing": missing,
        "extra": extra,
    }


# ---------------------------------------------------------------- 主程序
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="把文本型 PDF 转成墨水屏大字版 PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="适用: 纯文本型 PDF (网页打印、论文、小说、演讲稿)。\n"
               "扫描版 (纯图片) 需要先 OCR, 不在本工具范围内。")
    ap.add_argument("input", nargs="?", help="输入 PDF 路径 (--devices 时省略)")
    ap.add_argument("-o", "--output", help="输出 PDF 路径 (默认 <原名>-大字版.pdf)")
    ap.add_argument("--device", choices=sorted(DEVICES), default="10.3",
                    help="设备预设 (默认 10.3)")
    ap.add_argument("--page-w", type=float, help="自定义页宽 pt (需与 --page-h 同时提供)")
    ap.add_argument("--page-h", type=float, help="自定义页高 pt (需与 --page-w 同时提供)")
    ap.add_argument("--font-size", type=float,
                    help=f"正文字号 pt (各设备默认: {DEFAULT_FONT_SIZE})")
    ap.add_argument("--line-height", type=float, default=1.7, help="行距倍数 (默认 1.7)")
    ap.add_argument("--margin-x", type=float, default=30, help="左右边距 pt (默认 30)")
    ap.add_argument("--margin-y", type=float, default=40, help="上下边距 pt (默认 40)")
    ap.add_argument("--title", help="覆盖自动识别的标题")
    ap.add_argument("--no-title", action="store_true", help="不生成标题页")
    ap.add_argument("--keep-header-footer", action="store_true",
                    help="保留页眉页脚 (默认按跨页重复启发式删除)")
    ap.add_argument("--quiet", action="store_true", help="只输出结果文件路径")
    ap.add_argument("--devices", action="store_true", help="列出设备预设并退出")
    args = ap.parse_args(argv)

    if args.devices:
        for k, (w, h, desc) in DEVICES.items():
            print(f"  {k:6s} {w:4.0f}x{h:<4.0f}pt  {desc}")
        return 0

    if not args.input:
        ap.error("缺少输入 PDF 路径")
    src = Path(args.input)
    if not src.exists():
        ap.error(f"找不到文件: {src}")

    if args.page_w or args.page_h:
        if not (args.page_w and args.page_h):
            ap.error("--page-w 与 --page-h 需同时提供")
        page_w, page_h = args.page_w, args.page_h
        device_desc = f"自定义 {page_w}x{page_h}pt"
    else:
        page_w, page_h, device_desc = DEVICES[args.device]
    font_size = args.font_size or DEFAULT_FONT_SIZE[args.device]
    if not (8 <= font_size <= 72):
        ap.error("--font-size 应在 8-72 之间")

    out = Path(args.output) if args.output else src.with_name(src.stem + "-大字版.pdf")

    log = (lambda *a, **k: None) if args.quiet else print
    log(f"设备: {args.device} ({device_desc}), 页面 {page_w:.0f}x{page_h:.0f}pt")
    log(f"字号: {font_size}pt = {font_size/72*25.4:.1f}mm, 行距 {args.line_height}")

    # 提取
    raw = extract_text(src)
    if not raw.strip():
        ap.error("提取不到文本: 该 PDF 可能是扫描版 (纯图片), 请先 OCR")
    # 清理与分段
    title, items = clean_and_split(raw, drop_header_footer=not args.keep_header_footer)
    if args.title:
        title = args.title
    n_para = sum(1 for k, _ in items if k == "para")
    n_sec = sum(1 for k, _ in items if k == "section")
    log(f"解析: 标题 {title[:40]!r}, 段落 {n_para}, 章节分隔 {n_sec}")

    # 排版
    fonts, font_desc = find_fonts()
    if not fonts:
        ap.error("找不到可用字体")
    # 中文检测: 衬线西文字体不含中文字形, 自动切换 CJK 字体
    # (注意: 排版引擎不支持 .ttc 字体集合的字体子集化, 只列 TTF/OTF)
    if re.search(r"[一-鿿]", raw):
        cjk = next((p for p in (
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "C:/Windows/Fonts/arialuni.ttf",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ) if Path(p).exists()), None)
        if cjk:
            fonts = (("georgia", cjk), ("georgia-bold", cjk), ("georgia-italic", cjk))
            font_desc = f"CJK 字体 {Path(cjk).name}"
        else:
            log("警告: 检测到中文, 但未找到中文字体, 输出可能缺字")
    comp = Composer(page_w, page_h, font_size, args.line_height,
                    args.margin_x, args.margin_y, fonts)
    pages = comp.compose(title, items, out, no_title=args.no_title)
    log(f"生成: {out} ({pages} 页, 字体: {font_desc})")

    # 校验
    has_cjk = bool(re.search(r"[一-鿿]", raw))
    v = verify(out, raw, cjk=has_cjk)
    if has_cjk:
        ratio = v["out_chars"] / max(1, v["src_chars"])
        log(f"校验: 原文 {v['src_chars']} 字符 → 输出 {v['out_chars']} 字符")
    else:
        log(f"校验: 原文 {v['src_words']} 词 → 输出 {v['out_words']} 词")
        ratio = v["out_words"] / max(1, v["src_words"])
        if v["missing"]:
            log(f"  疑似缺失: {v['missing'][:5]}")
        if v["extra"]:
            log(f"  疑似多余: {v['extra'][:5]}")
    if not (0.9 <= ratio <= 1.1):
        log(f"  警告: 比例 {ratio:.2f} 偏离 1.0, 请检查输出")
    else:
        log("  ✓ 内容比例正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
