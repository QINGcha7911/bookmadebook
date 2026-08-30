#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agnes_intro.py — bookmadebook 60 秒开篇集成（Agnes 免费 AI 视频）
流程：口播文案 → 场景拆分 → Agnes 逐段生成（0元）→ 拼接+混口播 → 60秒竖版
用法：python agnes_intro.py "书名" "口播文本文件" "输出目录"
"""
import os, sys, json, time, subprocess, re, urllib.request

BASE = "http://localhost:8765"
SCENE_DURATION = 10  # 每段秒数（Agnes 支持 5/10/15/18/20）
TARGET = 60

def submit_simple(prompt: str, duration: int = SCENE_DURATION) -> str:
    """提交 Agnes simple 任务（multipart/form-data），返回 task_id"""
    import requests
    resp = requests.post(f"{BASE}/api/tasks/simple", timeout=30, files={"x": ("", "")},
                         data={"prompt": prompt, "mode": "t2v",
                               "duration": duration,
                               "video_width": 768, "video_height": 1152,
                               "negative_prompt": make_negative(),
                               "audio_enabled": False, "subtitle_enabled": False})
    resp.raise_for_status()
    return resp.json().get("task_id") or resp.json().get("id")

def wait_task(task_id: str, timeout: int = 300) -> dict:
    """轮询任务直到完成"""
    for _ in range(timeout // 5):
        time.sleep(5)
        try:
            d = json.loads(urllib.request.urlopen(f"{BASE}/api/tasks/{task_id}", timeout=10).read())
            st = d.get("status")
            if st == "completed":
                return d
            if st in ("failed", "error", "stopped"):
                raise RuntimeError(f"任务失败: {d.get('error_traceback', '')[:200]}")
        except Exception as e:
            if "失败" in str(e):
                raise
    raise TimeoutError(f"任务 {task_id} 超时")

def scenes_from_script(script: str) -> list:
    """按口播内容拆场景 prompt（规则版——适配故宫南迁式文案）"""
    # 按句号/感叹号切分，每场景 1-2 句
    sentences = re.split(r'[。！？]', script)
    scenes = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        buf += s + "。"
        if len(buf) >= 40:
            scenes.append(buf)
            buf = ""
    if buf:
        scenes.append(buf)
    return scenes[:12]

def make_prompt(scene_text: str, book_title: str) -> str:
    """场景文案 → Agnes 视频 prompt（纯场景·无人物·远景）"""
    return (f"1930年代中国民国时期历史场景，纯场景空镜，远景大全景，"
            f"彩色老电影质感，柔和自然光线，画面内容：{scene_text[:50]}。"
            f"《{book_title}》历史叙事，庄重，电影感，无任何人物，无生物，"
            f"无文字，无字幕，无标语，无招牌文字。"
            f"NO TEXT, NO CAPTION, NO SUBTITLE, NO WATERMARK, NO SIGN, "
            f"NO LETTERS, NO WORDS, CLEAN IMAGE WITHOUT ANY WRITING")

def make_negative() -> str:
    """负面 prompt：禁止人物+AI假感+恐怖感"""
    return ("人物，人，面孔，人脸，肖像，人群，剪影人影，动物，生物，"
            "黑白，阴森，恐怖，惊悚，扭曲，畸形，恐怖谷，"
            "巨大月亮，卡通，动漫，超现实，现代元素，文字乱码，"
            "塑料质感，高饱和，鲜艳刺眼")

def main():
    if len(sys.argv) < 4:
        print("用法: python agnes_intro.py 书名 口播文件 输出目录")
        sys.exit(1)
    title, script_file, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    script = open(script_file, encoding="utf-8").read()
    os.makedirs(out_dir, exist_ok=True)

    scenes = scenes_from_script(script)
    print(f"场景数: {len(scenes)}")
    vids = []
    for i, sc in enumerate(scenes):
        prompt = make_prompt(sc, title)
        print(f"[{i+1}/{len(scenes)}] 提交: {prompt[:50]}...")
        tid = submit_simple(prompt)
        d = wait_task(tid)
        fv = d.get("final_video_file")
        if not fv or not os.path.exists(fv):
            print(f"  ⚠️ 无产物，跳过")
            continue
        dest = os.path.join(out_dir, f"scene_{i+1:02d}.mp4")
        import shutil; shutil.copy(fv, dest)
        vids.append(dest)
        print(f"  ✅ 完成 -> {dest}")

    if not vids:
        print("❌ 无视频生成"); sys.exit(2)

    # 拼接（重编码统一格式）
    listf = os.path.join(out_dir, "concat.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for v in vids:
            f.write(f"file '{os.path.abspath(v)}'\n")
    concat_out = os.path.join(out_dir, "scenes_concat.mp4")
    subprocess.run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",listf,
                    "-c:v","libx264","-crf","23","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",concat_out],
                   check=True)
    print(f"拼接完成: {concat_out}")

if __name__ == "__main__":
    main()
