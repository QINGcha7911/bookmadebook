# TED 风格精读 — 技术实现方案

> 目标：让 listen-book 从「播客/笔记体解读」升级为「TED 演讲体精读」——有语速起伏、有停顿、有情绪、有 BGM 配合，像一场 8-15 分钟的个人演讲。
> 本文档基于 2026-08 实测数据（streaming_pipeline.py v3、edge-tts 7.2.7、ffmpeg 6.1.1、中文朗读 296-310 字/分）。

---

## 0. 结论速览

| 问题 | 答案 |
|------|------|
| 流水线能不能直接出 TED？ | 不能。现状是「全局单一 voice + 单一 rate + 无停顿 + 无 BGM」，需要加一层**导演层（Annotation Director）** |
| 语速起伏怎么做？ | edge-tts 支持**每段独立 `--rate/--volume/--pitch`**（已实测），按段覆盖即可 |
| 停顿怎么做？ | edge-tts 无 pause 参数（已实测 CLI），用**注解切块 + ffmpeg 静音插入** |
| 情绪怎么做？ | edge-tts 无 SSML/express-as（已实测）→ 靠 文本措辞 + rate/pitch/volume 微调 + 声音选择 三杠杆；要真情绪上 Azure TTS premium 档 |
| BGM 有吗？ | TED 正片音乐克制：开场/结尾有音乐，正文基本干净。设计为「开场 sting + 结尾 fade + 金句 swell + 可选掌声」，用 ffmpeg sidechaincompress 做闪避 |
| 004 干什么？ | 选书推荐 + TED 文案生成（带注解）+ 金句/标题/上架文案 + 多版本 hook A/B |
| 005 干什么？ | 流水线 TED 模式开发（注解解析/每段参数/静音/BGM/缓存键迁移）+ 批量生成 + 测试 |
| 端到端多久？ | 选书 5min + 文案 3-5min + 生成 2-3min（流式首段 30s）+ 质检 2min ≈ **15min 内出成品** |

---

## 1. streaming_pipeline.py 改造（005 开发）

### 1.1 现状瓶颈（v3 实测）

| 能力 | 现状 | TED 需要 |
|------|------|---------|
| 语速 | 全局一个 `--rate=+0%` 贯穿全文 | 段级起伏：主线 +5%，慢段 -10~-15%，金句 -5% |
| 停顿 | 仅拼接处 0.3s acrossfade 过渡 | 金句前 0.6-1.0s、段落转折 0.5-0.8s 刻意留白 |
| 情绪 | 无（edge-tts 无 SSML） | 措辞 + rate/pitch/volume 微调 + 声音 |
| BGM | 无通道 | 开场 sting / 结尾 fade / 金句 swell / 掌声 |
| 章节标记 | 按「第N章/Part N」 | 应按 TED 结构标记：开场/观点1-3/金句/行动号召 |
| 缓存键 | `hash(全文)+voice+rate` | 必须加入 style 指纹 + 每段参数 hash，否则命中旧版 |

### 1.2 核心设计：导演层（Annotation Director）

```
带注解演讲稿（.md）
     │  ① parse_annotations()  ← 新增
     ▼
[TTS 块列表] 每块含: text / voice / rate / volume / pitch / pause_after / bgm_event
     │  ② generate_segment() 改造：接受块级 TTSConfig
     ▼
[音频块 + 静音 + 音乐事件]
     │  ③ concat_with_events() ← 新增：按时间线插静音、混 BGM/音效
     ▼
④ loudnorm 归一化 → ⑤ 章节标记（TED 结构标题）→ 输出
```

### 1.3 注解规范（演讲稿内嵌表演标记，供 AI 写作时插入）

| 标记 | 含义 | 流水线动作 |
|------|------|-----------|
| `【停顿0.8】` | 留白 0.8s | 块间插入 0.8s 静音（块内则切块） |
| `【放慢】` | 本节减速 | 本块 `rate=-12%` |
| `【加速】` | 本节提速 | 本块 `rate=+10%` |
| `【加重】` | 重音强调 | 本块 `volume=+6%` + `rate=-4%` |
| `【金句】` | 全场最强一句 | 前置停顿 0.6s + 后置停顿 0.9s + BGM swell + 本块 `rate=-5%` |
| `【情绪：激动】` | 情绪微调 | `pitch=+3Hz` + `rate=+8%`；`【情绪：低沉】` → `pitch=-3Hz, rate=-10%` |
| `【BGM：起】` / `【BGM：收】` | 音乐事件 | 时间线记音乐淡入/淡出 |
| `【掌声】` | 掌声音效 | 开场问候后、结尾各一次（短促 2-3s，-12dB） |

**关键区分**：现有 `clean_markdown_for_tts()` 会删除「（共鸣式，40秒）」这类制作说明——**【】表演标记必须保留并先于清理逻辑提取**（解析器先抽注解、再从正文里剥掉标记，剥离后的纯文本才进 TTS）。

### 1.4 代码改动清单（streaming_pipeline.py）

```
1. 新增 style_profiles/ted.yaml（见 §1.6），CLI 加 --style ted
2. 新增 parse_annotations(text) → List[SpeechBlock]
   SpeechBlock = {text, voice, rate, volume, pitch, pause_after, bgm, tag}
   注解正则: 【(停顿[\d.]+|放慢|加速|加重|金句|情绪：[^】]+|BGM：[^】]+|掌声)】
3. generate_segment 签名改造:
   (text, voice, rate) → (block: SpeechBlock)
   内部拼 rate_arg = f"--rate={block.rate}"、volume、pitch（等号形式，负值坑已有记录）
4. smart_split_text：先 parse_annotations 切块，再做 1500 字安全分段（块太长时在句号处断开，保留块级参数）
5. 拼接改造 concat_with_events()：
   - 块间按 pause_after 插入静音（ffmpeg anullsrc 或预生成 silence.wav 拼接）
   - 保留 acrossfade 三角波过渡（0.3s）
   - 按 BGM 时间线混音（§4.4 命令）
6. 缓存键迁移（大坑！）：
   L2 键: hash(block.text + block.voice + block.rate + volume + pitch)
   L3 键: hash(full_text + style_id + style_profile_hash)
   → 发布 TED 模式后必须 rm -rf ~/.hermes/cache/listen-book/{l2,l3}/
7. extract_chapters_from_text：优先用 TED 结构标签（开场/观点/金句/行动号召）作章节标题
8. batch_pipeline：job 支持 style 字段，支持「书单 JSON」批量出 TED 版
```

### 1.5 情绪实现的三杠杆（edge-tts 无 SSML 的替代方案）

edge-tts 7.2.7 CLI 仅 `--rate/--volume/--pitch`（已实测 help），**无 SSML/express-as**。TED 情绪靠：

1. **文本措辞（主杠杆）**：短句（≤20字）、排比×3、修辞问句、具体故事细节——情绪是写出来的，不是 TTS 调出来的
2. **段级 rate/pitch/volume 微调（次杠杆）**：激动段 +8% rate / +3Hz pitch；低沉段 -10% rate / -3Hz pitch；金句 -5% + 停顿
3. **声音选择（底层杠杆）**：见 §3

**Premium 档（可选升级）**：真要「带情绪的神经语音」→ 换 Azure TTS（同系声音 + SSML `<mstts:express-as style="serious/cheerful">`）或 OpenAI gpt-4o-mini-tts（instructions 指定语气）或 ElevenLabs。作为 `tts_engine` 抽象层的另一实现接入，TED 模式默认仍走 edge-tts（免费）。

### 1.6 style_profiles/ted.yaml 草案

```yaml
# style_profiles/ted.yaml
id: ted
voice: zh-CN-YunjianNeural        # 主推：沉稳有力（见 §3）
base_rate: "+5%"                  # 演讲主线略快，制造"在台上讲"的节奏
segment_defaults:
  rate: "+5%"
  volume: "+0%"
  pitch: "+0Hz"
pause_defaults:
  paragraph: 0.5                  # 段间停顿 s
  hook_after: 0.7                 # 开场 hook 后
  golden_sentence: 0.9            # 金句后
bgm:
  enabled: true
  intro: assets/ted_intro.mp3     # 0-15s 音乐 sting，-22dB 淡入淡出
  outro: assets/ted_outro.mp3     # 结尾 15s 淡出
  swell_at: ["金句", "行动号召"]   # 这些块触发音乐 swell -28dB→-22dB
  duck_level: "-28dB"             # 说话时音乐电平
  swell_level: "-22dB"
sfx:
  applause: assets/applause.wav   # 开场后 + 结尾，-12dB，2-3s
chapters:
  use_ted_structure: true         # 章节标记用 开场/观点N/金句/行动号召
duration_estimate_chars_per_min: 296   # 云健实测，文案字数换算用
```

---

## 2. TED 风格 prompt 模板（演讲稿写作）

### 2.1 笔记体 vs 演讲体（写作范式切换）

| 维度 | 笔记体（现状 standard/deep 模板） | TED 演讲体（新 ted_mode） |
|------|--------------------------------|--------------------------|
| 人称 | 第二人称聊天「你有没有想过」 | 第一人称「我」+ 直面听众「你」，像站在台上 |
| 开场 | 生活场景/痛点切入 | **Hook**：惊人数据 / 反常识问题 / 一分钟故事 |
| 结构 | 开场→作者→观点→金句→总结 | hook → 展开（故事→原理→金句收束）×3 → 高潮 → 行动号召 → 回扣开场 |
| 句子 | 每句 ≤30 字，口语化 | 短句 ≤20 字，关键句更短、更有力 |
| 修辞 | 排比问句（偶尔） | 排比×3（至少一处）、修辞问句、对照、重复强调 |
| 金句 | 回顾原句 2-3 句 | 每观点收束一句 + 全场一句最强金句（【金句】标记） |
| 结尾 | 「如果觉得有帮助，欢迎分享」 | 行动号召（给听众一件可做的事）+ 回扣开场意象 |
| 表演 | 无 | 全程插入【停顿】【放慢】【金句】等表演标记 |
| 禁忌 | 首先/其次/总之 | 同上 + 不念书名/标题开场（延续用户硬性偏好）|

### 2.2 ted_mode prompt（可直接落盘 prompts/ted_mode.txt）

```text
[SYSTEM]
你是一位 TED 演讲撰稿人。为《{book_name}》写一篇 8-15 分钟的 TED 演讲体精读稿。
你不是在解读一本书，而是在准备一场演讲——这本书给了你一个值得站上舞台的「想法」。

[STRUCTURE]（严格按此顺序，每段标注时长）
1. Hook 开场（0:00-0:45）：用惊人数据 / 反常识问题 / 一个 30 秒小故事开场。
   直接进入主题，不念书名、不自我介绍、不报时长。
2. 这本书为什么值得讲（~30s）：作者经历过什么，让他/她必须写这本书（1-2 句背景即可）。
3. 核心观点 ×3（每个 60-90s），每观点内部遵循：故事/案例（具体细节）→ 原理（一句话讲清）→ 金句收束。
   三个观点之间要有递进或转折，不能并列堆砌。
4. 高潮段（~30s）：全书最有力量的一句话，前面放【停顿0.8】，说完放【金句】。
5. 行动号召（~30s）：给听众一件今晚就能做的事，用「你可以」「试试看」。
6. 结尾（~15s）：回扣开场的意象或问题，一句收束金句，不再寒暄。

[STYLE RULES]
- 第一人称「我」讲述 + 直接对听众说话，像在台上，不像在念稿
- 短句为主（≤20 字），关键句更短（≤10 字）
- 至少一处排比 ×3；至少两个修辞问句（「如果……会怎样？」）
- 用具体细节和数字，不用抽象形容词堆砌
- 每 60-90 秒安排一个钩子或金句
- 在合适位置插入表演标记：【停顿0.8】【放慢】【加速】【加重】【金句】【情绪：激动】【情绪：低沉】
- 全文禁用：首先/其次/最后/综上所述/这是一本……的书/我们下期见
- 不出现书名和作者名作标题，正文开头第一句就是 hook

[BOOK CONTENT]
{full_text / 预摘要}
```

### 2.3 开场样例（演讲体对照，延续「共鸣式开场」实测有效的思路）

```
❌ 笔记体：你有没有想过，为什么有些人面对打击总能站起来？
✅ 演讲体：2018 年，我一个人在深夜的出租屋里，盯着手机银行余额发呆。
   【停顿0.8】
   那个数字比我的人生规划少了一个零。
   【放慢】
   后来我读了一本书，里面有个老人，八十四天没钓到一条鱼。
   【停顿0.6】
   他决定，再出海一次。
```

---

## 3. 声音选择（已用 edge-tts --list-voices 实测微软官方风格标签）

### 3.1 中文 TED 主推

| 声音 | 微软官方标签 | TED 定位 | 建议 |
|------|------------|---------|------|
| **zh-CN-YunjianNeural 云健** | Male · **Passion** | 有力 + 沉稳，像 TEDx 讲者 | **主推**（已有 296字/分 实测校准数据） |
| zh-CN-YunyangNeural 云扬 | Male · **Professional, Reliable** | 播音腔、权威感 | 备选（更"官方"、更高龄感） |
| zh-CN-XiaoxiaoNeural 晓晓 | Female · **Warm** | 有温度的女声叙事 | 备选（情感向书目） |
| zh-CN-YunxiNeural 云希 | Male · **Lively, Sunshine** | 偏年轻活力 | 不推荐（TED 要沉稳不要活泼） |

**关键原则：TED 是单人演讲，全程单一声音**——不要多角色切换（那是播客体）。变化靠 §1.5 的语速/停顿/情绪杠杆。

### 3.2 英文 TED 主推

| 声音 | 微软官方标签 | 建议 |
|------|------------|------|
| **en-US-AndrewNeural** | **Warm, Confident, Authentic, Honest** | **主推**——最接近真实 TED 讲者声线 |
| en-US-ChristopherNeural | Reliable, **Authority** | 现有英文默认，权威沉稳（新闻感略重） |
| en-US-GuyNeural | **Passion** | 激情型备选 |

### 3.3 语速参数建议（基于 296-310 字/分实测）

| 段落类型 | rate | 说明 |
|---------|------|------|
| 主线叙事 | +5% | 演讲节奏，略快于解读 |
| 观点论证 | +0% | 正常 |
| 【放慢】情绪段 | -10~-15% | 关键故事/沉重点 |
| 【金句】 | -5% + 前后停顿 | 全场最强句，慢而重 |
| 【加速】铺垫段 | +10% | 排比递进、铺垫高潮 |

---

## 4. BGM / 音效配合

### 4.1 TED 的真实情况（设计依据）

- **正片基本无持续 BGM**：TED 官方演讲是干净的——只有开场/过场/结尾的音乐，正文靠讲者本身
- 「现场感」元素：开场掌声、妙语后的笑声、结尾掌声
- 电视/播客重制版才会铺一层低音量 ambient

### 4.2 我们的克制型设计（TED 风格 = 克制）

| 位置 | 内容 | 电平 | 时长 |
|------|------|------|------|
| 开场 0-15s | 音乐 sting 淡入淡出（钢琴/氛围） | -22dB | ~15s |
| 【金句】处 | 音乐 swell（从 -28 浮起到 -22） | -22dB | ~8s |
| 高潮段 | 同上 | -22dB | 段落长 |
| 结尾 15s | 音乐淡出收尾 | -22→-60dB | ~15s |
| 开场问候后 | 掌声音效（可选） | -12dB | 2-3s |
| 结尾 | 掌声音效（可选） | -12dB | 3-4s |
| 正文说话时 | 若铺 ambient 垫乐 | **-28dB** | 全程 |

### 4.3 素材

- 免费钢琴/氛围音轨：Pixabay Music（无版权）、或 ffmpeg `sine`/`anoisesrc` 合成极简 pad
- 音效：applause.wav（网上免费 CC0）、开场 sting 可截取任意氛围曲前 15s
- 全部放 `assets/`，ted.yaml 引用

### 4.4 混音实现（ffmpeg 6.1.1 已实测支持 sidechaincompress/amix）

**方案：闪避混音（ducking）**——人声主导，音乐在停顿/段落间浮起：

```bash
# 人声轨 voice.wav + 音乐轨 music.wav（已按时间线裁剪/循环）
ffmpeg -i voice.wav -i music.wav \
  -filter_complex "\
[1:a]volume=0.04[m0];\           # 音乐基础电平 ≈ -28dB
[0:a][m0]sidechaincompress=\
  threshold=0.05:ratio=8:attack=200:release=800[ducked];\  # 人声说话时压音乐
[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=3[aout]" \
  -map "[aout]" -c:a libmp3lame -b:a 192k final.mp3
```

- 金句 swell：在音乐轨对应时间点用 `volume=enable='between(t,32,40)':volume=0.06` 做电平提升（ted.yaml 的事件时间线驱动）
- 停顿静音：`anullsrc` 生成 silence 块与 acrossfade 序列拼接（沿用现有逐对拼接模式）
- 掌声：直接 amix 叠加，音量 -12dB，裁剪 2-3s

---

## 5. 004（Coze）与 005（Codex）分工

### 5.1 004（Coze 云端 bot，无本地文件）——内容侧

| 任务 | 说明 |
|------|------|
| 选书推荐 | 输出「TED-able 书单」：认知科学/人物传记/方法论，叙事性强、有单一核心想法的书（TED 讲的是"一个想法"，不是"一本书的总结"） |
| TED 文案生成 | 按 §2.2 ted_mode prompt 写带表演注解的演讲稿 |
| 多版本 hook A/B | 同一本书给 3 个不同开场（数据型/故事型/反常识型），用户挑 |
| 金句提炼 | 从书/稿中提炼 3-5 句最强金句供【金句】标记使用 |
| 上架文案 | 音频标题、节目简介、喜马拉雅/公众号发布文案 |
| 批量策划 | 每周书单 + 排期表（TED 精读专栏） |

**交付方式（沿用已知流程）**：004 无法传文件 → 演讲稿内容**贴成飞书消息**（长文分段贴）→ 007 校验完整性（无重复段落/无残留代码块标记）后落盘 `/root/.hermes/cache/documents/`。

### 5.2 005（Codex 本地沙箱）——工程侧

| 任务 | 说明 |
|------|------|
| 流水线改造 | §1.4 全部改动：注解解析器、块级 TTSConfig、静音插入、BGM 混音、章节标记 |
| style_profiles | ted.yaml + CLI `--style ted` + 批量书单 JSON 支持 |
| 缓存键迁移 | L2/L3 键加入 style 指纹（防命中旧版） |
| 测试 | 注解解析单测 + 时长回归（296字/分校准）+ 截断检测接入 |
| QA 工具 | 生成后自动 ffprobe 时长/章节/响度校验脚本 |
| 交付 | git commit → push 到 QINGcha7911/listen-book（005 需 `--sandbox workspace-write`） |

**验证规则（沿用 multi-agent-coordination 强制协议）**：005 自报完成 ≠ 完成。007 独立验证：改完清 `~/.hermes/cache/listen-book/{l2,l3}/` → 实测生成一段 TED 音频 → ffprobe 验时长/章节 → 试听首尾。

### 5.3 分工边界速记

> **004 写"讲什么、怎么讲"（内容+文案），005 写"怎么生成、怎么调参"（代码+流水线），007 管编排、校验、分发。**

---

## 6. 完整流程（选书 → 出音频）

```
① 选书        004 推荐 3-5 本 TED-able 书目（叙事强+单一核心想法）
              + 007 验证内容可得性（豆瓣简介/维基/公版全文/用户上传，合规来源链）
              → 用户拍板 1 本

② 定版        用户选：书 + 目标时长（TED 精读建议 8-15min）+ 声音（默认云健）
              007 把参数写入 job JSON

③ 文案        004（或 007 直出）按 ted_mode prompt 写带注解演讲稿
              007 落盘 → 字数校验：目标分钟 × 296 ≈ 字数（15min ≈ 4400字）

④ 审稿        007 检查：结构（hook→观点×3→高潮→行动号召→回扣）
              注解合法性（标记白名单、停顿数值范围）
              清理 markdown（标题行/加粗/列表，延续"不念标题"偏好）

⑤ 生成        streaming_pipeline.py --style ted -f 稿.txt
              注解解析 → 块级 TTS（每块 rate/volume/pitch 独立）
              → 静音插入 → BGM/掌声混音 → acrossfade 拼接 → loudnorm
              → TED 结构章节标记 → MP3（192k）
              流式模式：首段 30s 送达

⑥ 质检        007：ffprobe 时长（对照目标 ±10%）+ 截断检测 + 响度
              试听 hook 段和金句段（停顿/语速是否到位）
              不达标 → 迭代追加 600-1500字/轮（沿用实测有效的追加法）

⑦ 分发        MP3 + 演讲稿 → 飞书 / Obsidian / 喜马拉雅
              附 AIGC 合规声明：「本音频由 AI 生成」（2025-09-01 强制）

⑧ 迭代        用户反馈 → 调 ted.yaml（语速基线/音乐电平/声音）
              → rm -rf l2/l3 缓存 → 重新生成
```

**关键里程碑（首版上线）**：
- M1（0.5 天）：005 完成 §1.4 的 1-5 项 + ted.yaml → 手动能出一条带停顿的 TED 音频
- M2（+0.5 天）：BGM/掌声混音 + 章节标记 + 批量模式 → 能批量出
- M3（+0.5 天）：004 的 ted_mode 文案流程跑通（推荐→写稿→落盘→生成）→ 端到端 15min

---

## 7. 风险与坑（提前埋好）

1. **缓存命中旧版（必踩）**：改流水线后不清 l2/l3 → 返回旧音频，误以为没改。所有验证前先清缓存。
2. **注解被 clean_markdown_for_tts 误删**：解析器必须先抽【】标记，再走清理；清理正则要排除【】。
3. **负 rate 传参坑**：`--rate=-12%` 必须等号形式（空格形式 argparse 报错，已实测）。
4. **1500 字安全分段**：块再大也要 ≤1500 字（600s 静默截断硬上限，已实测），【放慢】段的块要更保守（慢速 = 同样字数更长时间）。
5. **中文 296 字/分是云健 +0% 基准**：base_rate=+5% 时实际约 310 字/分，文案字数换算按此；【放慢】段会拉低总时长预测，字数估算留 10% 余量。
6. **sidechaincompress 参数要试听**：threshold/ratio 不当会导致音乐"抽气感"，用默认 + 试听微调。
7. **004 长稿分段贴可能重复段落**：落盘后按重复段落检测（沿用已知校验流程）。
8. **TED ≠ 播客**：禁止多角色配音/访谈体；单一声音 + 演讲结构，这是风格保真的底线。

---

## 附：ted_mode 演讲体样例（hook 段，含注解）

```text
1996 年，有个人在苹果发布会上，掏出了一个方方正正的盒子。
【停顿0.8】
他说，这玩意儿，能装下一千首歌。
【放慢】
台下没人信。
【金句】
但十八年后，他让全世界每个人都装过一千首歌。
【情绪：激动】
乔布斯不是发明了音乐播放器，他发明的是——「把不可能，说成明天的事」。
```

（本段 ≈ 130 字 ≈ 30s，符合 hook 段 0:00-0:45 规格；字数-时长换算按 296字/分。）
