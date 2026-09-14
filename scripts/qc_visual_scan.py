#!/usr/bin/env python3
"""
qc_visual_scan.py — 通用「画面内容」VL 机器门禁（2026-09-14 新增）

为什么需要它（《大医》事故教训）：
  YOLO 人体模型**抓不到「孤立的手」「手指」**；也**不管现代物件**（汽车/电线杆）。
  《大医》第一版因此把「真人手握毛笔」「手指触碰设备」「雪地里的现代汽车」放进正片，
  而 YOLO 双尺寸终审全部漏掉，dry-run 还报了「✅」。→ 必须有一条 VL 语义轴补这个缺口。

与 qc_region_scan.py 同一套引擎（v3 版问法，2026-09-13 实测与人工 11/12 一致）：
  **单目标二元问法** + **每片抽 N 帧、每帧独立调用** + **多数票才算可疑**。
  （多分类问法会瞎猜；拼图一次问会把每格都判成第一个选项 —— 别走回头路。）

用法：
  python3 scripts/qc_visual_scan.py <素材根|清单文件> <目标> [每片帧数=3] [并发=8]
  目标：
    person_part  人的任何部位（脸/手/手指/手臂/腿/背影/人影）—— 补 YOLO 的盲区
    modern       现代物件（汽车/摩托车/柏油路标线/电线杆/现代建筑/塑料/现代包装/现代服装）
    product_shot 现代商业静物摄影感（影棚打光/纯色背景/浅景深/商品摆拍）—— 补 modern 漏掉的
                 「精油瓶滴管瓶 + 黄底商品照」这类（《大医》开头 22-33s 事故）
    japan        是否明显不属于日本（地域门禁，等价 qc_region_scan japan）
    china_classical  是否明显不属于中国古代（古风题材书用）
    china_republic   是否明显不属于中国清末-民国（《大医》这类民国题材书用；✱ 别用
                 china_classical 判民国书 —— 民国火车当然"不属于古代"，会报一堆假阳性）

  清单文件：JSON 数组或纯文本，每行一条 `<场景>/<文件>` 或任意相对/绝对路径 → 只扫这些片子
            （用于「只核成片实际用到的那 80 段」，比全池扫更快更准）

产物：<素材根>/_qc_<目标>_report.json + _qc_<目标>_sheets/*.jpg
⚠️ 只判「可疑」不当裁决 —— 可疑项必须逐格放大人工确认（VL 也会误判）。

⚠️ **抽样密度铁律（2026-09-14 实测）**：默认 3 帧**不够**！实测 `snow_landscape/04`（雪地公路
   上的汽车）—— 8 帧里只有 1 帧能看到车（车只在片段的某 1-2 秒出现），3 帧全错过 → **漏报**。
   源素材门禁必须 **≥8 帧/片**（`person_part 8 16` / `modern 8 16`）。
   注意：合成器只取源片段的**一个子窗口**，所以源级门禁必须扫满整片；
   而「成片实际用了什么」只有**对成片密采样**（每 2.5s 一帧）才能确认。
"""
import sys, json, os, base64, subprocess, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

ARG1 = sys.argv[1] if len(sys.argv) > 1 else "."
TARGET = (sys.argv[2] if len(sys.argv) > 2 else "person_part").lower()
NFRAME = int(sys.argv[3]) if len(sys.argv) > 3 else 3
WORKERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8
MODEL = os.environ.get("QC_VL_MODEL", "qwen-vl-max")
API = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
TMP = Path("/tmp/qc_visual"); TMP.mkdir(exist_ok=True)

# yes = 有问题（可疑）
QUESTIONS = {
    "person_part": ("这张图里是否出现了**人的任何部位**？\\n"
                    "yes = 有：人脸、手、手指、手臂、腿、脚、背影、身体任何部分、明显人影；\\n"
                    "no = 完全没有（纯器物/风景/建筑/食物/布料/光影特写，一个人也没有）。\\n"
                    "只回一个词：yes 或 no。"),
    "modern": ("这张图里是否出现了**明确属于现代工业/现代交通的东西**？\\n"
               "yes = 画面里能看清有：汽车/轿车/卡车/公交车/摩托车/自行车、柏油马路上的白色交通标线、"
               "高压电线杆或成排电线、玻璃幕墙写字楼、现代高层住宅楼、塑料瓶/塑料袋/塑料制品、"
               "现代印刷标签或广告牌、现代运动鞋或现代时装；\\n"
               "no = 没有上述任何一样。**以下都算 no，不要判 yes**：老式器物与古董、木石建筑与老宅、"
               "山水雪原森林、食物与食材、书本纸张与卷轴、金属医疗器械与老式仪器、"
               "老式火车/老式车站/老式汽车（蒸汽时代与民国样式的都算 no）、水墨画与书法。\\n"
               "只回一个词：yes 或 no。"),
    "japan": ("这张图如果要用在一部讲日本故事的视频里，画面是否**明显不属于日本**？\\n"
              "yes = 能明确看出是西欧/北美/澳洲等的场景或人物；\\n"
              "no = 看得出是日本，或者画面是中性的（食物/器物/桌面/光影特写）。\\n"
              "只回一个词：yes 或 no。"),
    "china_classical": ("这张图如果要用在一部讲中国古代故事的视频里，画面是否**明显不属于中国古代**？\\n"
                        "yes = 能明确看出是现代的/西方的；\\n"
                        "no = 看得出是中国古代，或者是中性的（食物/器物/山水/光影特写）。\\n"
                        "只回一个词：yes 或 no。"),
    # 2026-09-14 新增（《大医》民国口径 + 现代商品静物照事故的根治）
    "china_republic": ("这张图如果要用在一部讲中国**清末到民国**（约 1900-1949 年）故事的视频里，"
                       "画面是否**明显不属于那个时代、或者明显不是中国**？\\n"
                       "yes = 能明确看出是当代的（现代城市/汽车/塑料制品/玻璃幕墙）**或**明显西欧/北美/北欧的"
                       "（欧式石阶老巷、阿尔卑斯式红顶村落、北欧木屋、日式榻榻米与障子）；\\n"
                       "no = 中式木构与砖木建筑、老砖墙土墙、民国街景与店铺、蒸汽机车与老式车站、"
                       "中式器物与药柜算盘、山水雪原森林、食物器物光影特写（中性题材都算 no）。\\n"
                       "只回一个词：yes 或 no。"),
    "product_shot": ("这张图看起来是不是**现代商业静物摄影/商品广告照**的观感？\\n"
                     "yes = 影棚式打光、纯色或渐变背景、浅景深强虚化、商品摆拍构图"
                     "（精油瓶/滴管瓶/胶囊瓶/标准化包装、标签印刷精美、道具刻意摆放、色彩鲜艳统一）；\\n"
                     "no = 自然记录感、实拍场景、老照片质感、文物与器物记录照、食材原样摆放。\\n"
                     "只回一个词：yes 或 no。"),
}
Q = QUESTIONS.get(TARGET, QUESTIONS["person_part"])


def api_key():
    try:
        for line in Path("/root/.hermes/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("DASHSCOPE_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("DASHSCOPE_API_KEY", "")


KEY = api_key()
ARG1_P = Path(ARG1)
LIST_MODE = ARG1_P.is_file()
ROOT = Path(".") if LIST_MODE else ARG1_P           # 清单模式下产物落在 CWD


def clips():
    if LIST_MODE:
        # 直接传单个视频文件（如片头 5s mp4）→ 只扫这一个
        if ARG1_P.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
            return [ARG1_P]
        t = ARG1_P.read_text(encoding="utf-8", errors="ignore").strip()
        items = json.loads(t) if t.startswith("[") else [x.strip() for x in t.splitlines() if x.strip()]
        out = []
        for it in items:
            p = Path(it)
            if not p.is_absolute():
                cands = [Path("/mnt/d/AI软件/GitHub/bookmadebook/assets/scenes") / it,
                         Path(it)]
                # 支持 <场景>/<文件> 短格式 → 补 video/ 层
                if len(Path(it).parts) == 2:
                    d, f = Path(it).parts
                    cands.insert(0, Path("/mnt/d/AI软件/GitHub/bookmadebook/assets/scenes/book_大医") / d / "video" / f)
                p = next((c for c in cands if c.exists()), cands[0])
            if p.exists():
                out.append(p)
        return out
    return [p for p in sorted(ARG1_P.rglob("*.mp4"))
            if not any(part.startswith("_excluded") for part in p.parts)]


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    try:
        return max(0.1, float(r.stdout.strip()))
    except Exception:
        return 0.0


def grab(p, t, out):
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1",
                    "-vf", "scale=560:-2:flags=lanczos", "-y", str(out)], capture_output=True)
    return out.exists() and out.stat().st_size > 0


def ask_one(img: Path):
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {"model": MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": Q}]}], "max_tokens": 8, "temperature": 0}
    pj = TMP / f"pl_{img.stem}.json"
    pj.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run(["curl", "-s", "-m", "120", "-X", "POST", API,
                        "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json",
                        "-d", f"@{pj}"], capture_output=True, text=True, timeout=180)
    try:
        t = json.loads(r.stdout)["choices"][0]["message"]["content"].strip().lower()
        return "yes" if t.startswith("yes") else ("no" if t.startswith("no") else "err")
    except Exception:
        return "err"


def sheet(pairs, path):
    COLS, CW = 4, 380
    imgs = [Image.open(fs[0]).convert("RGB") for _, fs in pairs]
    rows = (len(imgs) + COLS - 1) // COLS
    ch = max(i.height for i in imgs)
    sh = Image.new("RGB", (COLS * CW, rows * ch), (15, 15, 15))
    d = ImageDraw.Draw(sh)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except Exception:
        f = ImageFont.load_default()
    for i, im in enumerate(imgs):
        r, c = divmod(i, COLS)
        sh.paste(im.resize((CW, ch)), (c * CW, r * ch))
        d.rectangle([c * CW + 5, r * ch + 5, c * CW + 78, r * ch + 66], fill=(0, 0, 0))
        d.text((c * CW + 14, r * ch + 11), str(i + 1), fill=(255, 235, 60), font=f)
    sh.save(path, quality=86)
    return path


def main():
    if not KEY:
        sys.exit("❌ 找不到 DASHSCOPE_API_KEY")
    cs = clips()
    if not cs:
        print(f"❌ 待检素材 0 段 —— 对象不存在/路径写错/清单为空。")
        print(f"   入参: {ARG1}（{'文件' if LIST_MODE else '目录'}）")
        print(f"   ⚠️ 0 段 ≠ 干净！这是「静默假通过」，绝不许当成通过。")
        sys.exit(3)
    mode = f"清单 {ARG1}" if LIST_MODE else f"全池 {ARG1}"
    print(f"{mode} | 素材 {len(cs)} 段 | 目标 {TARGET} | 每片 {NFRAME} 帧独立投票 | "
          f"并发 {WORKERS} | 模型 {MODEL}", flush=True)

    prep = []
    # 并发抽帧（2026-09-14：串行时 249 段要 5 分钟，是整条门禁的瓶颈）
    def prep_one(c):
        d = dur(c)
        if d <= 0:
            return None
        fs = []
        for k in range(NFRAME):
            t = d * (k + 1) / (NFRAME + 1)
            o = TMP / f"{hashlib.md5(str(c).encode()).hexdigest()[:10]}_{k}.jpg"
            if grab(c, t, o):
                fs.append(o)
        return (c, fs) if fs else None
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(prep_one, cs):
            if r:
                prep.append(r)
    print(f"抽帧完成 {len(prep)} 段（{sum(len(f) for _, f in prep)} 次 VL 调用）", flush=True)

    def one(item):
        c, fs = item
        votes = [ask_one(f) for f in fs]
        yes = sum(1 for v in votes if v == "yes")
        n = len([v for v in votes if v in ("yes", "no")])
        rel = str(c.relative_to(ROOT)) if str(c).startswith(str(ROOT)) else str(c)
        v = "unknown" if n == 0 else ("suspect" if yes * 2 > n else "ok")
        return rel, {"verdict": v, "votes": votes, "yes": yes, "n": n}

    res, done = {}, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, v in ex.map(one, prep):
            res[k] = v
            done += 1
            if done % 25 == 0 or done == len(prep):
                print(f"  {done}/{len(prep)}", flush=True)

    prefix = TARGET if not LIST_MODE else f"{TARGET}_picks"
    json.dump(res, open(ROOT / f"_qc_{prefix}_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sd = ROOT / f"_qc_{prefix}_sheets"; sd.mkdir(exist_ok=True)
    for i in range(0, len(prep), 12):
        sheet(prep[i:i + 12], sd / f"sheet_{i//12:03d}.jpg")

    sus = [k for k, v in res.items() if v["verdict"] == "suspect"]
    unk = [k for k, v in res.items() if v["verdict"] == "unknown"]
    print(f"\n✅ {ROOT/f'_qc_{prefix}_report.json'}")
    print(f"   可疑 {len(sus)} 段 | 通过 {len(res)-len(sus)-len(unk)} 段 | 未返回 {len(unk)} 段")
    for k in sorted(sus, key=lambda x: -res[x]["yes"]):
        print(f"   ⚠️ {res[k]['yes']}/{res[k]['n']}票  {k}")
    print(f"\n拼图留档: {sd}（可疑项必须逐格放大人工确认，VL 也会误判）")


if __name__ == "__main__":
    main()
