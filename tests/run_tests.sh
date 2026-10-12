#!/bin/bash
# pdf2largeprint 冒烟测试: 英文文本型样本, 覆盖默认/大字号/小屏设备三档参数
# 断言: 依赖可用, 工具退出码为 0, 输出 PDF 存在且非空, 完整性校验通过 (输出含 "✓")
set -u
cd "$(dirname "$0")/.." || exit 1
TOOL="python3 pdf2largeprint.py"
SAMPLES=tests/samples
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

# 依赖预检
python3 -c "import pymupdf" 2>/dev/null || {
    echo "✗ 缺少 PyMuPDF: pip3 install --user -r requirements.txt"; exit 1; }
VER=$(python3 -c "import pymupdf; print(pymupdf.__version__)" 2>/dev/null)
echo "依赖: pymupdf $VER $(command -v pdftotext >/dev/null && echo '+ pdftotext' || echo '(无 pdftotext, 用回退提取)')"

run_case() {
    local name="$1"; shift
    local out="$TMP/$name.pdf"
    local log
    log=$($TOOL "$@" -o "$out" 2>&1) || { echo "✗ $name: 退出码非 0"; FAIL=$((FAIL+1)); return; }
    [ -s "$out" ] || { echo "✗ $name: 输出文件缺失"; FAIL=$((FAIL+1)); return; }
    echo "$log" | grep -q "✓ 内容比例正常" || { echo "✗ $name: 校验未通过"; echo "$log" | tail -3; FAIL=$((FAIL+1)); return; }
    local pages
    pages=$(python3 -c "import pymupdf as f; print(len(f.open('$out')))" 2>/dev/null)
    echo "✓ $name: 校验通过, $pages 页"
    PASS=$((PASS+1))
}

run_case psalm46-默认 "$SAMPLES/The Secret of Psalm 46.pdf"
run_case psalm46-大字号 "$SAMPLES/The Secret of Psalm 46.pdf" --font-size 36
run_case psalm46-6寸 "$SAMPLES/The Secret of Psalm 46.pdf" --device 6

echo "---"
echo "通过 $PASS / $((PASS+FAIL))"
[ "$FAIL" -eq 0 ] || exit 1
