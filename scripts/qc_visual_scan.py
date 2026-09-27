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

⚠️ 2026-09-19 补（《一个人的好天气》事故）：素材级判「真人正脸」时，**每片帧数不得低于 6 帧、
   且必须整段均匀铺开**（`每片帧数` 参数已支持环境变量 QY_FRAMES 覆盖）。原默认 3 帧且集中
   在片头 2.5s → 脸出现在片段中后段就漏检，导致 5 段含正脸素材进片、整片重渲。

用法：
  python3 scripts/qc_visual_scan.py <素材根|清单文件> <目标> [每片帧数=6] [并发=8]
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

产物：<素材根>/_qc_<目标>_report.json + _qc_<目标>_sheets/*.jpg + _qc_<目标>_vlmcache.json（判定缓存）

💸 成本设计（2026-09-22 降费改造，实测口径）：
   召回层 = qwen3-vl-flash（输入 ¥0.15/M，560px 帧 ≈ ¥0.00011/次）
   确认层 = qwen-vl-max（输入 ¥1.6/M，≈ ¥0.00106/次）—— **只跑被判「可疑」的那些段**
   阳性对照已过（51 帧逐帧一致，含曾漏检的正脸片段 hospital_room_empty/07）⇒ 召回能力不降级；
   可疑项仍由 max 复判 ⇒ **最终判据线等同原方案**。
   缓存：键 = 相对路径|字节数|mtime|提示词版本|召回模型|目标轴|帧数。同池重扫（过去每天 3-4 遍）几乎全命中。
   逃生阀：QC_NO_CACHE=1 强制全量重扫；QC_VL_MODEL / QC_VL_CONFIRM_MODEL 可覆盖两层模型。
⚠️ 只判「可疑」不当裁决 —— 可疑项必须逐格放大人工确认（VL 也会误判）。

⚠️ **抽样密度铁律（2026-09-14 实测）**：默认 3 帧**不够**！实测 `snow_landscape/04`（雪地公路
   上的汽车）—— 8 帧里只有 1 帧能看到车（车只在片段的某 1-2 秒出现），3 帧全错过 → **漏报**。
   源素材门禁必须 **≥8 帧/片**（`person_part 8 16` / `modern 8 16`）。
   注意：合成器只取源片段的**一个子窗口**，所以源级门禁必须扫满整片；
   而「成片实际用了什么」只有**对成片密采样**才能确认 —— 现行标准是 **每 1.5s 一帧**，
  外加**逐镜入点帧**（成片约 630s → ≥420 帧 + 每镜入点/入点+0.5s）。实现见
  `/root/.hermes/scripts/final_dense_scan.py`（mode=fixed|shots），本脚本只做**素材级**扫描。
"""
import os
import sys, json, os, base64, subprocess, hashlib, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw, ImageFont

ARG1 = sys.argv[1] if len(sys.argv) > 1 else "."
TARGET = (sys.argv[2] if len(sys.argv) > 2 else "person_part").lower()
NFRAME = int(sys.argv[3]) if len(sys.argv) > 3 else int(os.environ.get("QY_FRAMES", "6"))  # 2026-09-19：3→6，3 帧会漏检片段中后段的正脸
WORKERS = int(os.environ.get("QC_WORKERS") or (sys.argv[4] if len(sys.argv) > 4 else 4))  # 2026-09-16：8→4，14 核机器上 8 路 VL+8 路 ffmpeg 会把 load 推到 135
# ── 2026-09-22 降费改造（007）：召回层 / 确认层分离 ────────────────────────────
#   实测（本机真实抽帧发同一提示词、同一张图，逐帧对比 51 帧）：
#     qwen-vl-max  输入 ¥1.6/M、输出 ¥4/M   → 560px 帧 ≈ ¥0.00106/次
#     qwen3-vl-flash 输入 ¥0.15/M、输出 ¥1.5/M → 同一张 560px 帧 ≈ ¥0.00011/次（**便宜 10.7 倍**）
#   阳性对照（2026-09-22，35+16 帧逐帧一致 51/51）：
#     ① hospital_room_empty/07（曾漏检的女性 3/4 侧脸）max yes 8/8 = flash yes 8/8
#     ② hospital_room_empty/06（空诊室）       max no  8/8 = flash no  8/8
#     ③ moonlight_window_night/08（人影/剪影）  max yes 5/5 = flash yes 5/5
#     ④ chinese_courtyard_quiet/03（现代塔吊·modern 轴）max yes 5/5 = flash yes 5/5
#   ⇒ flash 召回能力与 max 一致 ⇒ **全量走 flash，只有判「可疑」的段再用 max 复判**。
#   安全设计：可疑项必须过 CONFIRM_MODEL（默认仍是 qwen-vl-max）复判后才定终态，
#             所以最终判据线不降级（等同原方案），只是把 90% 的"必然 no"流量换成了便宜 10.7 倍的模型。
#   逃生阀：QC_VL_CONFIRM_MODEL=off / =qwen-vl-max 可一键切换确认层（做 A/B 用）。
#   ⚠️ 2026-09-26（007 裁定，三轮可复现实测）：
#     **qwen-vl-max 做人脸判据线会系统性漏判** —— 真违规召回 0/3（旧提示词下亦 0/3 复现）、
#     阴性误报 1/8；而 qwen3-vl-flash 真违规 3/3、阴性误报 0/7。max 正是「5 段真人脸素材在
#     池体检里被全判 clean、最终混进成片」的根因。故 **person_part(人脸轴) 默认确认层=off（flash 单跑）**。
#     地域轴/现代轴无今日证据支持撤下 ⇒ 仍保留 qwen-vl-max 确认层，不动。
#     （另：本轮实测「把 YOLO 命中点追加进 VL 帧集」A/B 逐段 14/14 零改善、成本 +67%；
#       且 YOLO 是「有人」探测器不是「正脸」探测器 ⇒ 不得参与人脸红线。）
MODEL = os.environ.get("QC_VL_MODEL", "qwen3-vl-flash")  # 召回层（2026-09-22 起默认 flash；原为 qwen-vl-max）
_DEFAULT_CONFIRM = "off" if TARGET == "person_part" else "qwen-vl-max"
CONFIRM_MODEL = os.environ.get("QC_VL_CONFIRM_MODEL", _DEFAULT_CONFIRM)  # 确认层；person_part 默认 off
API = os.environ.get("QC_VL_API", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
TMP = Path(f"/tmp/qc_vl_{TARGET}"); TMP.mkdir(exist_ok=True)   # 2026-09-17: 每轴独立临时目录（同轴并发时共用 /tmp/qc_visual 会互相覆盖抽帧，导致问的图与实际采样点不符）

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
    # 2026-09-15 新增：《莫斯科绅士》1922-1954 莫斯科，地域轴走快速引擎
    # （qc_region_scan.py 同机实测慢 25 倍，已弃用该轴；二元问法不变）
    "russia": ("这张图如果要用在一部讲**1920-1950 年代俄国故事**的视频里，画面是否**明显不属于俄国／欧洲**？\\n"
               "yes = 能明确看出是**东亚**（日式榻榻米/暖帘/拉门/障子/中文日文招牌/和服/东亚面孔与服饰）、"
               "中东、非洲、南亚、热带（棕榈/沙滩）、北美（摩天楼天际线、黄色校车、美国公路与加油站）、"
               "或者**现代玻璃幕墙写字楼／现代都市**等明显不是旧时代俄国的场景；\\n"
               "no = 看得出是俄国或欧洲（东正教洋葱头穹顶、石砌或砖砌老建筑、欧式老酒店与老街、"
               "积雪街道与松林、旧式室内与旧木家具、烛光与暖黄灯），"
               "或者画面是中性的（食器/器物/桌面/光影/天空/水面/花叶/酒瓶/书页特写）。\\n"
               "只回一个词：yes 或 no。"),
    "product_shot": ("这张图看起来是不是**现代商业静物摄影/商品广告照**的观感？\\n"
                     "yes = 影棚式打光、纯色或渐变背景、浅景深强虚化、商品摆拍构图"
                     "（精油瓶/滴管瓶/胶囊瓶/标准化包装、标签印刷精美、道具刻意摆放、色彩鲜艳统一）；\\n"
                     "no = 自然记录感、实拍场景、老照片质感、文物与器物记录照、食材原样摆放。\\n"
                     "只回一个词：yes 或 no。"),
    # 2026-09-16 新增：《温柔的夜》三毛·西班牙加那利群岛（当代西班牙海岛题材）
    # 二元问法，勿改多分类
    "spain": ("这张图如果要用在一部讲**西班牙加那利群岛**故事的视频里，画面是否**明显不属于西班牙／南欧地中海**？\\n"
              "yes = 能明确看出是**东亚**（中式日式室内、汉字日文招牌、榻榻米障子暖帘、东亚面孔与服饰）、\\n"
              "**北欧/寒冷地区**（厚积雪、成排冷杉、深色木屋）、**中东/非洲/南亚**、\\n"
              "**北美**（摩天楼天际线、黄色校车、典型美国公路与加油站）、\\n"
              "**英国/爱尔兰**（英式村舍、红砖排屋、双层巴士、红色电话亭），\\n"
              "或**现代玻璃幕墙写字楼／现代钢构商场**；\\n"
              "no = 看得出是西班牙或南欧地中海（白墙小镇、赤陶瓦顶、火山黑礁海岸、棕榈、\\n"
              "铁艺栏杆阳台、石铺老街、欧式老教堂），或者画面是中性的（器物/食物/桌面/\\n"
              "光影/天空/水面/石头/花叶特写，看不出是哪个国家）。\\n"
              "只回一个词：yes 或 no。"),
}
Q = QUESTIONS.get(TARGET, QUESTIONS["person_part"])
QVER = hashlib.md5(Q.encode("utf-8")).hexdigest()[:8]   # 提示词版本：改问法即自动失效全部缓存
NO_CACHE = bool(os.environ.get("QC_NO_CACHE"))          # QC_NO_CACHE=1 强制全量重扫（逃生阀）
CACHE = {}                                              # 由 main 从 <ROOT>/_qc_<target>_vlmcache.json 载入
hits = {"n": 0}                                         # 缓存命中数
calls = {"recall": 0, "confirm": 0}                     # 实际调用数（分层计数）


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
    """1-token 探活：API/key/model 是否可用（SiliconFlow 余额不足会返回 code 30001）。"""
    if not key:
        return False
    fp = "/tmp/_qc_probe.json"
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


# 2026-09-17: SiliconFlow 账号余额不足（code 30001）→ 自动回落 DashScope（qwen3-vl-flash）。
# 不回落的话所有 VL 门禁会静默全返 err（verdict=unknown）＝门禁等于没跑。
# 实测校准：与 SiliconFlow Qwen3-VL-32B 在《边城》16 段已知样本上 16/16 一致。
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


def ask_one(img: Path, model: str = ""):
    """单帧单次调用。2026-09-22 起：① 支持 model 覆盖（召回/确认两层）② err 自动重试 2 次
    —— 实测 flash 偶发瞬时失败（同一张图 8 帧里 1 帧返回空），重试即恢复；
    不重试会把 err 记进 votes 而静默降 n，等于偷偷降低判据强度。"""
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {"model": model or MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": Q}]}], "max_tokens": 8}
    pj = TMP / f"pl_{(model or MODEL).replace('/', '_')}_{img.stem}.json"
    pj.write_text(json.dumps(payload), encoding="utf-8")
    for _try in range(3):                       # 2026-09-22：err 重试 2 次（防瞬时失败静默降 n）
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
    cs = clips()
    if not cs:
        print(f"❌ 待检素材 0 段 —— 对象不存在/路径写错/清单为空。")
        print(f"   入参: {ARG1}（{'文件' if LIST_MODE else '目录'}）")
        print(f"   ⚠️ 0 段 ≠ 干净！这是「静默假通过」，绝不许当成通过。")
        sys.exit(3)
    mode = f"清单 {ARG1}" if LIST_MODE else f"全池 {ARG1}"
    # 2026-09-22：载入判定缓存（同素材+同问法+同模型 → 免重复 VL）
    global CACHE
    _cf = ROOT / f"_qc_{TARGET}_vlmcache.json"
    if not NO_CACHE and _cf.exists():
        try:
            CACHE = json.loads(_cf.read_text(encoding="utf-8"))
        except Exception:
            CACHE = {}
    print(f"{mode} | 素材 {len(cs)} 段 | 目标 {TARGET} | 每片 {NFRAME} 帧独立投票 | 并发 {WORKERS}", flush=True)
    print(f"   模型：召回 {MODEL}" + (f" → 可疑项确认 {CONFIRM_MODEL}" if CONFIRM_MODEL.lower() != "off" else "（❌ 确认层已禁用）")
          + f" | 缓存 {len(CACHE)} 条{'（已禁用 QC_NO_CACHE）' if NO_CACHE else ''}", flush=True)

    prep = []
    # 并发抽帧（2026-09-14：串行时 249 段要 5 分钟，是整条门禁的瓶颈）
    def prep_one(c):
        d = dur(c)
        if d <= 0:
            return None
        fs = []
        for k in range(NFRAME):
            t = sample_t(d, k, NFRAME)
            o = TMP / f"{hashlib.md5(str(c).encode()).hexdigest()[:10]}_{k}.jpg"
            if grab(c, t, o):
                fs.append(o)
        return (c, fs) if fs else None
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(prep_one, cs):
            if r:
                prep.append(r)
    print(f"抽帧完成 {len(prep)} 段（{sum(len(f) for _, f in prep)} 次 VL 调用）", flush=True)
    # 2026-09-26 补（007：查「0 段仍跑完并写空产物、退码 0」同类 bug）：
    #   入参非空但抽帧全失败（时长探测失败/解码失败/文件不可读）时，旧行为会写出空 report 并退 0
    #   ⇒ 下游把「没跑」当「全干净」。这正是 pool_certify 那类静默假通过，必须非 0 退出。
    if not prep:
        print(f"❌ 抽帧后待检 0 段 —— 入参 {len(cs)} 段全部无法抽帧（时长/解码/权限失败）。")
        print(f"   入参: {ARG1}（{'文件' if LIST_MODE else '目录'}）")
        print("   ⚠️ 0 段 ≠ 干净！这是「静默假通过」，绝不许当成通过。未写任何 report。")
        sys.exit(4)

    def one(item):
        c, fs = item
        rel = str(c.relative_to(ROOT)) if str(c).startswith(str(ROOT)) else str(c)
        # ── 2026-09-22 缓存（降重复扫描）──────────────────────────────────────────
        #   键 = 相对路径|字节数|mtime|提示词版本|召回模型|目标轴 ⇒ **内容或口径任一变化即失效**。
        #   为什么不违反「继承池须重跑门禁」：那是**选材侧**名单（_excluded/黑名单）的规则；
        #   本轴判的是「这段素材本身有没有人/现代物」= 片子的物理属性，只要文件没变、问法没变，
        #   结论就不会变。名单更新照旧在全量重扫里生效（名单变化 → 该段被排除，与本缓存无关）。
        k = None
        try:
            st = c.stat()
            # 2026-09-26：确认层模型也入键 —— 否则「max→off」换档后旧缓存（max 洗白的 ok）会继续命中，
            #   人脸轴改档等于没生效。口径（召回模型/确认模型/问法/帧数）任一变化即失效。
            k = (f"{rel}|{st.st_size}|{int(st.st_mtime)}|{QVER}|{MODEL}|{CONFIRM_MODEL}"
                 f"|{TARGET}|n{NFRAME}")   # 帧数必须入键（3 帧的结论不能拿来回答 6 帧的请求）
        except Exception:
            k = None
        if k and not NO_CACHE and k in CACHE:
            e = CACHE[k]
            hits["n"] += 1
            return rel, {"verdict": e["verdict"], "votes": e["votes"], "yes": e["yes"], "n": e["n"],
                         "model": e.get("model", MODEL), "cached": True,
                         "confirm_votes": e.get("confirm_votes"),
                         "confirm_yes": e.get("confirm_yes"), "confirm_n": e.get("confirm_n")}
        votes = [ask_one(f) for f in fs]
        calls["recall"] += len(fs)
        yes = sum(1 for v in votes if v == "yes")
        n = len([v for v in votes if v in ("yes", "no")])
        v = "unknown" if n == 0 else ("suspect" if yes * 2 > n else "ok")
        out = {"verdict": v, "votes": votes, "yes": yes, "n": n, "model": MODEL, "cached": False}
        # ── 确认层：可疑项用 CONFIRM_MODEL 复判（最终判据线等同原 qwen-vl-max 方案，不降级）
        if v == "suspect" and CONFIRM_MODEL and CONFIRM_MODEL.lower() != "off":
            calls["confirm"] += len(fs)
            cv = [ask_one(f, CONFIRM_MODEL) for f in fs]
            cy = sum(1 for x in cv if x == "yes")
            cn = len([x for x in cv if x in ("yes", "no")])
            out["confirm_votes"] = cv
            out["confirm_yes"] = cy
            out["confirm_n"] = cn
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

    prefix = TARGET if not LIST_MODE else f"{TARGET}_picks"
    json.dump(res, open(ROOT / f"_qc_{prefix}_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # 2026-09-26 补（同一「静默假通过」家族）：全部片段都拿不到 VL 结论（n==0 ⇒ unknown，
    #   典型是 API/模型不可用）时，旧行为仍退 0，下游会把「门禁等于没跑」当通过。先落盘留证，再非 0 退出。
    if res and all(v["verdict"] == "unknown" for v in res.values()):
        print("❌ 全部片段 VL 未返回有效答案（n=0 ⇒ unknown）—— API/key/模型不可用，门禁等于没跑。")
        print(f"   报告已落盘留证：{ROOT / f'_qc_{prefix}_report.json'}，但不得当作通过。")
        sys.exit(5)
    # 2026-09-22：回写缓存（供下次同池扫描免调 VL）
    if not NO_CACHE:
        try:
            _cf.write_text(json.dumps(CACHE, ensure_ascii=False), encoding="utf-8")
        except Exception as _e:
            print(f"   ⚠️ 缓存写入失败（不影响判定）：{_e}")
    sd = ROOT / f"_qc_{prefix}_sheets"; sd.mkdir(exist_ok=True)
    for i in range(0, len(prep), 12):
        sheet(prep[i:i + 12], sd / f"sheet_{i//12:03d}.jpg")

    sus = [k for k, v in res.items() if v["verdict"] == "suspect"]
    unk = [k for k, v in res.items() if v["verdict"] == "unknown"]
    _cr, _cc = calls["recall"], calls["confirm"]
    _cost = _cr * 0.00011 + _cc * 0.00106          # 实测单价：flash ¥0.00011/次、max ¥0.00106/次（560px 帧）
    print(f"\n✅ {ROOT/f'_qc_{prefix}_report.json'}")
    print(f"   可疑 {len(sus)} 段 | 通过 {len(res)-len(sus)-len(unk)} 段 | 未返回 {len(unk)} 段")
    print(f"💰 调用：召回 {_cr} 次（{MODEL}）+ 确认 {_cc} 次（{CONFIRM_MODEL}）| 缓存命中 {hits['n']} 段"
          f" | 本轴实付约 ¥{_cost:.2f}（若全走 qwen-vl-max 需 ¥{(_cr+_cc)*0.00106:.2f}）")
    for k in sorted(sus, key=lambda x: -res[x]["yes"]):
        print(f"   ⚠️ {res[k]['yes']}/{res[k]['n']}票  {k}")
    print(f"\n拼图留档: {sd}（可疑项必须逐格放大人工确认，VL 也会误判）")


if __name__ == "__main__":
    main()
