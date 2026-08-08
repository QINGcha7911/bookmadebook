---
name: bookmadebook
version: 2.2.0
description: |-
  AI 书籍精读音频生成 — 全年龄段（3岁+），多场景、多声音、多深度。
  用户一句话 → 推荐书籍 → 生成精读脚本 → TTS转音频 → 交付 MP3 + 笔记。
  触发词：解读、精读、推荐书、听书、讲书、有声书、朗读、读书、语音、听、讲故事、书评、拆书。  
requires: python>=3.10

---
# bookmadebook — AI 执行指南

> 本文档是给 AI 的执行指南，不是用户手册。拿到任务后按以下流程走。

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

**设计原则（2026-08-07 用户确认）**：
- 实景写实照片（Unsplash 免费图库），不用 AI 生图
- 同主题连贯画面（如沙漠星空系列），避免场景跳跃
- 交叉溶解过渡（xfade 1.5s），画面平滑流动
- 文字只保留金句 + 书名，淡入淡出
- Ken Burns 缓慢缩放（zoompan），动态不呆板

**用法**：
```bash
python scripts/video_composer.py --script 讲书稿.txt --audio 音频.mp3 --book 书名 --output out.mp4
```
- `--theme desert|forest|ocean` 选择实景主题（沙漠/森林/海洋）
- 自动提取【金句】标记 → 视频中段淡入淡出显示
- 输出 1080×1920 竖版（小红书/抖音适配）

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

