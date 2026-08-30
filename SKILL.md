---
name: bookmadebook
version: 2.5.0
description: |-
  AI 书籍精读生产流水线 — 全年龄段（3岁+），多场景、多声音、多深度。
  每日自动生成 10 分钟精读音频 + 1080×1920 竖版视频（60s 开篇 + 实景正文），
  配套小红书文案与海报；支持选题池（plan.tsv）与飞书 cron 无人值守：
  选题 → 讲书稿 → TTS → 素材 → 合成 → 质量门 → 小红书文案 → 飞书交付。
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
> **⚠️ 压缩命令必须带 `-movflags +faststart`（2026-08-21 早班/晚班两次踩坑）**：ffmpeg 压缩/拼接后 moov atom 默认在文件末尾，lark-cli 上传飞书会报「moov atom not found」且 ffprobe 误判损坏——agent 会陷入 65s 循环压缩但每次都"损坏"。任何 ffmpeg 输出 MP4 一律加 `-movflags +faststart`；压缩后必须 `ffprobe -v error -show_entries format=duration out.mp4` 验证可读再上传。混编码 concat（h264+hevc）禁止 `-c copy`（会损坏），必须 `-filter_complex concat` 统一重编码。
> **⚠️ 开篇 60s 画面切换铁律（2026-08-21 用户反馈教训）**：①**禁止单主题素材**——全部 warm_home 家居素材色调相似，切换视觉不可见，用户反馈"没有画面切换"；开篇必须**≥2 个主题交替穿插**（如 warm_home↔forest），每段 4-6s，视觉差异明显。②**金句字卡必须全程显示**——禁止 20-32s 一闪而过（用户反馈"没有金句文字"）；金句 5s 淡入→52s 淡出（`alpha='if(lt(t,5),t/5,if(lt(t,52),1,if(lt(t,56),(56-t)/4,0)))'`），fontsize ≥60 白字黑边。③开篇实现以 video_composer.py 开篇合成为准（旧参考脚本曾存 /tmp，已归档不可依赖）。
> **⚠️ 素材禁真人铁律（2026-08-21 用户反馈教训）**：视频画面**禁止出现真人/人物素材**（用户明确要求"把视频中的真人画面替换成景色画面"）。选素材时逐张目检：园林/山水/竹林/古建/静物（无人物）才可用；汉服人物、人像、有人物的场景一律弃用。**同时检查远景**：山水/园林素材**远景不得有现代城市/高楼/公路/电线**（landscape_02 山脚城市被剔除教训）——Pexels 下载的高清图远景常带城市，仅看缩略图会漏，须放大远景确认。素材下载后必须拼图目检（PIL 拼 4×3 缩略图 + vision 逐张确认无真人/现代元素）再入库。gufeng 库现状：园林 6 + 山水 5 + 竹林 3 + 古籍 1（零真人零城市）。
> **⚠️ 像素格式铁律（2026-08-21 打开出错教训）**：任何 ffmpeg 输出 MP4 必须显式 `-pix_fmt yuv420p`——否则 x264 默认可能输出 yuvj444p（High 4:4:4 Predictive），飞书/手机/多数播放器无法解码（用户反馈"打开会出错"）。手写开篇脚本（build_fusheng_opening.py）曾漏此项；video_composer.py 正常（自带 yuv420p）。**交付前必须验证**：`ffprobe -v error -select_streams v -show_entries stream=pix_fmt -of csv=p=0 out.mp4` 必须返回 `yuv420p`，非 yuv420p 即播放器不兼容。拼接时混编码用 filter_complex 重编码时同样要带 `-pix_fmt yuv420p`。
> **⚠️ drawtext 换行铁律（2026-08-21 乱码教训）**：ffmpeg drawtext 的换行必须用**真实换行符**（Python 源码里写 `\n` 单反斜杠），**禁止写 `\\n` 字面量**（双反斜杠=反斜杠+n 两个字符，drawtext 不解释转义，会把 `n` 渲染成文字——《浮生六记》开篇金句「若为儿择妇n非淑姊不娶」乱码根因）。Agent 写脚本时易犯此错；**开篇/字卡渲染后必须抽帧 vision 验证文字无乱码再交付**（`ffmpeg -ss 25 -i out.mp4 -frames:v 1 check.jpg`）。
> **v2.3.3 晚班恢复 10 分钟（2026-08-21 用户定案）**：晚班 18:15 与早班 6:15 同为**10 分钟精读视频**（讲书稿 ~2600-2800 字），正文=实景素材 Ken Burns 动态（video_composer.py --fast），开篇 60s 钩子不变；**不再用 45 分钟静态画面模式**（v2.3.2 已废弃，compose_static_body.py 不用于日常线）。10 分钟视频压缩用 H.264 crf36+faster（约 19MB），带 `-movflags +faststart`。
> **45 分钟长视频压缩铁律（仅未来长视频备查，日常线禁用）**：若未来恢复 38-45 分钟视频且需压 30MB 内，才用 **x265 + 720p + 目标码率**（`-c:v libx265 -preset medium -b:v 75k -maxrate 95k -bufsize 190k -c:a aac -b:a 40k -movflags +faststart`，~28-29MB；H.264 压 45 分钟必糊）；**日常线 10 分钟一律 H.264 1080×1920，禁止套用此命令**（2026-08-26《雅舍小品》720p 模糊教训）。
> **⚠️⚠️ 10 分钟视频压缩红线（2026-08-26 用户反馈"画面模糊"根因）**：**禁止 scale 720p！禁止 x265！** 10 分钟视频压缩必须保持 **1080×1920**，用 `-c:v libx264 -crf 36 -preset faster -c:a aac -b:a 96k -pix_fmt yuv420p -movflags +faststart`（约 19MB）。压缩后必须验证 `ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0 out.mp4` 返回 `1080,1920`——**agent 曾误套 45 分钟 x265+720p 命令导致交付 720p@101kbps 模糊视频**（2026-08-26《雅舍小品》）。45 分钟铁律仅供长视频，日常线一律 1080p。
> **⚠️ 开篇画面铁律（2026-08-18 用户否掉 v1 教训）**：①**禁止循环拼接同一段可灵视频**（v1 用 2 段×4 循环=画面重复，用户直接否掉）；②必须生成 **≥3 段不同 prompt 的可灵画面**（每段 10s，不同场景），每段只出现一次；③可灵段间**穿插实景素材** Ken Burns 做呼吸感；④xfade=1s 过渡；⑤**金句字卡首句必须 ≤60s 出现**（video_composer `_quote_times` 已修：`quotes[:6]` + 首句封顶 `audio_dur*0.06+15`）；⑥可灵生成用 kling-cli 技能（OpenMontage KlingClient，kling-v3，需先 python 加载 .env——CRLF 行尾不能 source）；⑦开篇拼接以 video_composer.py 为准（旧参考脚本曾存 /tmp，已归档不可依赖）；**⑧可灵余额不足降级（2026-08-18 008 实测 code 1102）**：可灵失败/余额不足时自动降级为「纯实景开篇」（assets/scenes 素材 Ken Burns 交替 + xfade + 首句金句字卡照常），禁止死等或报错，不影响正文与交付。

---

## 一、执行流程总览

Step 1: 选题池选书 → plan.tsv 待用行 + 配额规则（惬意 80%/历史 20%）选当日书
Step 2: 生成讲书稿 → AI 按 prompts/ 模板写稿（10 分钟约 2600-2800 字），生成前过质量门
Step 3: TTS 配音 → streaming_pipeline.py（分段生成→拼接→章节标记→-16 LUFS）
Step 4: 素材匹配 → scene_selector.py 选主题 + scene_fetcher.py 下载 + 目检入库
Step 5: 视频合成 → 60s 开篇 + video_composer.py 正文（实景 Ken Burns + 金句字卡）
Step 6: 交付质量门 → 素材/规格/文字/响度逐项打勾，任何 FAIL 禁止交付
Step 7: 小红书文案 → 配套文案 + 海报（60s 引流钩子）
Step 8: 飞书交付 → lark-cli 上传（MP4+音频+文稿），更新 plan.tsv 状态

---

## cron 无人值守端到端流程（飞书定时触发，2026-08-30 整理）

> 每日早班 6:15 / 晚班 18:15 由飞书 cron 触发，全程无人值守。入口 prompt 在生产 cron 环境（不在本仓库），按「〇、视频模式工作流 + 一、执行流程总览」执行。本节约束自动化关键点：

- **入口**：cron prompt → 选题（plan.tsv 待用行 + 配额）→ 讲书稿（约 2600-2800 字/10 分钟）→ 质量门 → TTS → 素材 → 合成 → 交付质量门 → 小红书文案 → lark-cli 上传飞书
- **超时**：video_composer 主合成 timeout 已放宽至 7200s（2 小时）；TTS 单段失败重试 2 次，仍失败即停止
- **失败策略**：任一步 fail-closed 停止（harness 退出码：2=质量门拦截 / 3=输出验证拦截 / 4=前置失败）；保留产物与日志供人工复核；**可灵失败自动降级纯实景开篇，禁止死等或报错中断**
- **开工自检（2026-08-30 引入，双轴 fail-closed）**：生产前必跑 `python3 /root/.hermes/scripts/dual_axis_selfcheck.py`——Standards 轴（技能文档命令参数/退出码 vs 实际 `--help` 实测）＋Spec 轴（选题池描述 vs plan.tsv 实际）。退出码 0 才开工，1/2 停止告警。**禁止凭记忆跳过验证**
- **ledger 记账（2026-08-30 引入）**：每本书在 `pipeline-ledger.md` 追加一行（日期/班次/书名/状态/链接/质量门/备注），失败记失败步骤；ledger 是断点重试与复盘依据
- **retry 假说**：重试前必须写「若 X 是原因，则改 Y 能通过」，禁止盲目重跑（防烧钱）
- **幂等**：选题即消费——选中后须将 plan.tsv 该行标记「已用」+ 使用日期；重复触发先 grep TSV 待用行与 pick.log 确认，防止重复生成/重复上传
- **产物路径**：bookmadebook-output/（out.mp4 + mp3 + 讲书稿.md）；上传飞书后记录消息链接
- **告警**：失败时 lark-cli 通知，次日人工复核产物与 TSV 状态

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
| adult（深度扩展） | prompts/deep_mode.txt | 深度模式（深挖论证） |
| adult（速览） | prompts/speed_mode.txt | 快速速览 |
| adult（TED 风格） | prompts/ted_mode.txt | TED 式演讲结构 |
| 各阶段通用 | prompts/chapter_summary.txt | 章节小结提示词 |

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

### 4.3 内容安全过滤

在生成脚本后、送入 TTS 前，必须过内容安全过滤：

from scripts.content_filter import ContentFilter
mode = "kids" if age_group != "adult" else "adult"
cf = ContentFilter(mode)
result = cf.check(script_text)

if not result["safe"]:
    # 替换不适内容为安全表述，重新生成该段
elif "warnings" in result:
    # 提醒家长陪听

### 4.4 脚本输出格式（两种输入模式）

生成结构化讲书稿，送入 TTS 支持两种模式：
- 纯文本：`-f script.txt`（见 5.1，默认用法，文本直接进 pipeline）
- 结构化 JSON：`--batch jobs.json`（jobs 数组，segments 的 text 拼接为完整文本送 TTS）


### 4.5 Harness 执行框架（质量门 + 输出验证门）

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

**CLI 用法（完整命令）**：
```bash
# 质量门（生成前）：--text 是讲书稿文件路径（不是 --script）
python scripts/quality_gate.py --text 讲书稿.txt --target-minutes 10 --voice zh-CN-XiaoxiaoNeural [--book-title 书名 --style ted]

# 输出验证门（生成后）：--audio 为生成的音频文件
python scripts/output_verify.py --audio out.mp3 --target-minutes 10 [--title-sample 标题样本.wav]

# 主控（串联全流程，推荐 cron/批量用）：
python scripts/harness.py --file 讲书稿.txt --target-minutes 10 [--voice auto --style ted --output out.mp3]
```
**退出码**：`harness.py` 为 0=成功 / 2=质量门拦截 / 3=输出验证拦截 / 4=前置阶段失败（书籍获取等）；**单跑 quality_gate.py / output_verify.py 直接返回 0=通过 / 1=不通过**——判断时勿混用。

---

**深度等级覆盖**：depth = quick/standard/deep/full，但 age_group 会限制可选深度。
- toddler/preschool 只支持 standard
- primary_lower/upper 支持 quick/standard/deep
- middle_school/high_school/adult 支持全部

### 4.6 视频合成（讲书音频 → 实景动态视频）

**设计原则（2026-08-07 用户确认，2026-08-11 升级）**：
- 实景写实照片（Pexels 免费图库，scene_fetcher.py 下载），不用 AI 生图
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
- `--theme auto`（默认）按内容自动选主题；手动指定可用值见 `python scripts/video_composer.py --help`（auto + arctic/desert/finance/forest/gufeng/hongkong/library/ocean/palace/pasture/rain/ship/snow/starry/sunrise/tech_city/temple/warm_home/ww2，共 19 个；素材目录 assets/scenes/ 另含 guyuan，scene_selector 关键词可自动匹配）
- `--scene-from auto|script|manual` 场景来源（标记/自动/手动）
- `--dry-run` 只输出场景规划不合成
- 自动提取【金句】标记 → 视频中段淡入淡出显示
- 输出 1080×1920 竖版（小红书/抖音适配）

**场景自动选择（2026-08-11 新增）**：
- 优先级：`--theme 手动 > 讲书稿【场景：XX】标记 > 自动检测（加权关键词统计）> 兜底 desert`
- `scene_selector.py`：复用 streaming_pipeline 的 CONTENT_VOICES，**加权统计**各类关键词命中数取最高（不是首命中——张居正传"汇报"误判职场教训）
- `scene_library.py`：本地素材库（assets/scenes/<theme>/ + ~/.cache/bookmadebook/scenes/），降级链 本地→缓存→下载→desert 兜底
- 多章节：`【场景：palace】` 标记可切段换主题，≤3 场景/片
- 素材清单：`assets/scenes/manifest.json`（各主题 Pexels URL，**已人工目检**：2026-08-11 清理了耳机/合影/手机等错配图）
- **注意**：manifest 中未逐一验证的 URL 内容可能不符（盲猜 ID 教训），新主题素材需人工目检
- **scene_fetcher.py**（2026-08-11 新增）：Pexels API 搜索下载素材（`--theme palace --download 3`），需 `PEXELS_API_KEY` 环境变量；API 返回真实图片+描述，杜绝盲猜
- **BGM 默认策略（2026-08-11 用户定案）**：商务/干货/历史内容默认无 BGM（`LISTEN_BOOK_NOBGM=1`，纯人声+云健男声）；抒情散文/治愈类可配 BGM（assets/bgm_*.mp3 + bgm_config.json），混音后必须 loudnorm 且不盖人声
- **战争/军事题材**：关键词自动选 ww2 主题（士兵剪影图，2026-08-13）；`--rate=-10%` 注意用等号（`-10%` 会被 argparse 误解析）
- **⚠️ 场景地域匹配铁律（2026-08-17 教训）**：palace 场景素材是**故宫/长城（中国建筑）**，只可用于中国题材（李鸿章/王阳明/万历/曾国藩等）；**欧洲/外国人物传记（拿破仑/梵高/歌德等）严禁用 palace**——拿破仑传曾误配故宫画面被用户抓包。选场景时先想"人物是哪个国家/地域"：欧洲战争人物→ww2（战争剪影）或 starry；欧洲艺术人物→starry/library；中国帝王将相→palace；自然题材→desert/forest/ocean/snow/pasture。**选题池 tsv 每本书的场景字段必须人工核对地域匹配后再入库**
- **船王/航运题材**：ship 主题（集装箱货轮图，2026-08-13）；**香港/政坛题材**：hongkong 主题（香港天际线图）；用户偏好：商务/传记男声用云健（zh-CN-YunjianNeural）比云扬更沉稳
- **Pexels 城市搜索坑**：搜 "hong kong skyline" 会混入里斯本/迪拜等相似城市港图，**下载后必须 vision 目检地标**（IFC/中银/摩天轮）再入库（2026-08-13 里斯本混入教训）
- **牧场/游牧题材**：pasture 主题（雪原羊群图，2026-08-13）；**磁性女声**：晓晓 + `--pitch=-15Hz`（低沉磁性，2026-08-13 新增 CLI 参数，注意用等号）
- **超长视频（45 分钟，已废弃 2026-08-21，仅备查）**：日常线固定 10 分钟规格；如未来临时做长视频：主合成 timeout 已放宽到 7200s（2 小时），45 分钟≈13500 字讲书稿，可 delegate_task 并行分章节写稿再合并；压缩才用「45 分钟长视频压缩铁律」（〇章节备注），日常线禁止套用
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

**设计音色覆盖（2026-08-21 用户验收，Qwen3-TTS 声音设计 API）**：
用户点名/重点内容优先用设计音色（`scripts/voice_design.py`，voice ID 见 references/voice-design.md）：
- 历史传记 → `hist_deep_male`（沉稳厚重老年男声 ✅用户定稿）
- 抒情散文/治愈小说 → `husky_tender`（母亲哄睡级温柔+沙哑烟嗓 ✅用户定稿，8轮迭代）
- 儿童故事 → `design_kid`（活泼童声 ✅用户定稿）
- 其他 → edge-tts 免费声兜底（上表）
- 不满意可改 voice_prompt 重新 create 无限迭代；试听验收=用户耳朵（lark-cli --audio 发 opus 语音消息）
- 描述铁律：先定年龄+醇厚底子再叠沙哑；禁"女孩/姑娘"（会出儿童基础音）；禁"解说/电台/歌手"（会出播音腔）
### 5.3 流水线内部处理（自动）

1. smart_split_text() → 按自然断点分3000字以内段
2. 逐段调 edge-tts 生成 MP3
3. 三级缓存检查（L1脚本/L2片段/L3成品）
4. ffmpeg 拼接所有段
5. add_chapter_markers() → 写入 ID3v2 章节标记
6. 输出最终 MP3

---

## 六、Step 5 — 交付用户

## 六·补、小红书文案方法论（2026-08-30 引入，coreyhaines31/marketingskills 提炼）

> 文案由 004 协作产出（或 AI 按本方法论撰写）。每条文案必须过本方法论门，不符合即重写。

### 标题公式（3 个备选必须公式错开）
1. 问题型：`{痛点}?`（例：「买了书翻三页就吃灰？」）
2. 反常识型：`这本书颠覆了我对{主题}的认知`（例：「看完这本书，我发现以前读的《XXX》都白读了」）
3. 价值型：`不{代价}也能{结果}`（例：「不熬夜也能读懂《XXX》」）
- 产出前过「Now you can」测试：给标题前缀"现在你可以…"，读起来具体且为真 → 保留；模糊/吹牛 → 重写

### 300 字三拍结构（Human Action Model）
1. **开头 60 字**：用读者原话戳痛点（「你是不是也买了书翻了三页就吃灰」）——禁止平铺「今天给大家推荐一本书」
2. **中间 180 字**：讲书给的愿景/新视角，**一本书只挑 1 个核心记忆点**，勿贪多
3. **结尾 60 字**：行动路径（「完整精读在主页视频」+ 橱窗），文末固定抛互动问题（「评论区扣 1，发你全书金句清单」）

### 第一行必须是钩子（四类选一）
- 好奇心型：「我被{常见认知}骗了很久」
- 故事型：「上周{意外}发生了」
- 价值型：「如何{结果}（不踩{坑}）」
- 反常识型：「冷知识：{大众做法}其实是错的」

### 商品清单内容化
用价值等式把 ≤100 元商品嵌进内容场景，而非硬挂——「书里提到的行动清单，橱窗帮你整理好了，均价 30 块」，低客单+互惠降决策门槛。

### 心理学弹药（可选叠加）
社会证明 / 稀缺紧迫（须真实）/ 损失厌恶 / 蔡格尼克（留悬念）——只用真实信息，禁止编造。

### 标签两层
固定支柱标签（#AI精读 #读书 #个人成长）+ 每本特色标签（按书主题）。

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| MP3 音频 | ~/bookmadebook/{书名}_{timestamp}.mp3 | 主交付物 |
| Markdown 文稿 | 同目录 .md 后缀 | 用 templates/script_doc.md.j2 渲染 |
| Obsidian 笔记 | Obsidian vault（如配置） | 自动存入 |
| MP4 视频 | bookmadebook-output/{书名}_10min.mp4 | 交付质量门通过后交付 |
| 小红书文案 + 海报 | 同输出目录 | 60s 开篇引流钩子，评论区引导听完整音频 |
| 飞书上传 | lark-cli 上传 | 上传前必须过交付质量门，记录消息链接 |
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
| scripts/quality_gate.py | 质量门（字数/重复/金句去重/markdown 残留） | Step 2 生成前 |
| scripts/output_verify.py | 输出验证门（标题残留/时长偏差/可解码） | TTS 生成后 |
| scripts/harness.py | 主控串联全流程（fail-closed） | cron/批量推荐入口 |
| scripts/video_composer.py | 正文视频合成（Ken Burns+字卡+章节时间轴） | Step 5 |
| scripts/scene_selector.py | 主题选择（标记+加权关键词） | Step 4 |
| scripts/scene_library.py | 素材库（本地→缓存→下载→desert 兜底） | Step 4 |
| scripts/scene_fetcher.py | Pexels API 素材下载（需 PEXELS_API_KEY） | Step 4 |
| scripts/voice_design.py | Qwen3-TTS 设计音色（hist_deep_male 等） | Step 3 |
| scripts/bgm_selector.py | BGM 选择/混音（loudnorm+alimiter） | 可选 |
| scripts/text_layers.py | 金句字卡 PIL 预渲染 | Step 5 |
| scripts/ted_director.py | TED 风格分段导演 | Step 2 |
| scripts/speed_probe.py | 语速实测 | Step 2 |
| scripts/deliver.py | 按时长压缩/分层（可选工具） | 交付 |
| scripts/config_loader.py | 配置加载（被 pipeline 自动调用） | 内部依赖 |
脚本间依赖关系：
book_info.py → AI 生成精读脚本（用 prompts/ 模板）→ content_filter.py 检查 → streaming_pipeline.py → cache_manager.py → 输出 MP3 + 文稿

---

## 选题池（2026-08-28 规则；2026-08-30 与实际 plan.tsv 对齐）

- **数据源**：`plan.tsv`（列：书名 | 主题 | 声音 | 视频场景 | 状态(待用/已用) | 使用日期）。当前池 23 本 = 惬意生活 11 + 历史传记 12；待用 9 本 = 惬意 5 + 历史 4。
- **配额规则（2026-08-28 用户定案）**：惬意生活 80% / 历史传记 20%（解忧杂货店类反响好，调高惬意占比）；循环节奏每 5 次 = 惬意×4 + 历史×1。
- **声音/场景映射**：惬意生活 = husky_tender（温柔沙哑）+ warm_home/library/gufeng/guyuan/pasture；历史传记 = hist_deep_male + palace/ww2。（2026-08-24 起已用行由晓晓逐步切换为 husky_tender，以 TSV 实际行为准）
- **选书脚本 pick.py 位于生产 cron 环境，不在本仓库**（仓库与技能目录均无该文件，实际路径以 cron 部署为准）；若在 cron 环境验证选池，**注意运行即消费（测试也消费）**——直接 grep TSV 待用行或 pick.log，勿实跑。
- 书单扩充/调整一律以 plan.tsv 实际行为准（本文不再列举书目清单，避免与 TSV 脱节）。

---

## 交付质量门（FAIL/PASS/验证清单，2026-08-29 ECC 拆解借鉴）

> 交付前逐项打勾，任何一项 FAIL 即禁止交付（重做后再验）。结构借鉴 ECC security-review 三段式：FAIL（禁止做的事）→ PASS（必须做的事）→ 验证清单（逐项打勾）。

### 1. 素材审核（禁真人/禁现代城市）

#### FAIL：禁止
- ❌ 真人/人物素材（汉服人物、人像、有人物的场景）——用户明确要求画面纯景色
- ❌ 远景含现代城市/高楼/公路/电线（Pexels 高清图远景常带城市，仅看缩略图会漏）
- ❌ 地域错配（欧洲人物配故宫 palace 素材——拿破仑传曾误配故宫被抓包）

#### PASS：必须
- ✅ 园林/山水/竹林/古建/静物（无人物）才可用
- ✅ 素材下载后拼图目检（PIL 4×3 缩略图 + vision 逐张确认无真人/现代元素）再入库
- ✅ 选场景先想人物国家/地域：中国帝王将相→palace；欧洲战争→ww2；欧洲艺术→starry/library；自然→desert/forest/ocean/snow/pasture

#### 验证清单
- [ ] 每张入库素材 vision 目检：无真人、无现代城市
- [ ] 远景放大确认（不止看缩略图）
- [ ] 选题池 tsv 场景字段与书目地域匹配

### 2. 视频规格（1080p 红线/像素格式/faststart）

#### FAIL：禁止
- ❌ `scale=720p` 压缩（2026-08-26《雅舍小品》模糊根因——agent 误套 45 分钟 x265+720p 命令）
- ❌ x265 编码（10 分钟日常线）
- ❌ 输出 MP4 不带 `-movflags +faststart`（moov atom 在末尾→lark-cli 报损坏、ffprobe 误判）
- ❌ 非 `-pix_fmt yuv420p`（默认可能 yuvj444p，飞书/手机无法解码）

#### PASS：必须
- ✅ `-c:v libx264 -crf 36 -preset faster -c:a aac -b:a 96k -pix_fmt yuv420p -movflags +faststart`
- ✅ 超过 20MB 可 crf38，但**分辨率永远保持 1080×1920**

#### 验证清单
- [ ] `ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0` 返回 `1080,1920`
- [ ] `ffprobe -v error -select_streams v -show_entries stream=pix_fmt -of csv=p=0` 返回 `yuv420p`
- [ ] `ffprobe -v error -show_entries format=duration` 可读（未损坏）
- [ ] 文件大小 <30MB（飞书限制）

### 3. 金句与文字（真实原文/无乱码）

#### FAIL：禁止
- ❌ 编造金句（无出处的句子冒充书中原话——004 初稿曾犯，008 已修正机制）
- ❌ drawtext 写 `\\n` 字面量（双反斜杠=渲染成 "n" 乱码——《浮生六记》乱码根因）

#### PASS：必须
- ✅ 金句=书中原句或凝练提炼，可查证
- ✅ 字卡/开篇渲染后**抽帧 vision 验证**无乱码再交付（`ffmpeg -ss 25 -i out.mp4 -frames:v 1 check.jpg`）

#### 验证清单
- [ ] 金句字卡与讲书稿一致（无编造）
- [ ] 抽帧 vision 目检文字无乱码/无缺字
- [ ] 引文修正机制生效（004 初稿 → 008 拦截替换可查证原文）

### 4. 音频响度（-16 LUFS）

#### FAIL：禁止
- ❌ loudnorm 后 I 值 < -17 LUFS 或 > -15.4（偏轻/偏炸，目标 -16±0.6）
- ❌ BGM 混音后盖过人声（人声不清晰即重混）
- ❌ 改音量参数不 bump 缓存指纹版本号（vol:v2 机制，否则旧缓存不失效）

#### PASS：必须
- ✅ 目标响度 -16 LUFS（EBU R128，TP≤-1.5，LRA 11）
- ✅ 三处 loudnorm 生效（concat 输出/mix_bgm 混音后/video_composer 兜底）
- ✅ 改音量参数必须 bump 缓存指纹版本号（vol:v2 机制）

#### 验证清单
- [ ] `ffmpeg -i file -af ebur128 -f null - 2>&1 | grep "I:"` 返回 -16±0.6
- [ ] BGM 混音后不盖人声（人声仍清晰可辨）

---

## 八、错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 书籍获取失败 | 告知用户，建议上传正版电子书或粘贴文本 |
| 内容安全拦截 | 替换不适内容，提示用户已自动调整 |
| TTS 连接失败 | 重试2次，仍失败则提示检查网络 |
| 音频拼接失败 | 检查 ffmpeg 安装，提示用户 |
| 缓存命中 | 跳过生成，直接使用缓存文件 |
| MP4 上传报「moov atom not found」 | 重压必须带 `-movflags +faststart`，ffprobe 验证可读再传 |
| 播放器无法解码/打开出错 | 检查 pix_fmt，重压 `-pix_fmt yuv420p` |
| 可灵生成失败（余额不足 code 1102 等） | 自动降级纯实景开篇，不影响正文与交付 |
| 视频 >30MB 飞书拒收 | crf 36→38 重压，分辨率保持 1080×1920 |
| 场景时间轴报 Numerical result out of range | 确认章节按 start 数字排序（chapters.sort），dry-run 验证时间轴 |

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

```
bookmadebook/
├── SKILL.md                    ← 本文件（AI执行指南）
├── config.yaml                 ← 全局配置（【常用】+【高级】标记）
├── listen.py / make_book.py    ← 入口脚本（音频/视频自适应，--output-type audio|video）
├── plan.tsv                    ← 每日选题池（待用/已用状态 + 使用日期）
├── assets/                     ← 素材：scenes/<theme>/（20 主题目录）+ bgm_*.mp3 + manifest.json
├── prompts/                    ← 讲书稿模板（children/teen + 深度/速览/TED/章节小结）
├── templates/                  ← 输出文稿模板（Jinja2）
├── references/                 ← EXECUTION_GUIDE.md / voice-design.md
└── scripts/                    ← 工具脚本（不要修改，共 21 个）
    ├── quality_gate.py / output_verify.py / harness.py          ← 质量门 + 验证门 + 主控
    ├── streaming_pipeline.py / speed_probe.py / voice_design.py / bgm_selector.py  ← TTS 链
    ├── video_composer.py / scene_selector.py / scene_library.py / scene_fetcher.py / text_layers.py / ted_director.py  ← 视频链
    ├── book_info.py / book_fetcher.py / content_filter.py / cache_manager.py / config_loader.py / deliver.py
    └── gen_cosy.py / tts_cosy.py                                ← 设计音色 TTS（Qwen3）
```

> **AIGC 合规声明**：本技能生成的内容由 AI 生成，请遵循相关法律法规及《人工智能生成合成内容标识办法》使用与传播。生成音频请在开头/结尾标注"本音频由AI生成"。
