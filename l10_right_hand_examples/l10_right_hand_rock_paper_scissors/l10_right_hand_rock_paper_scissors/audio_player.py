"""
音频播放管理器 — 基于 pygame.mixer 的 WAV 文件播放。

所有音频文件通过 sounds/generate_audio.py 预生成，
运行时直接加载播放，零延迟、无网络依赖。
"""

import logging
from pathlib import Path

import pygame
import pygame.mixer

logger = logging.getLogger(__name__)

# 音频文件名映射
AUDIO_FILES = {
    "count_rock":     "count_rock.wav",
    "count_scissors": "count_scissors.wav",
    "count_paper":    "count_paper.wav",
    "get_ready":      "get_ready.wav",
    "you_win":        "you_win.wav",
    "i_win":          "i_win.wav",
    "tie":            "tie.wav",
    "no_gesture":     "no_gesture.wav",
    "play_again":     "play_again.wav",
}


class AudioPlayer:
    """管理所有游戏音频的加载和播放。"""

    def __init__(self, sounds_dir: str | None = None):
        if sounds_dir is None:
            self._sounds_dir = Path(__file__).resolve().parent.parent / "sounds"
        else:
            self._sounds_dir = Path(sounds_dir)

        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._initialized = False
        self._channel: pygame.mixer.Channel | None = None

    def init(self) -> bool:
        """初始化 pygame.mixer 并预加载所有音频文件。

        Returns:
            True 如果初始化成功且至少加载了一个音频文件。
        """
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
            self._channel = pygame.mixer.Channel(0)
            self._initialized = True
        except pygame.error as e:
            logger.warning("pygame.mixer 初始化失败: %s", e)
            return False

        loaded = 0
        for name, filename in AUDIO_FILES.items():
            filepath = self._sounds_dir / filename
            if filepath.exists():
                try:
                    self._sounds[name] = pygame.mixer.Sound(str(filepath))
                    loaded += 1
                except pygame.error as e:
                    logger.warning("加载音频失败 %s: %s", filepath, e)
            else:
                logger.warning("音频文件不存在: %s", filepath)

        if loaded == 0:
            logger.warning("未加载任何音频文件，语音播报将不可用")

        return loaded > 0

    @property
    def available(self) -> bool:
        """是否有可用的音频。"""
        return bool(self._sounds)

    def play(self, name: str, blocking: bool = False) -> None:
        """播放指定音频。

        Args:
            name: 音频名称（AUDIO_FILES 中的键）
            blocking: 是否阻塞等待播放完成
        """
        sound = self._sounds.get(name)
        if sound is None:
            logger.debug("音频未加载: %s", name)
            return

        if not self._initialized or self._channel is None:
            return

        self._channel.play(sound)
        if blocking:
            while self._channel.get_busy():
                pygame.time.wait(50)

    def is_playing(self) -> bool:
        """查询是否正在播放音频。"""
        if not self._initialized or self._channel is None:
            return False
        return self._channel.get_busy()

    def stop(self) -> None:
        """停止当前播放。"""
        if self._initialized and self._channel is not None:
            self._channel.stop()

    def cleanup(self) -> None:
        """释放资源。"""
        if self._initialized:
            self.stop()
            pygame.mixer.quit()
            self._initialized = False
