---
name: audiobook-video-composition
description: 把讲书音频做成竖版实景动态视频(小红书推广)。Unsplash实景图+Ken Burns+xfade+金句。
---

# 讲书音频 → 实景动态视频合成

把 listen-book 生成的精读音频（或任何讲书 MP3）升级为 1080×1920 竖版视频，用于小红书/抖音推广。核心代码：`bookmadebook/scripts/video_composer.py`（仓库内，可复制改造）。

## 触发条件
- 用户要"把音频做成视频/配画面/推广视频"
- 讲书/精读内容需要发布到短视频平台
- 任何"音频→视频"的竖版合成需求

## 核心设计原则（用户 2026-08-07 三轮确认，勿偏离）
1. **实景写实照片**（Unsplash 免费图库下载），**不用 AI 生图、不用 PIL 手绘插画**——用户明确否掉过程序绘制版（"更换为偏实景写实类的动态画面"）
2. **同主题连贯画面**——如沙漠星空系列（黄昏→蓝调→夜空自然渐变）、海洋系列；**避免场景跳跃**（用户否掉过雪山/沙漠/玫瑰/太空/狐狸/日落六种无关场景硬切）
3. **交叉溶解过渡**（xfade 1.5s），不要硬切
4. **文字只保留金句 + 书名**（淡入淡出 + 黑描边），章节标题卡也去掉（用户："文字只需要出现金句即可"）
5. 画面必须"活的"：Ken Burns 缓慢缩放（zoompan），星星/粒子/运动感——用户否掉过纯静态卡片缩放版

## 场景自动选择（2026-08-11 升级，scene_selector.py）
- **决策优先级**：`--theme` 手动指定 > 讲书稿内【场景：XX】标记 > 自动检测 > 兜底 desert
- **自动检测 = 加权统计，不要直接复用 detect_content_type 的首命中逻辑**！它按 CONTENT_VOICES 顺序返回第一个命中类型——张居正传含"汇报"（职场词）+"皇帝/王朝/明朝"×5（历史词），首命中会误判成职场/tech_city。**修复：统计各类型命中关键词数，取命中最多者**（`sum(1 for kw in keywords if kw in text)`）
- **内容类型→主题映射**：历史→palace（账号主力内容）、悬疑→rain、励志→sunrise、情感→warm_home、童话→forest、职场→tech_city、兜底→desert
- **主题扩充（2026-08-13《董氏父子》定案）**：船王/航运→ship（Pexels 搜 "container ship cargo ship" 集装箱货轮，EVERGREEN 巨轮+拖轮，港口感）；香港/政坛/特首→hongkong（Pexels 搜 "victoria harbour hong kong skyline" 香港天际线，IFC/中银/摩天轮为地标判据）；战争/军事/士兵→ww2（士兵剪影图）。**新增主题注册三处**：scene_selector.py 关键词表 + scene_library.py 的 THEME_CN 中文名 + assets/scenes/<theme>/ 目录落图，缺一不可
- **【场景：XX】标记**：讲书稿章节内写 `【场景：宫殿】`（支持中文别名表：宫殿/古建/皇宫/历史→palace 等），多章节可换场景；段时长优先 ffprobe 音频章节（ID3v2 CHAP），取不到按字数比例
- **⚠️【场景】标记位置铁律（2026-08-13《二战战史》二次返工根因）**：标记必须放在 `## 章节标题` **正上方**——放标题下方会导致章节标题错位一格、画面与讲述内容错位（用户「画面和内容完全不符」）；**每个章节都必须有标记——漏标章节会被并入上一段**（2026-08-13《董氏父子》案例：第四章特首八年+结尾漏标，dry-run 只出 4 段、结尾被吞进第三章）；相邻章节同主题标记不会合并（解析器已修，只合并 <50 字符内重复）；音频 CHAP 数 ≠ 标记数时按字数比例分配（`==` 才用章节边界，`>=` 会让末段吞掉全部剩余时长）。**合成前 dry-run 逐段核对「段数==章节数、时间窗=章节标题」再合成**（dry-run 秒级，合成 15 分钟）；dry-run 发现段数不足先补标记，不用重录音频（【场景】是未知注解，ted_director 会忽略，不影响 TTS）
- **⚠️ 素材语义目检必须问「画面主体与主题语义一致吗」**（2026-08-13 案例：desert 主题实际是银河星空/蓝天白云——vision 只确认「无人物」漏判语义，北非章节配星空画面被用户否掉）。只确认「无人物/能下载/非错图」不够，要确认「这是沙漠」
- **⚠️ Pexels 城市/地标类搜索会混入相似城市（2026-08-13《董氏父子》案例）**：搜 "hong kong skyline" 返回的 3 张里 1 张是**里斯本港口**（贝伦塔+塔霍河，与香港同为海滨高楼城貌）。**城市类素材落地必须用标志性地标目检**：香港认 IFC/中银大厦/摩天轮，混入相似城市（里斯本/迪拜/新加坡）整批筛选，错图直接删不入库；合成后按场景段抽帧复检（用户「画面和内容不符合」第二例根因）
- **`--dry-run` 只输出场景规划**（调试用），`--scene-from auto|script|manual` 控制来源

## 本地素材库（2026-08-11，scene_library.py + manifest.json）
- 素材组织：`assets/scenes/<theme>/`（随仓库分发）+ `~/.cache/bookmadebook/scenes/<theme>/`（联网补图缓存）+ `fallback/`（断网兜底渐变图）
- **降级链**：本地素材 → 缓存 → 联网下载（manifest URL）→ 兜底 desert → 渐变图 → 报错退出。缺主题不中断出片（黄色警告）
- **本地素材库现状（2026-08-11 晚，30 张全部目检，离线可出片）**：palace 6张（Pexels 竖版金顶/屋檐脊兽/红墙光影/宫殿群 4 张 + Unsplash 太和殿/长城 2 张，历史/传记类主力）、desert 4（沙丘×3+蓝天）、rain 3（雨夜街景，已补）、warm_home 3（壁炉暖光，已补）、tech_city 5（办公室+城市夜景 2 张 + Pexels 夜景 3 张，经济/商务类主力）、forest 2、ocean 2、sunrise 2、starry 2、snow 2、library 2。manifest.json 只保留人工目检过的 URL，11 主题
- **下载用 wget 不用 curl**：Unsplash 网络慢时 curl 常 `rc=28` 超时但文件已截断（st_size 正好 512KB 整数倍=下载中断），PIL `im.load()` 报 `image file is truncated`。wget `--tries=2 --timeout=30` 对慢速网络更稳；下载后必须 `im.load()` 强制完整加载检测截断
- **manifest 里猜的 Unsplash photo ID 大多 404 或内容不符**：盲猜 ID 命中率极低（实测 10 个猜 7-8 个 404，且"有效"的可能是耳机图/家庭合影/布加迪/按摩图）。**素材落地必须逐张下载后 vision_analyze 确认内容再入 manifest**；`source.unsplash.com` 已下线勿用；Wikimedia 直连在 WSL 可能被墙
- **素材获取首选 Pexels API（2026-08-11 定案，scene_fetcher.py）**：`api.pexels.com` 在 WSL 网络可达（无 key 返回 401 JSON = 正常，注册即用）；免费注册；支持 `orientation=portrait`（竖版 9:16）+ 视频搜索 `/v1/videos/search`（230k+ 免费视频，选 HD 竖版文件）。**Pexels/Pixabay/Unsplash 网页全部 Cloudflare 反爬**（浏览器和 curl 都被挡 "Just a moment..."），网页抓取不可行；Openverse/Wikimedia API 在 WSL 被墙。用法：`python scripts/scene_fetcher.py --theme palace --download 3`（key 自动读 `~/.hermes/keys/pexels.txt` 或 `PEXELS_API_KEY` 环境变量），先 `--download 0` 看列表+目检再落盘
- **⚠️ Pexels CDN 下载必须 curl + UA 头**（2026-08-11 实测）：`images.pexels.com` 拒绝无 UA 的 wget（rc=8），**必须 `curl -sL -f --max-time 40 -H "User-Agent: Mozilla/5.0 ..." -o dst.jpg <url>`**；API 返回的是缩略图 URL（`w=940&h=650`），落库前剥掉参数换 `?w=2160`（scene_fetcher `--size "w=2160"` 已封装）；下载后仍要 PIL `im.load()` 校验（truncated 删掉重下）
- **⚠️ scene_fetcher `--download` 必须带 `--theme` 或 `--out`**（2026-08-11 实测）：只给 `--search ... --download N` 会静默跳过下载只打印候选（exit 0 无报错）——落盘前 `ls` 目标目录确认张数
- **⚠️ 不要用 photo ID 拼 CDN URL**（2026-08-11 实测）：API 返回的 `id` 字段（如 6336x9504）不是 `images.pexels.com/photos/<id>/...` 的路径段——盲拼会 404/空文件。**必须用 API 返回的 `url` 字段**（`src.original`/`src.large2x` 或列表里的 url），只替换 w/h 查询参数

## PIL 文字层（2026-08-11 升级，text_layers.py，替代 drawtext）
- **为什么换**：drawtext 中文转义坑（`:` `'` `,` 全要转义）、无自动断行（14 字硬切）、描边阴影参数爆炸、进度条几乎无法实现。PIL 预渲染透明 PNG + ffmpeg overlay：渲染一次、无转义、按像素语义断行、天然支持描边阴影
- **7 层结构**：book 书名(0-8.5s 淡出) / chapter_N 章节标签(闪现≤5s) / quote_N 金句(64px，长句56px，白字黑描边+阴影) / attribution 出处(仅最后金句) / progress_track + progress_fill(进度条) / watermark
- **进度条实现**：轨道层常驻 + 填充层 `crop=w=max(2\,iw*min(t/DUR\,1)):h=ih` 随时间增长（**注意 `\,` 转义，filter_complex 内不能有未转义逗号**）
- **布局规范（小红书安全框）**：文字限 x140-920 / y220-1600（底部15%被操作栏挡、右侧被按钮列挡）；书名 y≈250 居中、金句块中心 y≈980、进度条 y1530、水印 y1420 左下
- **字体商用合规**：微软雅黑不可随开源项目分发（版权风险）→ 换思源黑体/宋体（Noto CJK，OFL 免费商用，WSL 路径 `/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc`）

## PIL 文字层陷阱（2026-08-11 实测排障）
- **PNG 临时目录被 GC 删除**：text_layers 内部 `TemporaryDirectory` 在函数返回后被垃圾回收 → ffmpeg 报 `Error opening input file .../book.png`。**修复：模块级 `_KEEPALIVE = []` 列表保存 TemporaryDirectory 引用**（`_KEEPALIVE.append(td)`）
- **PNG 输入索引偏移**：filter 里 `[{idx}:v]` 的 idx = **图片输入数 + PNG 序号**（`png_base = n_images`），不是 `len(png_inputs)`——n 张图占 [0..n-1]，PNG 从 [n] 开始
- **文字层时间基准用 audio_dur 不用 xfade 累计 total**：xfade 循环的 total 是叠加后累计时长（差 1.5s/张），章节/金句时间窗应基于音频总时长

## 前 60 秒吸引力优化（2026-08-30 引入，小红书算法适配）

> 目标不是"好看"是"完播+互动"：CES 权重评论/转发/关注是点赞 4-8 倍；完播率每+10% CES 额外+15%；3 秒判定生死。

### 开场冲突钩子（讲书稿模板 ted_mode.txt 已强化）
- 第一句**必须**是冲突钩子（反常识/悬念/痛点/画面），**禁介绍句**（"今天给大家推荐一本书"→算法秒退）
- 开场 3 句只占 ~40 字，抛冲突不急着回答

### ⚠️ 60s 钩子模式定稿（2026-08-30 用户验收通过「这个不错，以后钩子就这样做」）
**AI 生成声明必须放音频尾端，开头 0-2s 直接出钩子**（streaming_pipeline `seg_files.append(disclosure_path)` 而非 insert(0)）。《标识办法》允许末尾标识；开头声明会打断前 3 秒留存。验证：开头 0-2s 音频能量非静音（钩子语音）、片尾 55-58s 有声明语音；开头画面无"本音频由AI生成"字样。
- 用户原话：「开头直接出钩子，把现有的本音频由AI生成的说明放在60秒的尾端，目的还是为了从一开始就吸引听众」
- **时间轴模板（60.4s 实测）**：0-2s 钩子句+书名帧 → 2-4s 停顿悬念 → 12s 首句金句字卡 → 19-36s 双主题交替段 → 43s 末句金句 → 52.8s CTA 帧淡入（完整版在主页/评论报书名）→ 55-58s AI 声明语音（片尾）
- **⚠️ 短版有 CTA 时末句金句不得保持到片尾**（2026-08-30 重叠 bug）：末句金句 y≈980 与 CTA y≈980 同区域，双双保持到结束会叠字。`has_cta` 时末句金句限时 6s 淡出让位
- 历史传记类禁 husky_tender（散文声），必须 hist_deep_male（`qwen-tts-vd-hist_deep_male-voice-20260821204552033-d7bc`）

### 首句金句前压 ≤12s（video_composer._quote_times）
- 2026-08-18 定 22s → 2026-08-30 再前压到 **12s**（3s 判定后第一个记忆点尽快出现，前 60s 必有字卡截图点）

### 短版双主题交替（scene_selector，audio_dur ≤90s 自动触发）
- 60s 钩子版/精华版强制 `主→备→主` 三段交替（每段 1/3），解决"全是蜡烛/全是宫殿"素材雷同
- 对照表 SHORT_THEME_ALT：warm_home→library、palace→starry、desert→starry、ww2→arctic 等（视觉差异大）
- 10min 长版**不受影响**（保持单一主题）
- 60s 版 xfade 建议缩到 0.8s、金句字卡 3-4 个、结尾留"完整版预告+评论报书名"CTA

### P1 落地（2026-08-30）
- **短版金句门**（quality_gate）：`--target-minutes ≤1.2` 时【金句】≥3 句（FAIL 拦截）、>4 句警告——60s 版 3-4 句字卡是截图传播点
- **短版金句显示 6s**（video_composer `_quote_times` 之后）：≤90s 版每句字卡 6s（3-4 句不重叠），长版仍 12s
- **结尾 CTA 帧**（text_layers.render_cta + video_composer）：短版片尾最后 4s 淡入「完整版精读在主页 / 评论区报书名，帮你点单」——蔡格尼克+评论权重×4；长版不加（末尾是金句升华）
- **开场自动提速**（streaming_pipeline TED 导演层）：第一块未标情绪/金句/放慢时自动 rate +8%（开场 15s 紧迫感，3s 判定优化）；写稿人标注优先不被覆盖
- **音效锚点 --sfx tick**（video_composer 可选，默认 none=纯人声红线）：开场+每 20s 一个 65Hz 柔和钟声（volume=0.016≈-36dB，lowpass 400Hz），仅听觉锚点不喧宾夺主。用法：`video_composer.py ... --sfx tick`

## 标准流程
1. **写讲书稿**（5分钟≈1150-1200字，含【金句】标记）→ 过 quality_gate 质量门（TED风格语速≈240字/分）
2. **生成音频**：`streaming_pipeline.py -f 稿.txt --voice zh-CN-YunjianNeural --style ted --target-minutes N`
3. **下载同主题实景图**（6张以内，Unsplash `?w=2160&q=80`），逐张 curl（网络不稳时单张限时+校验大小）
4. **竖版裁剪**：PIL 中心裁剪到 1080×1920（LANCZOS），处理"太宽/太高"两种 case
5. **合成**：ffmpeg 逐图 Ken Burns → xfade 串联 → drawtext 金句 → 混入音频
6. **验证**：抽帧检查（金句时段有字、非金句时段干净、过渡区重叠）→ 压缩 crf 28 → 交付

## 关键 ffmpeg 语法要点
- **Ken Burns**：先 `scale=2160:3840` 放大再 zoompan，`d=时长*25`，`s=1080x1920:fps=25`，奇数段放大/偶数段缩小交替
- **⚠️ 必须 cover 模式防拉伸（2026-08-11 用户反馈"字体压太扁"根因）**：`scale=2160:3840` 直接拉伸会让横图素材变形（故宫屋顶压扁/长城走样）。**标准写法：`scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,zoompan=...`** —— 横图先等比放大铺满再居中裁剪，比例不失真。横图素材无需预裁剪，cover 模式运行时处理。验收：目检画面比例正常
- **xfade 串联**：`[v0][v1]xfade=transition=fade:duration=1.5:offset=前段累计-1.5[x1]`，每段 trim 要 `段长+1.5` 留过渡余量
- **drawtext 淡入淡出**：`alpha='if(lt(t,ts+1),0,if(lt(t,ts+2),(t-ts-1),if(lt(t,te-1),1,if(lt(t,te),(te-t),0))))'`；白字必加 `borderw=3:bordercolor=black@0.6`（实景背景可读性）
- **中文字体**：`/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc`（WSL），Windows 端需另找字体路径

## 金句提取（video_composer.extract_quotes）
- 只认 `【金句】` 标记；标记后常是"叙述+「」嵌套"——**优先取最后一个「」引号内内容**，再按 `[。！？]` 截断到第一句
- 长度过滤 6-40 字；正则捕获宽度要 ≥120 字符（否则长句引号未闭合导致 inner 匹配失败）
- **讲书稿必须含【金句】标记，否则视频无字幕（2026-08-10 张居正传实测）**：先写稿生成音频、后补金句标记再做视频 → 首轮 "提取金句: 0 句"。**正确顺序：写稿时就把金句行标【金句】（如 `【情绪：激昂】【金句】"…"`），先过质量门/生成音频，再合成视频**——TED 解析器对【金句】做前停顿+慢速+重读（音频也受益），video_composer 同时提取为字幕（一举两得）。建议 2-4 句，取书中最有冲击力的原句。
- **⚠️【金句】必须独占一行（2026-08-13《冬牧场》45min 案例）**：行内【金句】（嵌在段落中间）会被 TTS 当正文朗读出来、且 video_composer 提取不到（正则按行匹配）→ 视频金句丢失。**合并/改写讲书稿后必须 `grep -n "【金句】"` 检查：非行首的金句拆成独立行**（引号内文字单独成段）。45 分钟稿三处行内金句（259/272/276 行）因此修复
- **金句去重（2026-08-13 并行写稿案例）**：多子代理分段写稿合并后，同一金句可能被两个代理各写一次（如"人之所以能够感到幸福"在第一章和第四章重复）——合并后用脚本统计金句前 15 字符去重，重复的换新句或删除

- **⚠️ 金句时间轴铁律（2026-08-14《朱元璋》10min 实测 bug + 修复）**：音频 CHAP 数量 = 分段数（10min 音频 23 段 = 14 个 CHAP 起点），**远大于金句数（4-6）**。video_composer 原逻辑 `audio_chapter_starts[qi]`（取前 N 个 CHAP 起点）→ 4 句金句全堆开头（0/6.9/48.6/49.1s），末句还霸屏到片尾（49s→608s 同一句）。**已修复为 `_quote_times()`**：金句在讲书稿中字符位置比例 × 总时长线性映射（前缀匹配前 12 字抗标点差异；不用 CHAP 取整——CHAP 后半段稀疏会再次聚集）。**改稿/加金句后必须验证金句时间分布**（`python3 -c "import sys;sys.path.insert(0,'scripts');import video_composer as vc;print(vc._quote_times(quotes,script,starts,dur))"` 看是否均匀）再合成；合成后按各金句 ts 抽帧复检（避免旧式"抽 80%+ 必见末句"——末句现在不一定保留到片尾）
- **⚠️ 末句金句不再无条件保留到片尾（2026-08-14 V4 修复，替代旧"字幕保留到视频结束"）**：末句金句**仅当距片尾 ≤18s 才持续到结束**（升华收束），否则同样限时 12s 淡出（原逻辑 from 49s 霸屏到 608s 被用户侧抽帧发现）。交付前抽片尾帧确认
- **⚠️ 用户上传音频 = 音轨基准（2026-08-15《朱元璋》返工教训）**：用户提供 mp3 时必须**优先复用其音轨**（ffprobe 确认时长 → 转写文本做脚本/CHAP → video_composer --audio 用户.mp3），**禁止忽略用户音频自己 TTS 重生成**——朱元璋案例：007 忽略用户上传的 10min mp3 自写稿 TTS，用户投诉"你给我的视频和音频不是同一本书的内容"。⚠️ 同名文件会覆盖 Hermes 文档缓存（doc_xxx 路径），收到用户音频先 `cp` 备份再处理
- **⚠️ 散文/治愈题材映射（2026-08-15《慢煮生活》案例）**：散文/治愈系 → 晓晓温柔女声（`zh-CN-XiaoxiaoNeural`）+ `--rate=-8%` + 纯人声（`LISTEN_BOOK_NOBGM=1`）+ **warm_home 主题**（暖光居家/壁炉/茶书静物实景）。自动场景检测会把散文误判"励志"（生活/快乐等词命中多）→ 手动 `--theme warm_home`。金句必须用书中真实句子（汪曾祺：人生忽如寄/口味宽一点/生活是很好玩的/家人闲坐灯火可亲）。10min 视频 ≥6 张素材：warm_home 原 3 张 + Pexels `--search "cozy tea book warm" --orientation portrait --download 3` 补茶书静物 3 张

## 交付终版修正（用户 2026-08-10 张居正传确认，默认执行；⚠️ 2026-08-14 金句行为已修订见上）
1. **字幕保留到视频结束（已修订）**：见上方"末句金句不再无条件保留到片尾"铁律——仅当末句距片尾 ≤18s 才持续到结束。
2. **用户可要求纯人声（删 BGM）**：`export LISTEN_BOOK_NOBGM=1` 强制无 BGM（2026-08-11 新增开关，bgm_selector 顶部判断；比 `LISTEN_BOOK_BGM=0` 更彻底——直接跳过混音）。**改 BGM 设置后必须清缓存**：`rm -rf ~/.hermes/cache/bookmadebook/l3 ~/.hermes/cache/bookmadebook/l2`，否则 L3 命中旧版（带 BGM/无 BGM）直接跳过混音。
3. **商务/经济/干货类内容偏好（2026-08-11 用户确认）**：**云健男声 `zh-CN-YunjianNeural` + 纯人声无 BGM + tech_city 场景**（《置身事内》精读视频即此配置：男声 3 分 45 秒、5 张都市夜景、5 金句）。日常精读默认晓晓女声；商务类自动切云健。
4. **男声选择梯度（2026-08-13《董氏父子》用户纠正「男声要更成稳些」）**：云扬 `zh-CN-YunyangNeural` 偏新闻播报感（战争/历史纪录片可用）；**传记/商务/政坛类用云健**（低沉厚重更沉稳）——先用了云扬被否，换云健后通过。**给用户交付前先想清楚题材匹配哪种男声**，别默认云扬；不确定时云健是传记/商务类安全默认

## 陷阱与排障
- **Unsplash 下载截断**：`image file is truncated` → 校验 `stat().st_size > 10000` 且 PIL 能打开，失败重试（`--retry 2`），可降级用已有张数
- **Unsplash 图片内容必须验证**：photo ID 是十六进制串，猜错会下载到完全不相关的内容（耳机/家庭合影/跑车），且 404 静默。**manifest 落地前逐张 `vision_analyze` 确认主题**（2026-08-11 实测 palace 主题 2 张缓存图都是错图）
- **zoompan 卡顿/模糊**：输入先放大 2 倍（2160:3840）再 pan，避免放大不足产生抖动
- **飞书交付视频**：≤20MB 用 `MEDIA:<path>` 直发成功（2026-08-10 实测 11.5MB 竖版 mp4 直发用户可见）；30MB 超限且云盘 upload 报 `file size beyond limit` → 先压缩预览版（`scale=720:1280` + `crf 30` + `aac 96k` ≈ 11MB）再发，高清原版另存。错误码 230055 时走 `lark-cli drive +upload`（相对路径）
- **预览文件名必须带书名**（2026-08-11 教训：用户"你怎么出的视频是张居正的/你再发一遍"两次混淆）：不要用 `v2/v3/xxx_preview.mp4` 这种通用编号——用户飞书里可能残留旧文件，分不清哪条是新的。命名用 `{书名}_{版本描述}.mp4`（如 `置身事内_商务男声版.mp4`），换规格重发时改版本描述（`_商务男声版` → `_云健无BGM版`），文件名本身就是版本标识
- **⚠️ MP4 幽灵 text 轨 = 播放异常（2026-08-16 挪威极夜案例，P0 播放兼容性）**：音频 MP3 自带 ID3 CHAP 章节（long-audio 管线的章节标记）时，`-c copy` mux 进 MP4 会把章节变成一条 `text` 数据轨（ffprobe 显示 `codec_type=data / codec_tag_string=text`），**时长可能超出正片**（实测 640.03s vs 正片 575.8s）→ 部分播放器/平台（飞书/微信/手机相册）判定文件异常无法播放。**症状定位**：`ffprobe -show_entries stream=index,codec_type,duration -of compact out.mp4` 看到第 3 条 data 流且时长 > 视频。**`-map 0:v:0 -map 0:a:0` / `-dn` / `-map -0:d` 都去不掉它**（mux 时被当作元数据轨道自动重建）。**正确修复：合成混音命令必须加 `-map_metadata -1` 丢弃源音频全部元数据**，同时显式 `-map 0:v:0 -map 1:a:0` 只选视频+音频 + `-movflags +faststart`（moov 移到文件头，流式播放/拖动顺畅）：
  ```
  ffmpeg -y -v error -i video.mp4 -i audio.mp3 -map 0:v:0 -map 1:a:0 \
    -map_metadata -1 -c:v copy -c:a aac -b:a 128k \
    -movflags +faststart -shortest out.mp4
  ```
  验证标准：`ffprobe -show_entries stream=index,codec_type -of compact` 只剩 video+audio 两条流；`-show_chapters` 无章节；moov 在文件头（`python3 -c "print(b'moov' in open('out.mp4','rb').read(4096))"` = True）。**此修复已合入 video_composer.py 混音命令**（2026-08-16），新合成不会复发；对存量视频用上述命令重封装（`-c copy` 秒级）即可修复，无需重新渲染。注意：`-map_metadata -1` 会顺带丢弃封面/其他有用元数据，如需要保留封面另行 `-attach`
- **抽帧验证金句要避开窗口边缘**（2026-08-11 实测）：金句只在 30%-95% 音频段显示，`quote_ts = 0.3*dur + i*(0.65*dur/n)`。抽帧若落在窗口起点（如 120/228≈53% 之前）会看到"无金句"——先算准某句金句的 ts 窗口再抽帧，或抽 80%+ 时长处必见末句金句（末句保留到片尾）
- **⚠️ 抽帧 fast-seek 坑（2026-08-23 山茶文具店误判教训）**：`ffmpeg -ss N -i file`（-ss 在 -i 前）是 **fast seek**——定位到最近关键帧，可偏差数秒；金句字卡只显示 12s 窗口（fade in ts+0.5 → te=ts+12），抽帧时机不对会**误判"金句没渲染"**（本轮抽 4 个时间点全落空，以为字卡丢失，实际是 seek 偏差）。正确做法：①先算金句实际显示时间——`python3 -c "import sys;sys.path.insert(0,'scripts');import video_composer as vc;print(vc._quote_times(...))"`（或 dry-run 后按稿中位置比例×总时长估算）；金句时间**不等于章节起始时间**（山茶文具店 4 句金句在 22s/278s/436s/494s，而章节在 0/35/104/226s——按章节抽帧必扑空）②在窗口**中段**抽帧（如 ts+4s）③更稳妥用精确 seek：`-ss` 放 `-i` **后面**（`ffmpeg -i file -ss N`）④抽帧结果"全是同一画面"时先用 md5 对比素材文件确认是否真重复，再怀疑渲染问题（warm_home 素材蜡烛占比高，短视频易显重复但实际每 0.9s 换图）
- **⚠️ 换配音必须全量重渲染，禁止只替换音轨（2026-08-23 山茶文具店换 husky_tender 案例）**：用户要求"把配音换成 X 声音"时，**不能** `ffmpeg -i video -i new.mp3 -map 0:v -map 1:a` 直接换音轨——video_composer 的金句字卡/章节标签时间轴**基于音频 CHAP 时长规划**（`_quote_times` 按稿中位置比例映射到音频时间轴），换音轨后新音频节奏不同 → 字卡与配音错位。正确路径：①streaming_pipeline.py 用新 voice ID 重新合成（`--voice qwen-tts-vd-husky_tender-voice-...`，husky_tender 语速比晓晓慢，10 分钟稿约 +10s 达 546s）②video_composer.py --audio 新 MP3 重新合成视频（字卡自动重排）③压缩 720p + 封面 + 飞书发送。判断依据：原音频无长静音分段（连续叙述）必须全量重渲染；交付时用 ffprobe 对比新视频音轨时长 ≈ 新音频源时长（546.35 vs 546.38）证明换声生效
- 视频 60s demo 时 `-shortest` 会截断，用 `-t 音频时长` 控制
- **长视频合成耗时预期（2026-08-13《二战战史》10min 实测）**：`--fast` 模式下 10 分钟视频仍需 **15-18 分钟**（zoompan 在 2160×3840 内部尺寸逐帧计算约 18000 帧），5 分钟视频约 10 分钟。用户催进度时要提前说明"合成约 X 分钟"；中间文件最后才 flush（文件大小不变≠卡死，看 `ps aux | grep [f]fmpeg` 的 CPU% 是否满载）；`video_composer.py` 的 subprocess timeout 已放宽到 1200s（`--fast` = preset faster + crf 26，画质略降但速度数倍，预览/长片用）
- **edge-tts 网络挂起检测与重试（2026-08-13 实测）**：streaming_pipeline 长时间（>10min）无输出时，`ps` 看进程状态——若 `epoll_wait`/sleeping + 0% CPU + `ss -tnp` 无活跃 TCP 连接 = edge-tts 请求挂起（WSL 网络抖动）。**处理**：kill 进程 → `timeout 15 python -c "import edge_tts,asyncio; ..."` 探活（通→重跑，通常 40s 内完成；不通→等网络）→ 重跑加 `timeout 900` 前缀防再挂。输出被 `| tail` 缓冲看不到中间进度时，用 `ls -la` 目标文件 + `ps` 判断实际进度

## 推广引流注意（GitHub 仓库已改名 bookmadebook，2026-08-08）
- 仓库原名 "listen-book" 时**按仓库名搜索会被淹没**（实测同名 109 个，0星排最后）——**改名流程**：先 `gh api search/repositories?q=<候选>+in:name` 验证重名数，选 **0 重名**候选（"bookmadebook" 0 重名）；`gh api -X PATCH repos/<owner>/<repo> -f name=<新名>` 改名（旧链接自动重定向）；本地 `git remote set-url origin` + 批量替换 README/SKILL/listen.py 中的旧名（**注意保留 `LISTEN_BOOK_*` 环境变量名，那是兼容性保留，不要替换**）；改名后 git push 可能因网络 TLS 失败 → 用 gh api PUT 逐文件推送（新文件 POST 不带 sha、已有文件 PUT 带 sha）；三端同步（GitHub/WSL 技能目录/008 Windows 技能目录）+ md5sum 验证
- 引流文案给**完整链接**（github.com/QINGcha7911/bookmadebook）或引导**搜用户名**，不要让用户搜仓库名
- **推广对象是技能/平台本身**（"点书→自动出精读音频/视频"），不是某一本书的内容——书只是能力示例（用户 2026-08-07 两次纠正：先否掉自编励志鸡汤"其他技能也能做"，再明确"要推广的是这个技能，类似平台一样"）
- **示例内容必须来自真实书籍精读**（公版书优先：《老人与海》/《小王子》），不要自编"努力才能成功"类鸡汤——差异化来自真实书内容，不是画面技巧

## 参考
- `references/xiaohongshu-60s-and-promotion.md` — 小红书 60 秒版实测规格（~230 字/偏差>15% 拦截）+ 2026 算法 CES/流量池/搜索 + 薯条四阶段推广（用户暂不用，备查）
- `references/long-video-45min-workflow.md` — 45分钟级超长视频完整工作流（2026-08-13《冬牧场》）：delegate_task 并行写稿→合并校验清单（金句去重/行内金句/场景对齐/字数）→磁性女声配方（晓晓+`--pitch=-15Hz`）→合成超时 7200s
- `references/video-upgrade-2026-08.md` — 2026-08-11 视频合成器升级实录：scene_selector/scene_library/text_layers 三模块设计决策、6 步实施路线、全部踩坑记录
- `references/github-repo-rename.md` — GitHub 仓库改名完整流程（重名验证→PATCH→本地同步→gh api推送→三端同步→踩坑）
- `references/ffmpeg-video-recipes.md` — 完整可复制的 6 图 xfade + 金句 drawtext 命令
- 音频侧：long-audio-tts-pipeline（TTS/BGM）；讲稿写作：audiobook-script-authoring
