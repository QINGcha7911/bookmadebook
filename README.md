[![EN](README_EN.md)](README_EN.md) ｜ [中文](README.md)

# 📚 Bookmadebook — 把没时间读的书，变成耳朵里的 15 分钟

> AI 书籍精读音频生成 Skill | 全年龄段 · 多场景 · 多声音 · 多深度
> 说一句话 → AI 推荐书 → 生成精读 → 转语音 → 开听！

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![GitHub Stars](https://img.shields.io/github/stars/QINGcha7911/bookmadebook?style=social)](https://github.com/QINGcha7911/bookmadebook)

---

## 🎯 你是否有这些困扰？

- 📖 **买了书没时间读**，堆在书架落灰？
- 🏃 **跑步/通勤时想听书**，但听书App只会干巴巴朗读原文？
- 👶 **想给孩子讲故事**，但工作太忙没精力？或者想要用**爸爸妈妈自己的声音**讲？
- 🧠 **听完就忘**，想要要点笔记？

**Bookmadebook 把任何一本书变成适合你当下场景的精读音频——30 秒出第一段，边生成边听。**

```
你：帮我解读《原子习惯》，跑步时听
AI：推荐 → 选书 → 生成精读 → 语音输出
```

---

## 🎧 试听一下

| 示例 | 场景 | 时长 | 亮点 |
|------|------|------|------|
| 🎤 [活着-TED演讲版](examples/活着-TED演讲版.mp3) | TED风格/高三激励 | ~9min | **TED导演层**：语速起伏+停顿+智能BGM+情绪 |
| 🌍 [励志英文-TED风格](examples/励志英文-TED风格.mp3) | 英文/励志 | ~0.7min | **英文自动选声**：Christopher男声+TED风格 |
| 🧒 [小王子-儿童睡前版](examples/小王子-儿童睡前版.mp3) | 亲子/睡前 | ~2.5min | 儿童模式：慢速+互动+内容过滤 |
| 📜 [孙子兵法-速览](examples/孙子兵法-速览.mp3) | 通勤 | ~1min | 速览模式 |
| 🧠 [思考快与慢-精读](examples/思考快与慢-精读.mp3) | 深度学习 | ~2min | 深度精读 |
| 📱 [原子习惯-成人-跑步](examples/原子习惯-成人-跑步.mp3) | 跑步 | ~3min | 跑步场景 |

> 💡 **2个新示例展示核心能力**：《活着》TED版=导演层全功能（情绪/停顿/BGM）；英文版=语言自动选声。

---

## 🎬 真实产出案例（视频精读）

> 以下均为本项目**实际生成并交付**的内容（非演示素材），含完整讲书稿、成片与文案。

| 作品 | 时长 | 声音 | 画面主题 | 讲书稿 |
|------|------|------|----------|--------|
| ⚔️ [二战战史-人类最惨烈六年](examples/screenshots/ww2_video.png) | 10min | 云扬·史诗男声 | 战争史诗（士兵剪影/雪原/海面） | [讲书稿](examples/scripts/二战战史_讲书稿.md) |
| 🏔️ [冬牧场-李娟散文](examples/screenshots/dongmuchang_video.png) | 10min | 晓晓·磁性女声 | 雪原牧场/牧民生活 | [讲书稿](examples/scripts/冬牧场_讲书稿.md) |
| 🌌 [挪威极夜-人文地理](examples/screenshots/norway_video.png) | 10min | 晓晓·温柔女声 | 北极极夜（极光/雪原/蓝调时刻） | [讲书稿](examples/scripts/挪威极夜_讲书稿.md) |
| 🦈 [亿万-围剿华尔街大白鲨](examples/screenshots/yiwan_video.png) | 10min | 云健·沉稳男声 | 华尔街金融（纽交所/交易大屏） | [讲书稿](examples/scripts/亿万围剿_讲书稿.md) |
| 🍲 [慢煮生活-汪曾祺](examples/screenshots/zhishenshinei_video.png) | 10min | 晓晓·温柔女声 | 暖光家居/生活美学 | [讲书稿](examples/scripts/慢煮生活_讲书稿.md) |

**完整成片已归档**：二战战史 / 冬牧场（10min & 45min）/ 挪威极夜 / 亿万 / 置身事内 / 慢煮生活 —— 全部通过质量门（时长偏差 0%、金句 4-6 条、AI 标识内置）。

### 🎥 视频能力（v2.2.0+）
- 1080×1920 竖版 + Ken Burns 动态运镜 + 交叉溶解
- **19 个实景主题库**：北极极夜/华尔街金融/战争史诗/雪原牧场/沙漠星空/海洋/森林/暖光家居…（新增主题入库 GitHub 即永久复用）
- 金句字幕（从讲书稿【金句】标记自动提取，去重后嵌入）
- 章节标题浮层 + 封面抽帧 + 右下角 AI 生成内容标识（合规）

---

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 🎙️ **父母声音克隆** | 录20秒 → 让爸爸妈妈用自己的声音给孩子讲故事（免费）|
| 🧒 **全年龄段** | 0-3岁幼儿 → 18+成人，7级分级，内容安全过滤 |
| 🎬 **多场景** | 通勤 / 跑步 / 睡前 / 亲子 / 深度学习 / 午休 |
| 🎤 **多声音** | 5种内置中文声线，免费切换 |
| 📏 **时长自选** | 3分钟速览 → 45分钟深度精读 |
| 🚀 **流式交付** | 30秒听到第1章，后台续播，不等全量生成 |
| 📝 **笔记输出** | 精读音频 + 同步生成笔记存入 Obsidian |
| 🔍 **智能推荐** | 不知道听什么？说个话题，AI 推荐书 + 高光片段 |
| 🛡️ **内容安全** | 儿童/青少年模式自动过滤暴力、恐怖、成人内容 |
| ⚖️ **版权合规** | 精读=种草引流（非盗版），书源自公开信息/公版书/用户正版 |

---

## 🚀 快速开始

### 1. 安装

```bash
# Hermes Agent 用户
git clone https://github.com/QINGcha7911/bookmadebook.git ~/.hermes/skills/productivity/bookmadebook

# 依赖
pip install edge-tts mutagen
sudo apt install ffmpeg   # macOS: brew install ffmpeg
```

### 2. 使用（说一句话就行）

```text
帮我解读《原子习惯》
跑步时听《小王子》，8分钟
给我6岁的女儿解读《西游记》，亲子模式
我想听关于自律的书
完整解读《乔布斯传》，45分钟
用我的声音给孩子讲故事（附上录音）
```

### 3. （可选）配置

```yaml
# config.yaml
age_group: adult        # toddler/preschool/primary_lower/primary_upper/middle_school/high_school/adult
scene: commute          # commute/running/bedtime/parent_child/deep_learning/lunch_break
depth: standard         # quick/standard/deep/full
voice: auto             # auto/xiaoshuang/xiaoxiao/yunxi/yunjian/yunyang
```

> 💡 90% 用户不需要改配置，开箱即用。

---

## 📖 详细文档

- [配置说明](config.yaml)
- [Roadmap](docs/ROADMAP.md)
- [年龄段与内容安全](SKILL.md)
- [Harness 执行框架架构](docs/harness-architecture.md)

---

## 🏗️ 项目结构

```
bookmadebook/
├── SKILL.md              # 主技能文件（含全部配置）
├── config.yaml           # 默认配置
├── prompts/              # 各年龄段提示词模板（children 4级 + teen 2级）
├── scripts/
│   ├── book_info.py          # 书籍信息获取（豆瓣/维基/古登堡，全合法）
│   ├── streaming_pipeline.py # 流式生成流水线（分段+章节标记+批量）
│   ├── quality_gate.py       # 🛡️ Harness质量门：生成前校验（字数/重复/金句去重/markdown/版权）
│   ├── output_verify.py      # 🛡️ Harness输出验证门：生成后校验（标题残留/时长偏差/完整性）
│   ├── content_filter.py     # 内容安全过滤器（kids/adult 双模式）
│   └── cache_manager.py      # 三级缓存（L1脚本/L2片段/L3成品）
├── templates/            # 输出模板
└── examples/             # 示例音频
```

---

## 🗓️ 更新日志

| 日期 | 版本 | 内容 |
|------|------|------|
| 2026-08-16 | v2.2.1 | 🚀 性能修复：zoompan 冗余计算消除（渲染提速，实测 175×175→213 帧）；DSH 独立审查驱动 P0+P1 七项修复（正则字数统计/缓存键/TED章节偏移/残缺文件校验/超时兜底/空输入保护） |
| 2026-08-16 | v2.2.0 | ✨ 新增 2 个实景主题：`arctic` 北极极夜（极光/雪原/蓝调）、`finance` 华尔街金融（纽交所/交易大屏）；主题库达 19 个 |
| 2026-08-14 | v2.2.0 | 🎬 视频合成器正式版：金句字幕自动嵌入、章节浮层、封面抽帧、AI 标识内置 |
| 2026-08-13 | v2.1.0 | 🎧 10 分钟精读实战流程固化（讲书稿框架/声音选择/素材匹配） |

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

- 🐛 遇到问题？[提 Issue](https://github.com/QINGcha7911/bookmadebook/issues/new?template=bug_report.yml)
- 💡 有新想法？[提建议](https://github.com/QINGcha7911/bookmadebook/issues/new?template=feature_request.yml)
- 📋 想一起开发？看 [Roadmap](docs/ROADMAP.md)

**维护说明**：本项目由单人维护，通过 AI Agent 团队（Hermes/Codex）自动化处理 Issue 分类、Bug 修复和功能开发。回复速度取决于复杂度，感谢理解 🙏

---

## 📄 License

[MIT](LICENSE) © 2026 QINGcha7911

---

## ⭐ Star 支持

如果这个项目帮到了你，欢迎 Star ⭐ 和分享给需要的人！
