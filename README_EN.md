# 📚 Listen-Book — Turn books you never have time to read into 15-minute audio

> AI book summary audio generator Skill | All ages · All scenarios · Multiple voices
> Say one sentence → AI recommends → generates summary → converts to speech → listen!

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## 🎯 What problem does it solve?

- 📖 Bought books but no time to read them?
- 🏃 Want to listen to books while running/commuting, but audiobook apps just read the raw text?
- 👶 Want to tell stories to your kids, but too busy? Or want **mommy/daddy's own voice** to tell the story?
- 🧠 Forget what you listened to? Want notes?

**Listen-Book turns any book into a summary audio tailored to your current scenario — first segment in 30 seconds, listen while it generates.**

```
You: Summarize "Atomic Habits" for my run
AI: Recommend → Pick book → Generate summary → Voice output
```

---

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🎙️ **Voice Cloning** | Record 20s → mommy/daddy's voice tells stories to kids (free) |
| 🧒 **All Ages** | 0-3 years to 18+, 7 levels, content safety filter |
| 🎬 **Multiple Scenarios** | Commute / Running / Bedtime / Parent-child / Deep learning / Lunch break |
| 🎤 **Multiple Voices** | 5 built-in Chinese voices, free to switch |
| 📏 **Duration Control** | 3-min quick summary → 45-min deep dive |
| 🚀 **Streaming Delivery** | Hear chapter 1 in 30s, background continues, no waiting |
| 📝 **Notes Output** | Audio + key notes auto-saved to Obsidian |
| 🔍 **Smart Recommendation** | Don't know what to read? Say a topic, AI recommends books + highlights |
| 🛡️ **Content Safety** | Kids/teens mode auto-filters violence, horror, adult content |
| ⚖️ **Copyright Compliant** | Summary = "seeding" (not piracy), sources from public info/public domain/user's own books |

---

## 🚀 Quick Start

### 1. Install

```bash
# Hermes Agent users
git clone https://github.com/QINGcha7911/listen-book.git ~/.hermes/skills/productivity/listen-book

# Dependencies
pip install edge-tts mutagen
sudo apt install ffmpeg   # macOS: brew install ffmpeg
```

### 2. Use (just say one sentence)

```text
Summarize "Atomic Habits" for my run
Summarize "The Little Prince" for my 6-year-old, parent-child mode
I want to listen to books about discipline
Full summary of "Steve Jobs", 45 minutes
Use my voice to tell stories to my kids (attach a 20s recording)
```

### 3. (Optional) Configure

```yaml
# config.yaml
age_group: adult        # toddler/preschool/primary_lower/primary_upper/middle_school/high_school/adult
scene: commute          # commute/running/bedtime/parent_child/deep_learning/lunch_break
depth: standard         # quick/standard/deep/full
voice: auto             # auto/xiaoshuang/xiaoxiao/yunxi/yunjian/yunyang
```

> 💡 90% of users don't need to change config — works out of the box.

---

## 🎬 Real Outputs (Video Summaries)

> All items below were **actually generated & delivered** with this project (not demo assets), including full scripts, videos & copy.

| Work | Length | Voice | Visual Theme | Script |
|------|--------|-------|--------------|--------|
| ⚔️ [WW2 History](examples/screenshots/ww2_video.png) | 10min | Yunyang·Epic male | War epic (soldier silhouettes/snowfield/sea) | [Script](examples/scripts/二战战史_讲书稿.md) |
| 🏔️ [Winter Pasture](examples/screenshots/dongmuchang_video.png) | 10min | Xiaoxiao·Warm female | Snow pasture/nomadic life | [Script](examples/scripts/冬牧场_讲书稿.md) |
| 🌌 [Norwegian Polar Night](examples/screenshots/norway_video.png) | 10min | Xiaoxiao·Soft female | Arctic (aurora/snowfield/blue hour) | [Script](examples/scripts/挪威极夜_讲书稿.md) |
| 🦈 [Billions: Hunting the Wall Street Shark](examples/screenshots/yiwan_video.png) | 10min | Yunjian·Calm male | Wall Street finance (NYSE/trading screens) | [Script](examples/scripts/亿万围剿_讲书稿.md) |
| 🍲 [Slow Life by Wang Zengqi](examples/screenshots/zhishenshinei_video.png) | 10min | Xiaoxiao·Warm female | Warm home/life aesthetics | [Script](examples/scripts/慢煮生活_讲书稿.md) |

### 🎥 Video Pipeline (v2.2.0+)
- 1080×1920 vertical + Ken Burns motion + crossfade
- **19 real-scene theme libraries**: arctic/finance/ww2/pasture/desert/starry/ocean/forest/warm_home…
- Quote subtitles auto-extracted from 【金句】 markers
- Chapter title overlays + cover frame + AI-generated content badge (compliant)

### 🗓️ Changelog

| Date | Version | Content |
|------|---------|---------|
| 2026-08-16 | v2.2.1 | 🚀 Perf fix: zoompan redundant frames eliminated (175×175→213); 7 bug fixes driven by independent AI review |
| 2026-08-16 | v2.2.0 | ✨ 2 new themes: `arctic` & `finance`; 19 themes total |
| 2026-08-14 | v2.2.0 | 🎬 Video composer GA: quote subtitles, chapter overlays, cover frame, AI badge |

---

## 📖 Documentation

- [Configuration](config.yaml)
- [Roadmap](docs/ROADMAP.md)
- [Age groups & content safety](SKILL.md)

---

## 🏗️ Project Structure

```
listen-book/
├── SKILL.md              # Main skill file (all config)
├── config.yaml           # Default config
├── prompts/              # Age-group prompt templates (children 4 levels + teen 2 levels)
├── scripts/
│   ├── book_info.py          # Book info fetching (Douban/Wikipedia/Gutenberg, all legal)
│   ├── streaming_pipeline.py # Streaming pipeline (segmentation + chapter markers + batch)
│   ├── content_filter.py     # Content safety filter (kids/adult dual mode)
│   └── cache_manager.py      # 3-level cache (L1 script/L2 segments/L3 final)
├── templates/            # Output templates
└── examples/             # Sample audio
```

---

## 🤝 Contributing

Issues and PRs welcome!

- 🐛 Found a bug? [Open an Issue](https://github.com/QINGcha7911/listen-book/issues/new?template=bug_report.yml)
- 💡 Have an idea? [Suggest a feature](https://github.com/QINGcha7911/listen-book/issues/new?template=feature_request.yml)
- 📋 Want to help develop? See [Roadmap](docs/ROADMAP.md)

---

## 📄 License

[MIT](LICENSE) © 2026 QINGcha7911

---

## ⭐ Support

If this project helps you, please ⭐ Star and share it!
