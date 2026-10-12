# pdf2largeprint — 文本型 PDF 转墨水屏大字版

把纯文本型 PDF（网页打印、论文、小说、演讲稿）重排成适合墨水屏阅读的大字版 PDF：
页面按设备**物理尺寸**设置（全屏 1:1 显示，不被缩放），正文大字号、宽行距，
自动清理网页噪音、还原断词、拆分超长段落，并做词级完整性校验。

## 依赖与环境

- **Python 3.10+**
- **PyMuPDF ≥ 1.27**（唯一必需模块，见 `requirements.txt`）
- `pdftotext`（poppler 自带，**可选**：缺失时自动回退 PyMuPDF 提取，仅启发式
  分段效果略差）
- 字体**无需安装**：优先使用系统衬线字体（Georgia / Times / Liberation Serif），
  都没有时自动使用 PDF 内置 Times；含中文时自动切换系统 CJK 字体
  （macOS Arial Unicode / Windows arialuni / Linux Droid Sans Fallback）

### 安装步骤

```bash
# macOS / Linux
pip3 install --user -r requirements.txt
# 或
pip3 install --user "pymupdf>=1.27"

# Windows
pip install -r requirements.txt

# pdftotext (可选, 推荐)
brew install poppler            # macOS
sudo apt install poppler-utils  # Debian/Ubuntu
```

验证安装：

```bash
python3 -c "import pymupdf; print(pymupdf.__version__)"   # 应输出 >= 1.27
which pdftotext                                            # 有输出则启用高质量提取
bash tests/run_tests.sh                                    # 3 个用例全部通过即可
```

### 常见环境问题

**macOS 26 上 `pip install` 崩溃**（pip 内 truststore 解析系统版本失败，
报 `ValueError: invalid literal for int() with base 10: ''`）：

```bash
# 方案: 手动下载 wheel 并解压到 user site-packages (无需 pip)
# 1. 从镜像 simple 页面找 wheel 地址 (替换版本号):
curl -s "http://mirrors.aliyun.com/pypi/simple/pymupdf/" -o /tmp/pm.html
grep -o 'href="[^"]*pymupdf-1\.2[89][^"]*macosx[^"]*arm64\.whl[^"]*"' /tmp/pm.html
# 2. 下载并用 Python 解压安装 (注意替换实际散列路径):
curl -sL -o /tmp/pm.whl "http://mirrors.aliyun.com/pypi/packages/<上一步 href 中的路径, 去掉 ../../ 与 #sha256=...>"
python3 -c "
import site, zipfile, os
os.makedirs(site.getusersitepackages(), exist_ok=True)
zipfile.ZipFile('/tmp/pm.whl').extractall(site.getusersitepackages())
"
python3 -c "import pymupdf; print(pymupdf.__version__)"
```

**公司内网 pip 访问 PyPI 失败**：换镜像源，如
`pip3 install pymupdf -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com`
（或清华 `https://pypi.tuna.tsinghua.edu.cn/simple`）。

**pdftotext 未安装**：工具仍可运行（回退 PyMuPDF 提取），但网页打印型 PDF 的
行序保留不如 `pdftotext -layout`，分段可能略差，建议装上 poppler。

## 快速开始

```bash
# 默认配置: 10.3" 墨水屏, 30pt 正文字号
python3 pdf2largeprint.py book.pdf
# → book-大字版.pdf (250 页 / 以 7000 词文档为例)

# 列出设备预设
python3 pdf2largeprint.py --devices

# 指定设备与字号
python3 pdf2largeprint.py book.pdf --device 6 --font-size 22 -o book-6寸.pdf

# 一键生成多档字号, 拷贝到墨水屏对比挑最舒服的
for fs in 26 30 34; do
  python3 pdf2largeprint.py book.pdf --font-size $fs -o "book-${fs}pt.pdf" --quiet
done
```

### Supernote Manta 使用示例

```bash
# Manta 默认配置 (10.7" 全屏, 30pt)
python3 pdf2largeprint.py "The Secret of Psalm 46.pdf" --device manta -o 大字-manta.pdf

# 阅读+批注场景: 字号加大、行距放宽, 给手写批注留空间
python3 pdf2largeprint.py "The Secret of Psalm 46.pdf" --device manta \
    --font-size 32 --line-height 1.9 --margin-y 45 -o 大字-manta-批注版.pdf

# 对照调字号 (Manta 上 26/30/34pt 一次生成, 拷进设备挑一档)
for fs in 26 30 34; do
  python3 pdf2largeprint.py "The Secret of Psalm 46.pdf" \
      --device manta --font-size $fs -o "大字-manta-${fs}pt.pdf" --quiet
done
```

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--device` | `10.3` | 设备预设（见下表） |
| `--page-w / --page-h` | — | 自定义页面物理尺寸 pt，覆盖 `--device` |
| `--font-size` | 按设备推荐 | 正文字号 pt（8–72）。30pt ≈ 10.6mm 字高 |
| `--line-height` | `1.7` | 行距倍数 |
| `--margin-x / --margin-y` | `30 / 40` | 页边距 pt |
| `--title` | 自动识别 | 覆盖标题 |
| `--no-title` | 否 | 不生成标题页 |
| `--keep-header-footer` | 否 | 保留页眉页脚（默认按跨页重复启发式删除） |
| `--quiet` | 否 | 只输出文件路径 |
| `--devices` | — | 列出设备预设后退出 |

### 设备预设（物理尺寸，均为 3:4 竖屏主流比例）

| 设备 | 页面 (pt) | 默认字号 |
|---|---|---|
| `6` | 258×344 | 20pt — Kindle 6" |
| `6.8` | 297×396 | 22pt — Kindle Paperwhite 6.8" |
| `7` | 303×403 | 22pt — Kobo Libra 7" |
| `7.8` | 337×449 | 24pt — Kobo Aura ONE / Boox Nova 7.8" |
| `10.2` | 446×595 | 30pt — Kindle Scribe 10.2" |
| `10.3` | 445×594 | 30pt — Boox Note / Kobo Elipsa / 掌阅 Smart 10.3" |
| `10.7` / `manta` | 461×614 | 30pt — Supernote Manta 10.7" (1920×2560 @300PPI) |
| `13.3` | 574×765 | 32pt — Boox Max / Sony DPT 13.3" |

## 设计要点（踩坑经验）

1. **页面必须用物理尺寸**。PDF 的 pt 是物理单位（1pt = 1/72 英寸）。若把页面设成
   屏幕像素数（如 1404×1872pt），阅读器"适配页面"时会把它压缩 2.4 倍，
   26pt 文字实际显示只有约 4mm。按设备物理尺寸（10.3" ≈ 445×594pt）设置后，
   全屏显示即真实大小：30pt = 10.6mm 字高，是普通 12pt 正文的 2.5 倍。
2. **测量-装填分页**。排版引擎（MuPDF Story）在段落跨页时有丢内容的确定性 bug，
   且对超页段落会静默截断。因此每段先排版到探针区量高，恰好放得下的段组整组
   放置、段落永不跨页；超长段落按句子边界自动拆分。
3. **文本清理**：跨页重复的页眉/页脚与页码删除；网页打印 PDF 的导航行按
   "像标题的行"（4–12 词、无句末标点）启发式跳过；行尾 `-` 的硬连字符折行
   保留连字符还原（如 `Stratford-` + `upon-Avon`）；行尾句末标点 + 下一行
   非小写开头 = 段落边界。
4. **中英文自适应**：检测到中文自动切换 CJK 字体（macOS: Arial Unicode；
   Windows: arialuni；Linux: Droid Sans Fallback），完整性校验从词级降级为字符级。
   注意引擎不支持 `.ttc` 字体集合的字体子集化，CJK 候选只列 TTF/OTF。
5. **完整性校验**：生成后对比原文/输出词数（或字符数），比例偏离 0.9–1.1 自动
   警告。"疑似缺失/多余"多为大字排版折行拆词的假象（如 `24-bit` → `24-`+`bit`），
   内容无损。

## 测试

```bash
bash tests/run_tests.sh
```

- `samples/The Secret of Psalm 46.pdf`：Brian Moriarty 的 GDC 演讲稿（英文网页打印版，
  18 页 letter，7000+ 词）——本工具的开发动机样本，含页眉导航、硬连字符折行、
  超长段落等典型场景。三个用例分别覆盖默认配置、大字号、小屏设备。

## 已知局限

- 适用纯文本型 PDF；**扫描版（纯图片）需先 OCR**，结果质量取决于文本层。
- 多栏排版、表格、代码块的分段启发式可能不理想，校验警告会提示。
- 中文的"段落"重建启发式（行尾标点规则）按英文标点设计，中文 PDF 建议人工抽查。

## 开发历史

本工具由 `The Secret of Psalm 46.pdf` 的排版需求演化而来。早期原型
`make_large_print.py`（硬编码该文档）在解决"引擎跨页丢内容"问题的过程中验证了
测量-装填方案，随后泛化为本工具。
