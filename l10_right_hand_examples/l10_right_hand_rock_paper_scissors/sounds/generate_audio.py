#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "edge-tts",
# ]
# ///
"""
音频预生成脚本 — 使用 edge-tts 生成石头剪刀布游戏所需的所有 WAV 文件。

运行方式:
    uv run generate_audio.py

生成的文件放在当前目录 (sounds/) 下。
"""

import asyncio
import sys
from pathlib import Path

import edge_tts

# 音频条目: (文件名, 文本内容, 语音模型)
AUDIO_ENTRIES = [
    # 中文倒计时 — 使用活泼有力的女声
    ("count_rock.wav",     "石头！",      "zh-CN-XiaoyiNeural"),
    ("count_scissors.wav", "剪刀！",      "zh-CN-XiaoyiNeural"),
    ("count_paper.wav",    "布！",        "zh-CN-XiaoyiNeural"),
    ("get_ready.wav",      "准备！",      "zh-CN-XiaoyiNeural"),

    # 英文结果播报 — AAA 格斗游戏热血风格
    ("you_win.wav",        "YOU WIN!",   "en-US-ChristopherNeural"),
    ("i_win.wav",          "I WIN!",     "en-US-ChristopherNeural"),
    ("tie.wav",            "TIE!",       "en-US-ChristopherNeural"),

    # 中文提示
    ("no_gesture.wav",     "没看清！",    "zh-CN-XiaoyiNeural"),
    ("play_again.wav",     "再来一局？",  "zh-CN-XiaoyiNeural"),
]

OUTPUT_DIR = Path(__file__).resolve().parent


async def generate_all():
    """生成所有音频文件。"""
    print(f"输出目录: {OUTPUT_DIR}")

    for filename, text, voice in AUDIO_ENTRIES:
        output_path = OUTPUT_DIR / filename
        print(f"  生成 {filename}: \"{text}\" ({voice})...", end=" ", flush=True)

        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")

    print("全部完成！")


def main():
    asyncio.run(generate_all())


if __name__ == "__main__":
    main()
