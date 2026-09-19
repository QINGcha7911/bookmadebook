#!/bin/bash
# 充值后补跑《湘行散记》VL 三轴 + 商品照轴（2026-09-17 因两家 VL 账号欠费跳过）
# 跑法: bash scripts/regates_xxsj.sh   （SiliconFlow 恢复后自动用 Qwen3-VL-32B，
#       未恢复时 qc_visual_scan.py 会自动回落 DashScope；两家都欠费则全部 verdict=unknown，
#       看到「未返回 N 段」= 门禁没跑成，别当成通过）
set -u
cd "/mnt/d/AI软件/GitHub/bookmadebook" || exit 1
ROOT="assets/scenes/book_湘行散记"
LOG="/tmp/regates_xxsj.log"
: > "$LOG"
export CV_THREADS=1

QC_WORKERS=6 python3 scripts/qc_visual_scan.py "$ROOT" person_part 8 6 >> "$LOG" 2>&1 &
P1=$!
QC_WORKERS=6 python3 scripts/qc_visual_scan.py "$ROOT" modern 8 6 >> "$LOG" 2>&1 &
P2=$!
wait $P1 $P2
QC_WORKERS=6 python3 scripts/qc_visual_scan.py "$ROOT" china_republic 4 6 >> "$LOG" 2>&1
QC_WORKERS=6 python3 scripts/qc_visual_scan.py "$ROOT" product_shot 4 6 >> "$LOG" 2>&1
echo "=== 汇总 ===" >> "$LOG"
python3 scripts/qc_summary.py "$ROOT" >> "$LOG" 2>&1 || true
python3 /root/.hermes/tmp/build_excluded.py "$ROOT" >> "$LOG" 2>&1
tail -40 "$LOG"
echo
echo "下一步：逐格裁决可疑项（拼图在 $ROOT/_qc_*_sheets/），把确认违规的写进"
echo "  ${ROOT}_excluded.json（短格式 <目录>/<文件>），可接受的写进 ${ROOT}_qc_decisions.json，"
echo "然后跑收口校验： python3 scripts/qc_gate_audit.py $ROOT"
