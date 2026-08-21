# 声音设计 API（阿里百炼 Qwen3-TTS Voice Design）

> 2026-08-21 接入，用户验收通过。用**文字描述**生成任意中文音色，无需音频样本。

## 原理

```
文字描述(voice_prompt) → qwen-voice-design API → 专属音色 voice ID（长期有效）
→ 之后任何文本用 voice ID 合成语音
```

- 端点（北京地域）：`https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization`
- 合成端点（非流式）：`https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`
- key：`DASHSCOPE_API_KEY`（~/.hermes/.env 中真实 key sk-2407aa5a...；config.yaml custom_providers 中 Kimi 系列复用同 key）
- 模型：create 用 `qwen-voice-design`，target_model/synth 用 `qwen3-tts-vd-2026-01-26`
- 音色默认长期有效，1 年未使用自动清理

## 已创建音色（2026-08-21，用户验收）

| 用途 | 名称 | voice ID | 描述要点 |
|------|------|----------|---------|
| 📜 历史传记 | hist_deep_male | `qwen-tts-vd-hist_deep_male-voice-20260821204552033-d7bc`（最新的）| 沉稳厚重老年男声，低沉沧桑叙述感 ✅用户确认 |
| 🌸 散文治愈 | prose_female | `qwen-tts-vd-prose_female-voice-20260821210009623-0ed8` | 温柔治愈年轻女声（被沙哑版取代）|
| 🎙️ 沙哑女声 | husky_female | `qwen-tts-vd-husky_female-voice-20260821211048195-2799` | 轻沙哑深夜电台感 |
| 🎙️ 沙哑女声2 | husky_female2 | `qwen-tts-vd-husky_female2-voice-20260821211251791-3d27` | 明显烟嗓颗粒感，**用户当前选定** ✅ |
| 🧒 儿童故事 | design_kid | `qwen-tts-vd-design_kid-voice-20260821205612330-e42c` | 活泼亲切童声 ✅用户确认 |

## CLI 用法

```bash
# 设计新音色
DASHSCOPE_API_KEY=xxx python3 scripts/voice_design.py create \
  --name my_voice --prompt "温柔抒情的女声，带一点沙哑的烟嗓质感..." \
  --preview "预览文本" --out preview.wav

# 用音色合成语音
DASHSCOPE_API_KEY=xxx python3 scripts/voice_design.py synth \
  --voice <VOICE_ID> --text "要合成的文本" --out out.wav

# 列出所有音色
python3 scripts/voice_design.py list

# 删除音色
python3 scripts/voice_design.py delete --voice <VOICE_ID>
```

## voice_prompt 编写要点

- 中文描述，Qwen3-TTS 上限 2048 字符
- 越具体越好：性别/年龄/音色特质（沙哑、磁性、清亮）/语调/情绪/适用场景
- 参考已验收的描述：
  - 历史男声："沉稳厚重的老年男声，语气低沉有力，带有历史的沧桑感与叙述感，适合历史传记讲述"
  - 沙哑女声："明显的沙哑烟嗓女声，嗓音低沉带有颗粒感，像经历过沧桑的女歌手，慵懒磁性，情感饱满，说话时带着一点点气声和沙哑的摩擦感，深夜电台感十足，适合抒情散文和治愈系小说"
- 不满意就改描述重新 create（每次生成新 voice ID），试听验收 = 用户耳朵

## 与 edge-tts 的关系

- edge-tts（免费，14 中文声）：默认兜底，跑量低成本
- 声音设计 API（百炼，按量计费）：用户点名的精读/重点内容用设计音色
- 视频流水线 streaming_pipeline.py 的 voice 参数两者通用（传 voice ID 或 edge 声名均可，需在 TTS 层适配）
