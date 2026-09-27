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
import os
import sys, json, os, base64, subprocess, hashlib, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

ARG1_P = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
LIST_MODE = ARG1_P.is_file()          # 2026-09-22 补：清单模式（与 qc_visual_scan.py 对齐）
ROOT = Path(".") if LIST_MODE else ARG1_P   # 清单模式下产物落 CWD，别污染素材池
TARGET = (sys.argv[2] if len(sys.argv) > 2 else "japan").lower()
NFRAME = int(sys.argv[3]) if len(sys.argv) > 3 else 3
WORKERS = int(os.environ.get("QC_WORKERS") or (sys.argv[4] if len(sys.argv) > 4 else 4))  # 2026-09-16：8→4，同上
# ── 2026-09-22 降费改造（007）：与 qc_visual_scan.py 同一套设计 ──────────────
#   召回层 qwen3-vl-flash（560px 帧 ≈ ¥0.00011/次）→ 判「可疑」的段再用 qwen-vl-max 复判（≈¥0.00106/次）
#   阳性对照：2026-09-22 person_part 轴 51 帧逐帧一致（含曾漏检正脸段），本轴沿用同一召回模型；
#   地域轴判据更细 ⇒ **确认层必须保留**（终态由 max 定，判据线不降级）。
MODEL = os.environ.get("QC_VL_MODEL", "qwen3-vl-flash")  # 召回层（2026-09-22 起默认 flash）
CONFIRM_MODEL = os.environ.get("QC_VL_CONFIRM_MODEL", "qwen-vl-max")  # 确认层；"off" 禁用
NO_CACHE = bool(os.environ.get("QC_NO_CACHE"))
CACHE = {}
hits = {"n": 0}
calls = {"recall": 0, "confirm": 0}
API = os.environ.get("QC_VL_API", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
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
    # 2026-09-16 新增：西班牙/地中海海岛题材（《温柔的夜》三毛·加那利群岛）
    # 二元问法，勿改多分类
    "spain": ("这张图如果要用在一部讲**西班牙加那利群岛**故事的视频里，画面是否**明显不属于西班牙／南欧地中海**？\n"
              "yes = 能明确看出是**东亚**（中式日式室内、汉字日文招牌、榻榻米障子暖帘、东亚面孔）、\n"
              "**北欧/寒冷地区**（厚积雪、成排冷杉、深色木屋、极地影调）、**中东/非洲/南亚**、\n"
              "**北美**（摩天楼天际线、黄色校车、典型美国公路与加油站、白宫式建筑）、\n"
              "**英国/爱尔兰**（英式村舍、红砖排屋、双层巴士、红色电话亭），\n"
              "或**现代玻璃幕墙写字楼／现代钢构商场**等明显与加那利群岛无关的场景；\n"
              "no = 看得出是西班牙或南欧地中海（白墙小镇、赤陶瓦顶、火山黑礁海岸、棕榈、\n"
              "带铁艺栏杆的阳台、石铺老街、欧式老教堂），或者画面是中性的（器物/食物/桌面/\n"
              "光影/天空/水面/石头/花叶特写，看不出是哪个国家）。\n"
              "只回一个词：yes 或 no。"),
    # 2026-09-16 新增：当代中国/台湾题材（《目送》龙应台·台北/屏东潮州/浙江淳安，当代）
    # 二元问法，勿改多分类
    "china_contemporary": ("这张图如果要用在一部讲**当代中国／台湾故事**的视频里，画面是否**明显不属于中国／台湾**？\n"
                           "yes = 能明确看出是**欧美**（欧美城市街景与建筑、西式吧台与洋酒、欧美面孔与服饰、\n"
                           "英文字母招牌为主、白墙赤陶瓦的南欧小镇、阿尔卑斯石屋、北欧冷杉雪原）、\n"
                           "**中东/非洲/南亚/热带**（棕榈沙滩、纱丽长袍）、或**日式室内**（榻榻米、障子、暖帘和室）；\n"
                           "no = 看得出是中国或台湾（中文/繁体汉字招牌、骑楼与铁皮屋、庙宇红墙与香炉、\n"
                           "中式碗筷与炒锅、台北街景与捷运、台湾稻田与山景），\n"
                           "或者画面是中性的（器物/食物/桌面/光影/天空/水面/花叶/书籍特写，看不出是哪个国家）。\n"
                           "只回一个词：yes 或 no。"),
}
Q = QUESTIONS.get(TARGET, QUESTIONS["japan"])
QVER = hashlib.md5(Q.encode("utf-8")).hexdigest()[:8]   # 提示词版本：改问法即自动失效缓存


def api_key():
    """取 VL API key（2026-09-17 百炼停用→SiliconFlow）。
    环境变量与 .env 都收，但**过滤占位符/异常值**（曾因 .env 里是 `***`、环境里是旧值而静默失败）。"""
    cands = []
    for name in ("QC_VL_KEY", "DASHSCOPE_API_KEY", "SILICONFLOW_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(name, "")
        if v:
            cands.append(v)
    try:
        for line in Path("/root/.hermes/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            for nm in ("QC_VL_KEY", "DASHSCOPE_API_KEY", "SILICONFLOW_API_KEY", "OPENAI_API_KEY"):
                if line.strip().startswith(nm + "="):
                    cands.append(line.split("=", 1)[1].strip().strip('"').strip("'"))
    except Exception:
        pass
    for c in cands:
        c = (c or "").strip().strip('"').strip("'")
        if c and c not in ("***", "<set>") and len(c) > 20 and "..." not in c:
            return c
    return ""

KEY = api_key()


def _probe_ok(api: str, model: str, key: str) -> bool:
    """1-token 探活：判断 API/key/model 是否可用（SiliconFlow 余额不足 → code 30001）。"""
    if not key:
        return False
    fp = "/tmp/_qc_region_probe.json"
    with open(fp, "w") as fh:
        fh.write(json.dumps({"model": model, "max_tokens": 1,
                             "messages": [{"role": "user", "content": "hi"}]}))
    try:
        r = subprocess.run(["curl", "-s", "-m", "30", api, "-H", f"Authorization: Bearer {key}",
                            "-H", "Content-Type: application/json", "-d", f"@{fp}"],
                           capture_output=True, text=True, timeout=45)
        s = r.stdout or ""
        d = json.loads(s[s.find("{"):s.rfind("}") + 1])
        return bool(d.get("choices"))
    except Exception:
        return False


# 2026-09-17: 主 VL 探活失败（SiliconFlow 余额不足）→ 自动回落 DashScope qwen3-vl-flash。
if not _probe_ok(API, MODEL, KEY):
    # 2026-09-19：主备对调后，备路 = SiliconFlow（需时再启；余额恢复即自动可用）
    _alt, _altsrc = "", ""
    try:
        for _l in Path("/root/.hermes/.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if _l.strip().startswith("SILICONFLOW_API_KEY="):
                _alt = _l.split("=", 1)[1].strip().strip('"').strip("'")
                break
    except Exception:
        pass
    if _alt:
        print(f"⚠️ 主 VL（{MODEL}）探活失败 → 回落 SiliconFlow {os.environ.get('QC_VL_FALLBACK_MODEL', 'Qwen/Qwen3-VL-32B-Instruct')}")
        API = "https://api.siliconflow.cn/v1/chat/completions"
        MODEL = os.environ.get("QC_VL_FALLBACK_MODEL", "Qwen/Qwen3-VL-32B-Instruct")
        KEY = _alt


# 判定缓存路径：清单模式与全池分开（两边的键空间不同，混用会互相失效）。
# ROOT 在清单模式 = CWD（产物落 CWD），全池模式 = 素材根 ⇒ 载入与回写必须都用 _CF 这一个变量。
_CF = ROOT / ("_qc_region_picks_vlmcache.json" if LIST_MODE else "_qc_region_vlmcache.json")


def clips(root: Path):
    """2026-09-22：新增清单模式（005 提的差异）。
    清单文件 = JSON 数组或纯文本，每行 `<场景>/<文件>`/`<场景>/video/<文件>`/绝对路径
    ⇒ 用于「只核成片实际用到的那几十段」，比全池扫更快更省（与 qc_visual_scan.py 同语义）。
    相对路径解析顺序：QC_POOL_ROOT（默认 scenes 根）→ 场景根/video/ → 相对 CWD。"""
    if LIST_MODE:
        if ARG1_P.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
            return [ARG1_P]
        t = ARG1_P.read_text(encoding="utf-8", errors="ignore").strip()
        items = json.loads(t) if t.startswith("[") else [x.strip() for x in t.splitlines() if x.strip()]
        pool = Path(os.environ.get("QC_POOL_ROOT", "/mnt/d/AI软件/GitHub/bookmadebook/assets/scenes"))
        out = []
        for it in items:
            p = Path(it); cands = []
            if not p.is_absolute():
                cands = [pool / it, p]
                if len(p.parts) == 2:
                    sc, f = p.parts
                    cands = [pool / sc / "video" / f, pool / sc / f] + cands
                p = next((c for c in cands if c.exists()), cands[0])
            if p.exists():
                out.append(p)
        return out
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


def ask_one(img: Path, model: str = ""):
    """单帧独立调用（多帧必须独立问，合并问会互相污染）。
    2026-09-22：支持 model 覆盖（召回/确认两层）+ err 重试 2 次（防瞬时失败静默降 n）。"""
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {"model": model or MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": Q}]}], "max_tokens": 8}
    pj = TMP / f"pl_{(model or MODEL).replace('/', '_')}_{img.stem}.json"
    pj.write_text(json.dumps(payload), encoding="utf-8")
    for _try in range(3):
        r = subprocess.run(["curl", "-s", "-m", "120", "-X", "POST", API,
                            "-H", f"Authorization: Bearer {KEY}", "-H", "Content-Type: application/json",
                            "-d", f"@{pj}"], capture_output=True, text=True, timeout=180)
        try:
            t = json.loads(r.stdout)["choices"][0]["message"]["content"].strip().lower()
            if t.startswith("yes"):
                return "yes"
            if t.startswith("no"):
                return "no"
        except Exception:
            pass
        time.sleep(1.2 * (_try + 1))
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
        sys.exit("❌ 找不到 VL API key（QC_VL_KEY / SILICONFLOW_API_KEY / OPENAI_API_KEY）")
    cs = clips(ROOT)
    if not cs:
        # 2026-09-22 补（005 报：喂清单时打「0 段」后 Python 直接崩 NotADirectoryError）
        print("❌ 待检素材 0 段 —— 对象不存在/路径写错/清单为空。")
        print(f"   入参: {ARG1_P}（{'文件(清单)' if LIST_MODE else '目录'}）")
        print("   ⚠️ 0 段 ≠ 干净！这是「静默假通过」，绝不许当成通过。")
        sys.exit(3)
    print(f"{'清单 ' + str(ARG1_P) if LIST_MODE else '全池 ' + str(ARG1_P)} | 素材 {len(cs)} 段 | 目标 {TARGET} | "
          f"每片 {NFRAME} 帧独立投票 | 并发 {WORKERS}", flush=True)

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
    # 2026-09-26 补（007：查「0 段仍跑完并写空产物、退码 0」同类 bug）：
    #   入参非空但抽帧全失败（时长探测失败/解码失败/文件不可读）时，旧行为会写出空 report 并退 0
    #   ⇒ 下游把「没跑」当「全干净」。这是静默假通过，必须非 0 退出、不写 report。
    if not prep:
        print(f"❌ 抽帧后待检 0 段 —— 入参 {len(cs)} 段全部无法抽帧（时长/解码/权限失败）。")
        print(f"   入参: {ARG1_P}（{'文件(清单)' if LIST_MODE else '目录'}）")
        print("   ⚠️ 0 段 ≠ 干净！这是「静默假通过」，绝不许当成通过。未写任何 report。")
        sys.exit(4)
    # 2026-09-22：载入判定缓存（漏了这步会把上一轮缓存覆盖丢失 —— 自查发现并补上）
    global CACHE
    if not NO_CACHE and _CF.exists():
        try:
            CACHE = json.loads(_CF.read_text(encoding="utf-8"))
        except Exception:
            CACHE = {}
    print(f"   模型：召回 {MODEL}" + (f" → 可疑项确认 {CONFIRM_MODEL}" if CONFIRM_MODEL.lower() != "off" else "（❌ 确认层已禁用）")
          + f" | 缓存 {len(CACHE)} 条{'（已禁用 QC_NO_CACHE）' if NO_CACHE else ''}", flush=True)

    def one(item):
        c, fs = item
        rel = str(c.relative_to(ROOT)) if str(c).startswith(str(ROOT)) else str(c)   # 清单模式=绝对路径，护栏必加
        # 2026-09-22 缓存：键 = 相对路径|字节数|mtime|提示词版本|召回模型|目标轴（任一变化即失效）
        k = None
        try:
            st = c.stat()
            # 2026-09-26：确认层模型也入键（口径任一变化即失效）—— 与 qc_visual_scan.py 对齐，
            #   防「换确认模型后旧缓存继续命中」导致改档不生效。
            k = (f"{rel}|{st.st_size}|{int(st.st_mtime)}|{QVER}|{MODEL}|{CONFIRM_MODEL}"
                 f"|{TARGET}|n{NFRAME}")   # 帧数必须入键（3 帧的结论不能拿来回答 6 帧的请求）
        except Exception:
            k = None
        if k and not NO_CACHE and k in CACHE:
            e = CACHE[k]; hits["n"] += 1
            return rel, {"verdict": e["verdict"], "votes": e["votes"], "yes": e["yes"], "n": e["n"],
                         "model": e.get("model", MODEL), "cached": True,
                         "confirm_votes": e.get("confirm_votes"),
                         "confirm_yes": e.get("confirm_yes"), "confirm_n": e.get("confirm_n")}
        votes = [ask_one(f) for f in fs]
        calls["recall"] += len(fs)
        yes = sum(1 for v in votes if v == "yes")
        n = len([v for v in votes if v in ("yes", "no")])
        if n == 0:
            v = "unknown"
        elif yes * 2 > n:            # 多数票
            v = "suspect"
        else:
            v = "ok"
        out = {"verdict": v, "votes": votes, "yes": yes, "n": n, "model": MODEL, "cached": False}
        # 确认层：可疑项用 CONFIRM_MODEL 复判（终态判据线等同原 qwen-vl-max 方案）
        if v == "suspect" and CONFIRM_MODEL and CONFIRM_MODEL.lower() != "off":
            calls["confirm"] += len(fs)
            cv = [ask_one(f, CONFIRM_MODEL) for f in fs]
            cy = sum(1 for x in cv if x == "yes")
            cn = len([x for x in cv if x in ("yes", "no")])
            out["confirm_votes"], out["confirm_yes"], out["confirm_n"] = cv, cy, cn
            if cn:
                out["verdict"] = "suspect" if cy * 2 > cn else "ok"
        if k and not NO_CACHE:
            CACHE[k] = {kk: out.get(kk) for kk in
                        ("verdict", "votes", "yes", "n", "model", "confirm_votes", "confirm_yes", "confirm_n")}
        return rel, out

    res, done = {}, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for k, v in ex.map(one, prep):
            res[k] = v
            done += 1
            if done % 25 == 0 or done == len(prep):
                print(f"  {done}/{len(prep)}", flush=True)

    _rep = ROOT / ("_qc_region_picks_report.json" if LIST_MODE else "_qc_region_report.json")   # 清单模式另起名，防覆盖全池报告
    json.dump(res, open(_rep, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # 2026-09-26 补（同一「静默假通过」家族）：全部片段都拿不到 VL 结论（n==0 ⇒ unknown，
    #   典型是 API/模型不可用）时旧行为仍退 0。先落盘留证，再非 0 退出。
    if res and all(v["verdict"] == "unknown" for v in res.values()):
        print("❌ 全部片段 VL 未返回有效答案（n=0 ⇒ unknown）—— API/key/模型不可用，门禁等于没跑。")
        print(f"   报告已落盘留证：{_rep}，但不得当作通过。")
        sys.exit(5)
    if not NO_CACHE:
        try:
            _CF.write_text(json.dumps(CACHE, ensure_ascii=False), encoding="utf-8")
        except Exception as _e:
            print(f"   ⚠️ 缓存写入失败（不影响判定）：{_e}")
    sd = ROOT / ("_qc_region_picks_sheets" if LIST_MODE else "_qc_region_sheets"); sd.mkdir(exist_ok=True)
    for i in range(0, len(prep), 12):
        sheet(prep[i:i + 12], sd / f"sheet_{i//12:03d}.jpg")

    sus = [k for k, v in res.items() if v["verdict"] == "suspect"]
    unk = [k for k, v in res.items() if v["verdict"] == "unknown"]
    print(f"\n✅ {_rep}")
    print(f"   可疑(判为非目标地域) {len(sus)} 段 | 通过 {len(res)-len(sus)-len(unk)} 段 | 未返回 {len(unk)} 段")
    _cr, _cc = calls["recall"], calls["confirm"]
    print(f"💰 调用：召回 {_cr} 次（{MODEL}）+ 确认 {_cc} 次（{CONFIRM_MODEL}）| 缓存命中 {hits['n']} 段"
          f" | 本轴实付约 ¥{_cr*0.00011 + _cc*0.00106:.2f}（若全走 qwen-vl-max 需 ¥{(_cr+_cc)*0.00106:.2f}）")
    for k in sorted(sus, key=lambda x: -res[x]["yes"]):
        print(f"   ⚠️ {res[k]['yes']}/{res[k]['n']}票  {k}")
    print(f"\n拼图留档: {sd}（可疑项必须逐格放大人工确认，VL 也会误判）")


if __name__ == "__main__":
    main()
