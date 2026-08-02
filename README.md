[![EN](README_EN.md)](README_EN.md) ｜ [中文](README.md)

# 📚 Listen-Book — 把没时间读的书，变成耳朵里的 15 分钟

> AI 书籍精读音频生成 Skill | 全年龄段 · 多场景 · 多声音 · 多深度
> 说一句话 → AI 推荐书 → 生成精读 → 转语音 → 开听！

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![GitHub Stars](https://img.shields.io/github/stars/QINGcha7911/listen-book?style=social)](https://github.com/QINGcha7911/listen-book)

---

## 🎯 你是否有这些困扰？

- 📖 **买了书没时间读**，堆在书架落灰？
- 🏃 **跑步/通勤时想听书**，但听书App只会干巴巴朗读原文？
- 👶 **想给孩子讲故事**，但工作太忙没精力？或者想要用**爸爸妈妈自己的声音**讲？
- 🧠 **听完就忘**，想要要点笔记？

**Listen-Book 把任何一本书变成适合你当下场景的精读音频——30 秒出第一段，边生成边听。**

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
git clone https://github.com/QINGcha7911/listen-book.git ~/.hermes/skills/productivity/listen-book

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

---

## 🏗️ 项目结构

```
listen-book/
├── SKILL.md              # 主技能文件（含全部配置）
├── config.yaml           # 默认配置
├── prompts/              # 各年龄段提示词模板（children 4级 + teen 2级）
├── scripts/
│   ├── book_info.py          # 书籍信息获取（豆瓣/维基/古登堡，全合法）
│   ├── streaming_pipeline.py # 流式生成流水线（分段+章节标记+批量）
│   ├── content_filter.py     # 内容安全过滤器（kids/adult 双模式）
│   └── cache_manager.py      # 三级缓存（L1脚本/L2片段/L3成品）
├── templates/            # 输出模板
└── examples/             # 示例音频
```

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

- 🐛 遇到问题？[提 Issue](https://github.com/QINGcha7911/listen-book/issues/new?template=bug_report.yml)
- 💡 有新想法？[提建议](https://github.com/QINGcha7911/listen-book/issues/new?template=feature_request.yml)
- 📋 想一起开发？看 [Roadmap](docs/ROADMAP.md)

**维护说明**：本项目由单人维护，通过 AI Agent 团队（Hermes/Codex）自动化处理 Issue 分类、Bug 修复和功能开发。回复速度取决于复杂度，感谢理解 🙏

---

## 📄 License

[MIT](LICENSE) © 2026 QINGcha7911

---

## ⭐ Star 支持

如果这个项目帮到了你，欢迎 Star ⭐ 和分享给需要的人！
