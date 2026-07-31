# 📚 Book-to-Audio — 把你的书变成耳朵的盛宴

> AI 书籍精读音频生成 Skill | 全年龄段 · 多场景 · 多声音 · 多深度
> 说一句话 → AI 推荐书 → 生成精读 → 转语音 → 开听！

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## 🎯 它能做什么

**跑步、开车、通勤、睡前、亲子时光——把任何一本书变成适合你当下场景的精读音频。**

```
你：帮我解读《原子习惯》，跑步时听
AI：推荐 → 选书 → 生成精读 → 语音输出（30秒出首段）
```

### 支持的能力

| 能力 | 说明 |
|------|------|
| 🧒 **全年龄段** | 0-3岁幼儿 → 18+成人，7级分级，内容安全过滤 |
| 🎬 **多场景** | 通勤 / 跑步 / 睡前 / 亲子 / 深度学习 / 午休 |
| 🎤 **多声音** | 5种内置中文声线，免费；可克隆父母声音（免费） |
| 📏 **时长自选** | 3分钟速览 → 45分钟深度精读 |
| 🚀 **流式交付** | 30秒听到第1章，后台续播，不等全量生成 |
| 📝 **笔记输出** | 精读音频 + 同步生成笔记存入 Obsidian |
| 🔍 **智能推荐** | 不知道听什么？说个话题，AI 推荐书 + 高光片段 |
| 🛡️ **内容安全** | 儿童/青少年模式自动过滤暴力、恐怖、成人内容 |

---

## 🚀 快速开始

### 1. 安装

```bash
# Hermes Agent 用户
git clone https://github.com/你的用户名/book-to-audio.git ~/.hermes/skills/book-to-audio

# 依赖
pip install edge-tts
sudo apt install ffmpeg   # macOS: brew install ffmpeg
```

### 2. 使用（说一句话就行）

```text
帮我解读《原子习惯》
跑步时听《小王子》，8分钟
给我6岁的女儿解读《西游记》，亲子模式
我想听关于自律的书
完整解读《乔布斯传》，45分钟
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

- [中文文档](docs/README.zh-CN.md)
- [English Docs](docs/README.en.md)
- [配置说明](docs/CONFIGURATION.md)
- [年龄段设计](docs/AGE_GROUPS.md)
- [Roadmap](docs/ROADMAP.md)

---

## 🎧 示例音频

| 示例 | 年龄 | 场景 | 时长 |
|------|------|------|------|
| 《原子习惯》 | 成人 | 跑步 | 3分钟 |
| 《小王子》 | 3-6岁 | 睡前 | 2.5分钟 |
| 《乔布斯传》 | 成人 | 深度学习 | 13分钟 |

> 音频文件在 `examples/` 目录

---

## 🏗️ 项目结构

```
book-to-audio/
├── SKILL.md              # 主技能文件（含全部配置）
├── config.yaml           # 默认配置
├── prompts/              # 各年龄段提示词模板
│   ├── children/         # 0-12岁（4级）
│   └── teen/             # 12-18岁（2级）
├── scripts/
│   ├── streaming_pipeline.py  # 流式生成流水线
│   └── content_filter.py      # 内容安全过滤器
├── templates/            # 输出模板
├── examples/             # 示例音频
└── docs/                 # 文档
```

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

- 🐛 遇到问题？[提 Issue](https://github.com/你的用户名/book-to-audio/issues/new?template=bug_report.yml)
- 💡 有新想法？[提建议](https://github.com/你的用户名/book-to-audio/issues/new?template=feature_request.yml)
- 📋 想一起开发？看 [Roadmap](docs/ROADMAP.md) 找适合的议题

**维护说明**：本项目由 [@你的用户名](https://github.com/你的用户名) 一个人维护，通过 AI Agent 团队（Hermes/Codex）自动化处理 Issue 分类、Bug 修复和功能开发。回复速度取决于复杂度，感谢理解 🙏

---

## 📄 License

[MIT](LICENSE) © 2026 你的用户名

---

## ⭐ Star 支持

如果这个项目帮到了你，欢迎 Star ⭐ 和分享给需要的人！
