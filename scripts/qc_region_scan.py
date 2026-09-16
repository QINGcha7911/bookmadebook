#!/usr/bin/env python3
"""
qc_region_scan.py — 素材池「地域」机器门禁（第三道，2026-09-13）

背景：YOLO 只管「有没有人」，不管「是不是目标地域」。实测素材池里混进过欧美酒吧、
      洋酒瓶、欧美人物、纽约曼哈顿天际线（搜 "bar counter" / "city skyline" 这类
      英文词时素材站会返回西方内容），靠抽帧目测发现不了 → 本工具把它变成机器可核的报告。

用法：
  python3 qc_region_scan.py <素材根> [目标地域] [每片帧数] [并发]
  例：python3 qc_region_scan.py assets/scenes/book_深夜食堂 japan 3 8

  目标地域：japan | china_classical | england
    japan           → 查「是不是明显不属于日本」的西方式场景
    china_classical → 查「是不是明显不属于中国古代」的场景
    england         → 查「是不是明显不属于英国/西欧」的场景（2026-09-15 新增，英国题材书用）

产物：<素材根>/_qc_region_report.json     逐段判定（含每帧投票明细）
      <素材根>/_qc_region_sheets/*.jpg    拼图留档，供人工复核可疑项

⚠️ 实测坑（2026-09-13，重要）：
  ① **不要问「属于日式/中式/欧美哪一类」**——多分类问法在特写/器物镜头前会瞎猜：
     ryokan(日式旅馆)/障子房间 被判「中式」，和服女子被判「中式」，而 12 格拼图一次问
     更会把每格都判成第一个选项。**正确问法是单目标二元**：
     「这张图是否明显不属于日本？」+ **多帧多数票**（3 帧 3 次独立调用，≥2 票 yes 才算可疑）
     → 实测与人工判读 11/12 一致。
  ② 大图 base64 走 curl argv 会 "Argument list too long" → payload 落文件用 -d @file。
  ③ 素材路径结构是 <场景>/video/*.mp4，别漏 video 那层。
  ④ 本工具只做「判可疑」，**不做最终裁决**：可疑项必须逐格放大人工确认（VL 也会误判）。
"""
import sys, json, os, base64, subprocess, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
TARGET = (sys.argv[2] if len(sys.argv) > 2 else "japan").lower()
NFRAME = int(sys.argv[3]) if len(sys.argv) > 3 else 3
WORKERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8
MODEL = os.environ.get("QC_VL_MODEL", "qwen-vl-max")
API = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
TMP = Path("/tmp/qc_region"); TMP.mkdir(exist_ok=True)

QUESTIONS = {
    "japan": ("这张图如果要用在一部讲日本故事的视频里，画面是否**明显不属于日本**？\n"
              "yes = 能明确看出是西欧/北美/澳洲等的场景或人物（西式吧台、洋酒瓶、欧美面孔与服饰、"
              "欧美城市街景与建筑、玻璃幕墙现代室内、英文招牌为主）；\n"
              "no = 看得出是日本（日文招牌、汉字、榻榻米、障子、暖帘、木格栅、和服、日本街景车站），"
              "或者画面是中性的（食物/器物/桌面/光影/夜景特写，看不出是哪个国家）。\n"
              "只回一个词：yes 或 no。"),
    "china_classical": ("这张图如果要用在一部讲中国古代故事的视频里，画面是否**明显不属于中国古代**？\n"
                        "yes = 能明确看出是现代的/西方的（现代建筑、玻璃幕墙、西装、汽车、"
                        "欧美或当代城市街景、日式榻榻米障子等非中式元素）；\n"
                        "no = 看得出是中国古代（中式木构建筑、亭台楼阁、红木家具、水墨山川、"
                        "汉服、古风器物），或者是中性的（食物/器物/山水/光影特写）。\n"
                        "只回一个词：yes 或 no。"),
    "england": ("这张图如果要用在一部讲**英国故事**的视频里，画面是否**明显不属于英国/西欧**？\n"
                "yes = 能明确看出是**东亚**（日式榻榻米/暖帘/拉门/中文日文招牌/和服/东亚面孔与服饰）、"
                "中东、非洲、南亚、热带（棕榈/沙滩）、或**北美大城市**（摩天楼天际线、黄色校车、"
                "典型美国公路与加油站、白宫式建筑）等明显不是英国的场景；\n"
                "no = 看得出是英国或西欧（英式乡村丘陵与树篱、石砌/砖砌农舍、英式庄园宅邸与花园、"
                "哥特式教堂、英式海滨栈桥、双层巴士、灰绿色草地与阴天柔光），"
                "或者画面是中性的（食器/器物/桌面/光影/天空/水面/花叶特写，看不出是哪个国家）。\n"
                "只回一个词：yes 或 no。"),
    # 2026-09-15 新增：俄国/欧洲旧时代题材（《莫斯科绅士》1922-1954 莫斯科）
    # 二元问法，勿改成多分类（多分类会瞎猜，已实测踩坑）
    "russia": ("这张图如果要用在一部讲**1920-1950 年代俄国故事**的视频里，画面是否**明显不属于俄国／欧洲**？\n"
               "yes = 能明确看出是**东亚**（日式榻榻米/暖帘/拉门/障子/中文日文招牌/和服/东亚面孔与服饰）、\n"
               "中东、非洲、南亚、热带（棕榈/沙滩）、北美（摩天楼天际线、黄色校车、典型美国公路与加油站）、\n"
               "或者**现代玻璃幕墙写字楼／现代都市**等明显不是旧时代俄国的场景；\n"
               "no = 看得出是俄国或欧洲（东正教洋葱头穹顶、石砌或砖砌老建筑、欧式老酒店与老街、\n"
               "积雪街道与松林、旧式室内与旧木家具、烛光与暖黄灯），"
               "或者画面是中性的（食器/器物/桌面/光影/天空/水面/花叶/酒瓶/书页特写，看不出是哪个国家）。\n"
               "只回一个词：yes 或 no。"),
}
Q = QUESTIONS.get(TARGET, QUESTIONS["japan"])


def api_key():
    try:
        for line in Path("/root/.hermes/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("DASHSCOPE_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("DASHSCOPE_API_KEY", "")


KEY = api_key()


def clips(root: Path):
    return [p for p in sorted(root.rglob("*.mp4"))
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
    """单帧独立调用（多帧必须独立问，合并问会互相污染）"""
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


def sample_t(d, k, n):
    """片头偏置采样（2026-09-16 修复）。
    旧公式 t = d*(k+1)/(n+1) 的首个采样点落在片长 11% 处，永远扫不到片段开头约 1 秒
    —— 今早真人出现在源片 2.19s 处，旧公式与均匀抽帧全部漏检。
    新公式：前 1/3 的帧压在开头 0-2.5s，其余均匀铺开。
    """
    if d <= 0:
        return 0.0
    head_x = [0.05, 0.35, 0.9, 1.6, 2.5]
    head_n = max(1, (n + 2) // 3)
    if k < head_n:
        return min(head_x[min(k, len(head_x) - 1)], max(d - 0.05, 0.05))
    m = n - head_n
    if m <= 0:
        return d * 0.5
    return min(d * (k - head_n + 1) / (m + 1), max(d - 0.05, 0.05))


def main():
    if not KEY:
        sys.exit("❌ 找不到 DASHSCOPE_API_KEY")
    cs = clips(ROOT)
    print(f"素材 {len(cs)} 段 | 目标 {TARGET} | 每片 {NFRAME} 帧独立投票 | 并发 {WORKERS} | 模型 {MODEL}", flush=True)

    prep = []
    for c in cs:
        d = dur(c)
        if d <= 0:
            continue
        fs = []
        for k in range(NFRAME):
            t = sample_t(d, k, NFRAME)
            o = TMP / f"{hashlib.md5(str(c).encode()).hexdigest()[:10]}_{k}.jpg"
            if grab(c, t, o):
                fs.append(o)
        if fs:
            prep.append((c, fs))
    print(f"抽帧完成 {len(prep)} 段（{sum(len(f) for _, f in prep)} 次 VL 调用）", flush=True)

    def one(item):
        c, fs = item
        votes = [ask_one(f) for f in fs]
        yes = sum(1 for v in votes if v == "yes")
        n = len([v for v in votes if v in ("yes", "no")])
        rel = str(c.relative_to(ROOT))
        if n == 0:
            v = "unknown"
        elif yes * 2 > n:            # 多数票
            v = "suspect"
        else:
            v = "ok"
        return rel, {"verdict": v, "votes": votes, "yes": yes, "n": n}

    res, done = {}, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, v in ex.map(one, prep):
            res[k] = v
            done += 1
            if done % 25 == 0 or done == len(prep):
                print(f"  {done}/{len(prep)}", flush=True)

    json.dump(res, open(ROOT / "_qc_region_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sd = ROOT / "_qc_region_sheets"; sd.mkdir(exist_ok=True)
    for i in range(0, len(prep), 12):
        sheet(prep[i:i + 12], sd / f"sheet_{i//12:03d}.jpg")

    sus = [k for k, v in res.items() if v["verdict"] == "suspect"]
    unk = [k for k, v in res.items() if v["verdict"] == "unknown"]
    print(f"\n✅ {ROOT/'_qc_region_report.json'}")
    print(f"   可疑(判为非目标地域) {len(sus)} 段 | 通过 {len(res)-len(sus)-len(unk)} 段 | 未返回 {len(unk)} 段")
    for k in sorted(sus, key=lambda x: -res[x]["yes"]):
        print(f"   ⚠️ {res[k]['yes']}/{res[k]['n']}票  {k}")
    print(f"\n拼图留档: {sd}（可疑项必须逐格放大人工确认，VL 也会误判）")


if __name__ == "__main__":
    main()
