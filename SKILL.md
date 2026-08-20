---
name: bookmadebook
version: 2.3.2
description: |-
  AI 书籍精读音频生成 — 全年龄段（3岁+），多场景、多声音、多深度。
  用户一句话 → 推荐书籍 → 生成精读脚本 → TTS转音频 → 交付 MP3 + 笔记。
  触发词：解读、精读、推荐书、听书、讲书、有声书、朗读、读书、语音、听、讲故事、书评、拆书。  
requires: python>=3.10

---
# bookmadebook — AI 执行指南

> 本文档是给 AI 的执行指南，不是用户手册。拿到任务后按以下流程走。

---

## 〇、视频模式工作流（2026-08-18 用户固化，v2.3.0）

> 精读以**音频为主、视频为辅**。生成精读视频时（默认开启）：
> 1. **60 秒开篇视频**：钩子开场（悬念/金句）+ 书名 + 核心亮点，节奏快、竖版 1080×1920
> 2. **接着精读正文**：正文画面（字卡/图片/可灵场景）随讲书稿章节推进
> 3. 画面策略（省成本）：核心场景用可灵（**3 段内，5 秒/段**），其余用金句字卡/图片 + 本地合成
> 4. 口播本地 TTS（免费），背景音乐可选，金句必须以字卡呈现
> 5. 配套：小红书文案 + 海报（60 秒版为引流钩子，评论区引导听完整精读音频）
>
> **可灵配置**：KLING_API_KEY + KLING_API_BASE_URL 在 `/mnt/d/AI软件/GitHub/OpenMontage/.env`（008 已配，58 字符 key）。可灵 CLI 技能：`kling-cli`（/root/.hermes/skills/kling-cli/）。
> **分工**：008 维护 SKILL.md（已 push commit 5d3d613）；007 同步本地技能 + 生产 cron 模板。
> **正文画面策略（008 已确认，2026-08-18）**：正文 = **实景素材合成（默认，assets/scenes Ken Burns）** + **可灵核心场景（可选 ≤3 段，5 秒/段）** + **金句字卡（必配）**。60 秒开篇用可灵为主。
> **v2.3.1 免费版默认（2026-08-18 用户定案）**：开篇+正文**全部实景素材 Ken Burns**+金句字卡+本地口播=**0 元**；**可灵仅爆款/重点书用（≤2 段，20-40 元，非必需）**。cron prompt 已更新（免费版默认，可灵失败自动退回纯实景）。
> **⚠️ 开篇 60s 画面风格自适应（v2.3.1 补充，2026-08-18 用户定案）**：按讲书稿内容类型判定——**历史传记/战争类=黑白（灰度化）**，**惬意抒情/治愈类=彩色**。判定=讲书稿历史关键词检测（朝代/年号/皇帝/战役/战争/列传/史/起义/王朝等），出现即历史类→开篇加灰度化（hue=s=0 或 format=gray）；无=治愈类→彩色。正文画面风格与开篇一致。
> **v2.3.2 晚班 45 分钟静态画面模式（2026-08-20 用户定案）**：晚班 18:15 精读视频 10 分钟→**45 分钟**（讲书稿 ~10000-11500 字）；前 60 秒吸引方式不变（钩子+金句字卡+口播）；**正文=1-2 张固定静态图**（最多轻微 crop 平移运镜，禁多素材频繁切换），脚本 `/tmp/compose_static_body.py`（金句字卡自动叠加、--gray 黑白、双图 xfade）。早班 6:15 保持 10 分钟不变。压缩：45 分钟静态画面 crf 40-44 <20MB。
> **⚠️ 开篇画面铁律（2026-08-18 用户否掉 v1 教训）**：①**禁止循环拼接同一段可灵视频**（v1 用 2 段×4 循环=画面重复，用户直接否掉）；②必须生成 **≥3 段不同 prompt 的可灵画面**（每段 10s，不同场景），每段只出现一次；③可灵段间**穿插实景素材** Ken Burns 做呼吸感；④xfade=1s 过渡；⑤**金句字卡首句必须 ≤60s 出现**（video_composer `_quote_times` 已修：`quotes[:6]` + 首句封顶 `audio_dur*0.06+15`）；⑥可灵生成用 `/tmp/gen_kling_video.py`（OpenMontage KlingClient，kling-v3，需先 python 加载 .env——CRLF 行尾不能 source）；⑦开篇拼接参考 `/tmp/rebuild_opening_v2.py`；**⑧可灵余额不足降级（2026-08-18 008 实测 code 1102）**：可灵失败/余额不足时自动降级为「纯实景开篇」（assets/scenes 素材 Ken Burns 交替 + xfade + 首句金句字卡照常），禁止死等或报错，不影响正文与交付。

---

## 一、执行流程总览

Step 1: 解析用户意图 → 确定参数（书/年龄/场景/深度/声音）
Step 2: 获取书籍信息 → book_info.py（公开信息）或 book_fetcher.py（全文）
Step 3: 生成精读脚本 → AI 生成（按年龄段选择 prompts/ 模板）
Step 4: TTS 转音频 → streaming_pipeline.py（分段生成→拼接→章节标记）
Step 5: 交付用户 → MP3 文件 + Markdown 文稿

---

## 二、Step 1 — 解析用户意图

从用户输入中提取以下参数，缺失的用默认值：

| 参数 | 配置键 | 默认值 | 如何从用户语言推断 |
|------|--------|--------|-------------------|
| 书名/主题 | book_title | 必填 | 直接提到的书名，或要求推荐某主题 |
| 年龄段 | age_group | adult | "6岁"→primary_lower, "初中"→middle_school, "睡前"→bedtime场景 |
| 场景 | scene | commute | "跑步"→running, "睡前"→bedtime, "和孩子"→parent_child |
| 深度 | depth | standard | "速览"→quick, "深度"→deep, "完整"→full |
| 声音 | voice | 按年龄自动选 | "男声"→yunxi, "温柔"→xiaoxiao |
| 语速 | speed | 按年龄自动设 | 可被 age_group 覆盖 |
| 时长(分钟) | duration | auto | 用户说了具体分钟数则设置 |
| 交付模式 | delivery_mode | progressive | "完整"→full, 默认→progressive |
| 输出类型 | output_format | audio | "只要文稿"→script, "都要"→both |
年龄段口语映射表（完整映射见 config.yaml）：
- 0-3岁/toddler, 3-6岁/preschool, 6-9岁/primary_lower, 9-12岁/primary_upper
- 12-15岁/middle_school, 15-18岁/high_school, 18+/adult

场景口语映射表：
- 通勤/地铁/开车→commute, 跑步/运动→running, 睡前/晚安→bedtime
- 亲子/陪孩子→parent_child, 学习/研究→deep_learning, 午休→lunch_break

---

## 三、Step 2 — 获取书籍信息

### 3.1 确定获取策略

用户提供了文件/文本？→ 直接用用户提供内容（最优先）
否：判断是否公版书 → 公版书：用 book_fetcher.py 获取全文（古登堡计划）→ 现代书：用 book_info.py 获取公开信息（豆瓣+维基）

### 3.2 调用脚本

# 现代版权书：获取公开信息（简介+评分+金句+评价）
python scripts/book_info.py "书名"

# 公版书：获取完整文本
python scripts/book_fetcher.py "书名"

# 用户提供文件
python scripts/book_info.py --file /path/to/book.txt

# 如果用户说"推荐书"（没有指定具体书）
→ 先用 LLM 按 age_group 的 recommendation_categories 推荐 3 本书
→ 用户选择后，再走上述获取流程

### 3.3 合规原则（版权红线）
- 精读是"种草引流"，不是盗版替代
- 现代书只用公开信息（豆瓣简介+维基百科+公开书评）
- 公版书可获取全文（作者逝世超50年）
- 音频结尾附购书链接（现代书）

**版权红线（务必遵守）：**

| 红线 | 说明 | 风险等级 |
|------|------|---------|
| 1. 不朗读全文 | 现代版权书只能精读（解读+片段引用+金句），**禁止逐字朗读整本书** | 🔴 高 |
| 2. 不抓盗版文本 | 书内容禁止来自盗版渠道（安娜的档案/微信读书抓取等） | 🔴 高 |
| 3. 商用需谨慎 | 个人自用安全；商用（付费/带货）时"合理使用"标准更严 | 🟡 中 |
| 4. 公版书最安全 | 作者逝世超50年（古登堡书目）→ 可全文朗读、可商用 | 🟢 安全 |
| 5. 标注AI生成 | 音频开头/结尾标注"本音频由AI生成，内容为解读引用，版权归原作者" | 🟢 必做 |

**安全边界速查：**
- ✅ 《老人与海》《小王子》《西游记》原著（公版）→ 放心做
- ⚠️ 《活着》《太白金星有点烦》等现代书 → 只精读，不逐字朗读，公开传播前注意
- ❌ 任何书从盗版源获取全文 → 绝对禁止

---

## 四、Step 3 — 生成精读脚本

### 4.1 选择提示词模板

| age_group | 模板路径 | 特殊处理 |
|-----------|---------|---------|
| toddler | prompts/children/toddler_mode.txt | 无观点结构，纯故事+互动 |
| preschool | prompts/children/preschool_mode.txt | 简单情节+提问 |
| primary_lower | prompts/children/primary_lower_mode.txt | 故事+知识点 |
| primary_upper | prompts/children/primary_upper_mode.txt | 多观点+案例 |
| middle_school | prompts/teen/middle_school_mode.txt | 批判性思考 |
| high_school | prompts/teen/high_school_mode.txt | 深度分析 |
| adult | prompts/standard_mode.txt | 完整精读结构 |

### 4.2 内容质量铁律（用户亲定，必须遵守）

**① 内容量诚实告知**
- 生成前用 `--target-minutes` 校验：实测语速 × 目标分钟 = 需要字数
- **内容不足时直接报错停止**，明确告知用户：
  - 当前稿子约 X 分钟，距目标还差 X 字
  - 选项：①补充更多书中真实情节 ②缩短目标时长 ③换书
- **禁止默默生成注水版**（用重复内容/空话凑时长）

**② 零重复规则**
- 金句只出现一次（正文讲过就不再进金句集锦）
- 同一情节/场景全稿只讲一次，禁止"换个说法再讲一遍"
- 每个段落必须有信息增量（新情节/新人物/新细节）
- 写完自检：发现"前面说过/正如刚才提到"或意思重复的内容，删掉
- 宁短勿滥：内容不够就诚实写短，绝不注水

**③ 讲书结构（书籍90%+解读10%）**
- 90% 篇幅讲书里的内容（情节/人物/故事/细节/对话）
- ≤10% 解读（段落结尾1-2句点题，全书结尾总结）
- 每段开头先亮主旨（TED式分段主旨），不平铺直叙

**④ 抑扬顿挫与本地化**
- 情绪标注14种（开心/悲伤/紧张/温柔/坚定/疑惑/神秘/爆发/轻声等），每段至少2-3个情绪
- 写作语言符合目标国家的表达习惯（日文ねよ/敬语，英文口语化，中文语气词）

### 4.2.1 讲书稿结构规范（时间线框架，2026-08-08用户确认）

**核心原则：严格时间线叙事，零重叠，同一主题只出现一次。** 禁止用"补充段落"乱序堆砌（《苏东坡传》v1 教训：17个补充段落乱序插入导致架构混乱/内容重叠/凑数感，用户否掉）。

**① 章节框架（传记/人物类通用）**
- 开场：**悬念钩子**（3个场景/画面切入，不直接报人名）→ 点出主角 → 预告今天的故事
- 按时间线分章：少年/入仕/低谷/转折/高峰/再贬/终局
- 每章：先亮主旨 → 讲2-4个真实细节（具体到场景/对话/数字）→ 1-2句解读点题
- 结尾：总结+升华+金句收束，与听者产生共鸣

**② 内容组织规则**
- 同一主题（如杭州治理、美食、情感）**只在一个章节出现一次**，禁止拆散到多处
- 补充内容必须**并入对应时间线章节**，禁止"## 补充"独立段落
- 章节顺序=时间顺序，不跳转不回看
- 每章内部按"场景-细节-解读"推进，不平行罗列

**③ TED情绪强化**
- 情绪标注**多样化**：悬念/反差/震撼/感叹/紧张/愤怒/低沉/激昂/温暖…（不只"平静/温暖"）
- 每章至少1个【停顿0.5s】或【停顿1s】（节奏对比）
- 关键金句前加停顿+金句重读
- 开场必须有钩子（悬念句/反差句/场景句），禁止平铺直叙"今天讲XXX"

**④ 金句管理**
- 每章0-2个金句，全稿4-6个（不贪多）
- 金句位置：正文首次出现 + 结尾呼应（语境不同不算重复）
- 金句必须是书中原句或凝练提炼，禁止编造

### 4.4 视频合成（讲书音频 → 实景动态视频）

**设计原则（2026-08-07 用户确认，2026-08-11 升级）**：
- 实景写实照片（Unsplash 免费图库），不用 AI 生图
- 同主题连贯画面（如沙漠星空系列），避免场景跳跃
- 交叉溶解过渡（xfade 1.5s），画面平滑流动
- 文字只保留金句 + 书名，淡入淡出
- Ken Burns 缓慢缩放（zoompan），动态不呆板
- **文字层用 PIL 预渲染 PNG + overlay**（替代 drawtext，规避中文转义/断行/描边坑）
- **字体用思源黑体/宋体（Noto CJK，OFL 商用合规）**，不用微软雅黑（商用侵权风险）
- **画面 scale 必须 cover 模式**（`force_original_aspect_ratio=increase` + `crop`），防横图拉伸变形（2026-08-11 用户反馈"字体压太扁"根因）

**用法**：
```bash
python scripts/video_composer.py --script 讲书稿.txt --audio 音频.mp3 --book 书名 --output out.mp4
```
- `--theme auto`（默认）按内容自动选主题；也可手动指定（desert/forest/ocean/palace/sunrise/starry/rain/library/warm_home/snow/tech_city/temple）
- `--scene-from auto|script|manual` 场景来源（标记/自动/手动）
- `--dry-run` 只输出场景规划不合成
- 自动提取【金句】标记 → 视频中段淡入淡出显示
- 输出 1080×1920 竖版（小红书/抖音适配）

**场景自动选择（2026-08-11 新增）**：
- 优先级：`--theme 手动 > 讲书稿【场景：XX】标记 > 自动检测（加权关键词统计）> 兜底 desert`
- `scene_selector.py`：复用 streaming_pipeline 的 CONTENT_VOICES，**加权统计**各类关键词命中数取最高（不是首命中——张居正传"汇报"误判职场教训）
- `scene_library.py`：本地素材库（assets/scenes/<theme>/ + ~/.cache/bookmadebook/scenes/），降级链 本地→缓存→下载→desert 兜底
- 多章节：`【场景：palace】` 标记可切段换主题，≤3 场景/片
- 素材清单：`assets/scenes/manifest.json`（11 主题 Unsplash URL，**已人工目检**：2026-08-11 清理了耳机/合影/手机等错配图）
- **注意**：manifest 中未逐一验证的 URL 内容可能不符（盲猜 ID 教训），新主题素材需人工目检
- **scene_fetcher.py**（2026-08-11 新增）：Pexels API 搜索下载素材（`--theme palace --download 3`），需 `PEXELS_API_KEY` 环境变量；API 返回真实图片+描述，杜绝盲猜
- **强制无 BGM**：`LISTEN_BOOK_NOBGM=1` 环境变量（2026-08-11 用户要求商务/干货内容纯人声，配合云健男声）
- **战争/军事题材**：关键词自动选 ww2 主题（士兵剪影图，2026-08-13）；`--rate=-10%` 注意用等号（`-10%` 会被 argparse 误解析）
- **⚠️ 场景地域匹配铁律（2026-08-17 教训）**：palace 场景素材是**故宫/长城（中国建筑）**，只可用于中国题材（李鸿章/王阳明/万历/曾国藩等）；**欧洲/外国人物传记（拿破仑/梵高/歌德等）严禁用 palace**——拿破仑传曾误配故宫画面被用户抓包。选场景时先想"人物是哪个国家/地域"：欧洲战争人物→ww2（战争剪影）或 starry；欧洲艺术人物→starry/library；中国帝王将相→palace；自然题材→desert/forest/ocean/snow/pasture。**选题池 tsv 每本书的场景字段必须人工核对地域匹配后再入库**
- **船王/航运题材**：ship 主题（集装箱货轮图，2026-08-13）；**香港/政坛题材**：hongkong 主题（香港天际线图）；用户偏好：商务/传记男声用云健（zh-CN-YunjianNeural）比云扬更沉稳
- **Pexels 城市搜索坑**：搜 "hong kong skyline" 会混入里斯本/迪拜等相似城市港图，**下载后必须 vision 目检地标**（IFC/中银/摩天轮）再入库（2026-08-13 里斯本混入教训）
- **牧场/游牧题材**：pasture 主题（雪原羊群图，2026-08-13）；**磁性女声**：晓晓 + `--pitch=-15Hz`（低沉磁性，2026-08-13 新增 CLI 参数，注意用等号）
- **超长视频（45分钟）**：video_composer 主合成 timeout 已放宽到 7200s（2小时）；45 分钟≈13500字讲书稿，可 delegate_task 并行分章节写稿再合并
- **渲染提速（2026-08-13）**：zoompan 内部渲染分辨率从 2160×3840 降到 1080×1920（原来先放大 4K 再缩回 1080p = 白算 3/4 像素），45 分钟视频合成从 80-90 分钟 → 25-30 分钟，画质无差别
- **交付分层（2026-08-13 新增 deliver.py，仅作可选工具）**：用户想要多长就生成多长，**时长不做任何限制**。deliver.py 只是辅助工具（按时长压缩/分层），是否使用由用户决定——用户要完整视频就给完整视频，要音频就给音频，要 5 分钟精华就做 5 分钟精华
- **小红书精华版（2026-08-13）**：小红书平台限制为参考信息（单条视频限 15 分钟、普通号最佳 5 分钟、MP4/720p+/竖版9:16），**不是技能限制**——用户要发小红书时可按此做精华版，用户要完整版就做完整版，一切以用户需求为准
- **场景标记铁律（2026-08-13 修复）**：`【场景：XX】`必须放在章节标题**正上方**；每章一个标记；相邻章节可用同主题（解析器已修：只合并 <50 字符内重复标记，不再吞段）；音频章节数与标记数不一致时按字数比例分配
- **ffprobe 章节排序坑（2026-08-14 实测）**：ffprobe 读 MP3 ID3 CHAP 按**字符串**排序（`"560"<"57"`，因 `'6'<'7'`），10 分钟稿章节被排成 `0→560→57→193...`，导致场景时间轴出现负区间 → 合成报 `Numerical result out of range`。**scene_selector.read_audio_chapters 已加 `chapters.sort(key=start)` 按数字重排**——改稿后必须 dry-run 验证时间轴（逐段 start<end 递增）再合成

**音频/视频自适应**（2026-08-07）：
- `python listen.py "《小王子》10分钟"` → 默认音频
- `python listen.py "《小王子》10分钟视频"` / "做个视频" / "短片" → 自动识别为视频
- 视频模式：先生成音频（harness）→ 再合成实景视频（video_composer）
- 输出类型可强制指定：`--output-type audio|video`

**视频验收要点**（用户偏好）：
- 画面必须"活的"（星星闪/粒子动/Ken Burns），不能静态
- 场景切换要连贯（同主题+交叉溶解），不要硬切跳跃
- 金句是唯一文字，位置/时长要配音频节奏

### 4.3 Harness 执行框架（质量门 + 输出验证门）

bookmadebook 采用 **Harness 控制循环**（不是"给AI知识后自由发挥"），生成全程强制校验：

```
讲书稿 → [quality_gate 质量门] → streaming_pipeline 生成 → [output_verify 验证门] → 交付
             ❌不过→停止(exit 2)        ↑                          ❌不过→禁止交付(exit 3)
```

**质量门 `scripts/quality_gate.py`（生成前）**：
- 字数校验：实测语速 × 目标时长，不足报错（诚实告知，禁止注水）
- 重复段落检测：n-gram 相似度>75% 拦截
- 金句去重：同一金句出现>1次 拦截
- markdown 残留：正文行内 # 号/符号簇 警告
- 版权检查：现代版权书无解读特征 警告

**输出验证门 `scripts/output_verify.py`（生成后）**：
- 开头标题朗读检测：波形相关性 vs 标题样本，>0.5 拦截（防止"井号"问题复发）
- 时长偏差：>10% 拦截
- 音频完整性：可解码、时长>0

**CLI 用法**：`--target-minutes` 触发质量门；生成后自动跑输出验证门。
退出码：0=通过, 2=质量门拦截, 3=输出验证拦截。

---

**深度等级覆盖**：depth = quick/standard/deep/full，但 age_group 会限制可选深度。
- toddler/preschool 只支持 standard
- primary_lower/upper 支持 quick/standard/deep
- middle_school/high_school/adult 支持全部

### 4.2 内容安全过滤

在生成脚本后、送入 TTS 前，必须过内容安全过滤：

from scripts.content_filter import ContentFilter
mode = "kids" if age_group != "adult" else "adult"
cf = ContentFilter(mode)
result = cf.check(script_text)

if not result["safe"]:
    # 替换不适内容为安全表述，重新生成该段
elif "warnings" in result:
    # 提醒家长陪听

### 4.3 脚本输出格式

生成 JSON 格式的结构化脚本，segments 的 text 拼接为完整文本送入 TTS。

---

## 五、Step 4 — TTS 转音频

### 5.1 调用流水线

python scripts/streaming_pipeline.py -f script.txt --voice {voice} --rate {rate}

### 5.2 声音选择逻辑

| age_group | 声音 | 语速 |
|-----------|------|------|
| toddler | zh-CN-XiaoshuangNeural | -20% |
| preschool | zh-CN-XiaoxiaoNeural | -15% |
| primary_lower | zh-CN-XiaoxiaoNeural | -10% |
| primary_upper | zh-CN-YunxiNeural | -5% |
| middle_school | zh-CN-YunjianNeural | +0% |
| high_school | zh-CN-YunyangNeural | +0% |
| adult | zh-CN-XiaoxiaoNeural | +0% |
### 5.3 流水线内部处理（自动）

1. smart_split_text() → 按自然断点分3000字以内段
2. 逐段调 edge-tts 生成 MP3
3. 三级缓存检查（L1脚本/L2片段/L3成品）
4. ffmpeg 拼接所有段
5. add_chapter_markers() → 写入 ID3v2 章节标记
6. 输出最终 MP3

---

## 六、Step 5 — 交付用户

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| MP3 音频 | ~/bookmadebook/{书名}_{timestamp}.mp3 | 主交付物 |
| Markdown 文稿 | 同目录 .md 后缀 | 用 templates/script_doc.md.j2 渲染 |
| Obsidian 笔记 | Obsidian vault（如配置） | 自动存入 |
交付模式：
- progressive（默认）：30秒内出第1章音频，后台继续生成后续章节
- full：等全部生成完一次性交付

---

## 七、关键脚本说明

| 脚本 | 功能 | 调用时机 |
|------|------|---------|
| scripts/book_info.py | 获取书籍公开信息（豆瓣+维基） | Step 2，现代书 |
| scripts/book_fetcher.py | 获取书籍全文（多源降级） | Step 2，公版书 |
| scripts/content_filter.py | 内容安全过滤 | Step 3 生成脚本后 |
| scripts/streaming_pipeline.py | TTS 分段生成→拼接→章节标记 | Step 4 |
| scripts/cache_manager.py | 三级缓存（被 pipeline 自动调用） | 内部依赖 |
脚本间依赖关系：
book_info.py → AI 生成精读脚本（用 prompts/ 模板）→ content_filter.py 检查 → streaming_pipeline.py → cache_manager.py → 输出 MP3 + 文稿

---

## 八、错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 书籍获取失败 | 告知用户，建议上传正版电子书或粘贴文本 |
| 内容安全拦截 | 替换不适内容，提示用户已自动调整 |
| TTS 连接失败 | 重试2次，仍失败则提示检查网络 |
| 音频拼接失败 | 检查 ffmpeg 安装，提示用户 |
| 缓存命中 | 跳过生成，直接使用缓存文件 |

---

## 九、配置文件

详见 config.yaml（带【常用】/【高级】标记），核心关注：
- age_group.default — 默认年龄段
- scene.default — 默认场景
- delivery_mode.mode — 交付模式
- tts.default_engine — TTS 引擎
- content_safety.mode — 内容安全模式

详细年龄段参数、场景参数见 references/EXECUTION_GUIDE.md。

## 十、文件结构

bookmadebook/
├── SKILL.md                    ← 本文件（AI执行指南）
├── config.yaml                 ← 全局配置（【常用】+【高级】标记）
├── references/EXECUTION_GUIDE.md  ← 详细执行参考
├── prompts/                    ← 精读脚```
## 九、配置文件详见 config.yaml（带【常用】/【高级】标记），核心关注：- age_group.default — 默认年龄段- scene.default — 默认场景- delivery_mode.mode — 交付模式- tts.default_engine — TTS 引擎- content_safety.mode — 内容安全模式详细年龄段参数、场景参数见 references/EXECUTION_GUIDE.md。## 十、文件结构bookmadebook/├── SKILL.md                    ← 本文件（AI执行指南）├── config.yaml                 ← 全局配置（【常用】+【高级】标记）├── references/EXECUTION_GUIDE.md  ← 详细执行参考├── prompts/                    ← 精读脚本生成模板（按年龄段+深度）├── templates/                  ← 输出文稿模板（Jinja2）└── scripts/                    ← 工具脚本（不要修改）    ├── book_info.py            ← 书籍公开信息获取    ├── book_fetcher.py         ← 书籍全文获取（公版书）    ├── content_filter.py       ← 内容安全过滤    ├── streaming_pipeline.py   ← TTS分段→拼接→章节标记    └── cache_manager.py        ← 三级缓存（被pipeline自动调用）
---

> **AIGC 合规声明**：本技能生成的内容由 AI 生成，请遵循相关法律法规及《人工智能生成合成内容标识办法》使用与传播。生成音频请在开头/结尾标注"本音频由AI生成"。

