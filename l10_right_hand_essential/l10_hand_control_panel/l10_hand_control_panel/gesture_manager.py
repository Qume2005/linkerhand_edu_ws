#!/usr/bin/env python3
"""
手势与序列数据管理器 — 纯 Python，无 Qt 依赖。

职责:
- 从 JSON 文件加载/保存自定义手势和序列数据
- 提供自定义手势 CRUD 接口
- 提供序列 CRUD 接口
- 解析手势名称（内置预设 + 自定义）
- 数据完整性验证
- 变更事件通知
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence


class GestureManager:
    """手势与序列数据管理器。

    使用 JSON 文件进行持久化，文件位置为:
    Linux:   ~/.config/l10_hand_control_panel/gestures.json
    macOS:   ~/Library/Application Support/l10_hand_control_panel/gestures.json
    Windows: %APPDATA%/l10_hand_control_panel/gestures.json

    内置手势名称只读，不可通过本管理器修改。
    """

    SCHEMA_VERSION = "1.0"
    CONFIG_DIR_NAME = "l10_hand_control_panel"
    CONFIG_FILE_NAME = "gestures.json"

    BUILTIN_GESTURE_NAMES: frozenset = frozenset({
        "open", "fist", "ok", "pinch", "point", "peace", "thumbs_up",
    })

    def __init__(self) -> None:
        self._custom_gestures: dict[str, dict[str, Any]] = {}
        self._sequences: dict[str, dict[str, Any]] = {}
        self._config_path: str = ""
        self._change_callbacks: list[Callable[[str, str], None]] = []

    # ── 生命周期 ──────────────────────────────────────────────────────

    def load(self) -> None:
        """从 JSON 文件加载数据。文件不存在则初始化为空。"""
        self._config_path = self._get_config_path()
        if not os.path.exists(self._config_path):
            self._custom_gestures = {}
            self._sequences = {}
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            import warnings
            warnings.warn(f"手势配置文件损坏，已初始化为空: {exc}")
            self._custom_gestures = {}
            self._sequences = {}
            return

        if not isinstance(data, dict):
            warnings.warn("手势配置文件格式错误，已初始化为空")
            self._custom_gestures = {}
            self._sequences = {}
            return

        self._custom_gestures = data.get("custom_gestures", {}) or {}
        self._sequences = data.get("sequences", {}) or {}

    def save(self) -> None:
        """原子写入 JSON 文件（写临时文件 + rename），防止损坏。"""
        self._config_path = self._get_config_path()
        config_dir = os.path.dirname(self._config_path)
        os.makedirs(config_dir, exist_ok=True)

        tmp_path = self._config_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._serialize(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._config_path)
        except OSError as exc:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise IOError(f"保存手势配置失败: {exc}") from exc

    def _get_config_path(self) -> str:
        """返回跨平台的配置目录路径，创建目录（如不存在）。"""
        config_dir = Path.home() / ".config" / self.CONFIG_DIR_NAME
        config_dir.mkdir(parents=True, exist_ok=True)
        return str(config_dir / self.CONFIG_FILE_NAME)

    def _serialize(self) -> dict[str, Any]:
        """将内部状态序列化为 JSON 可写结构。"""
        return {
            "version": self.SCHEMA_VERSION,
            "custom_gestures": self._custom_gestures,
            "sequences": self._sequences,
        }

    # ── 事件通知 ──────────────────────────────────────────────────────

    def on_changed(self, callback: Callable[[str, str], None]) -> None:
        """注册变更回调。回调签名: callback(change_type, key)。

        change_type 可选值: gesture_created, gesture_updated, gesture_deleted,
        sequence_created, sequence_updated, sequence_deleted
        """
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    def _notify_changed(self, change_type: str, key: str) -> None:
        """通知所有注册的变更回调。"""
        for cb in self._change_callbacks:
            try:
                cb(change_type, key)
            except Exception:
                pass

    # ── 内置手势访问 ──────────────────────────────────────────────────

    def _get_builtin_gesture(self, name: str) -> tuple[int, ...] | None:
        """从 linker_hand_description 获取内置手势 DOF 值。"""
        try:
            from linker_hand_description.gesture_presets import GESTURE_PRESETS
            return GESTURE_PRESETS.get(name)
        except Exception:
            return None

    # ── 自定义手势 CRUD ──────────────────────────────────────────────

    def get_custom_gesture(self, name: str) -> dict[str, Any] | None:
        """获取自定义手势数据，返回 None 如果不存在。"""
        return self._custom_gestures.get(name)

    def list_custom_gestures(self) -> dict[str, dict[str, Any]]:
        """返回所有自定义手势的浅拷贝 {name: data}。"""
        return dict(self._custom_gestures)

    def create_custom_gesture(
        self,
        name: str,
        dof_values: Sequence[int],
        description: str = "",
    ) -> dict[str, Any]:
        """创建自定义手势。

        Args:
            name: 手势名称，不能与内置或已有自定义手势重名。
            dof_values: 10 个 DOF 值（整数 0-255）。
            description: 可选描述。

        Returns:
            创建的手势数据字典。

        Raises:
            ValueError: 名称不合法或 DOF 值不合法。
        """
        valid, err = self.validate_gesture_name(name)
        if not valid:
            raise ValueError(err)

        if len(dof_values) != 10:
            raise ValueError("DOF 值必须为 10 个元素的列表")

        clamped = [max(0, min(255, int(v))) for v in dof_values]
        now = datetime.now().isoformat()

        data = {
            "dof_values": clamped,
            "description": description,
            "created_at": now,
            "updated_at": now,
        }

        self._custom_gestures[name] = data
        self.save()
        self._notify_changed("gesture_created", name)
        return dict(data)

    def update_custom_gesture(
        self,
        name: str,
        dof_values: Sequence[int] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新自定义手势的 DOF 值或描述。

        Args:
            name: 要更新的手势名称。
            dof_values: 新的 DOF 值列表（可选，不修改则不传）。
            description: 新的描述文本（可选，不修改则不传）。

        Returns:
            更新后的手势数据字典。

        Raises:
            KeyError: 手势不存在。
            ValueError: DOF 值不合法。
        """
        if name not in self._custom_gestures:
            raise KeyError(f"自定义手势 '{name}' 不存在")

        data = self._custom_gestures[name]

        if dof_values is not None:
            if len(dof_values) != 10:
                raise ValueError("DOF 值必须为 10 个元素的列表")
            data["dof_values"] = [max(0, min(255, int(v))) for v in dof_values]

        if description is not None:
            data["description"] = description

        data["updated_at"] = datetime.now().isoformat()

        self.save()
        self._notify_changed("gesture_updated", name)
        return dict(data)

    def delete_custom_gesture(self, name: str) -> bool:
        """删除自定义手势。

        Returns:
            True 如果成功删除，False 如果不存在。
        """
        if name not in self._custom_gestures:
            return False

        del self._custom_gestures[name]
        self.save()
        self._notify_changed("gesture_deleted", name)
        return True

    def rename_custom_gesture(self, old_name: str, new_name: str) -> bool:
        """重命名自定义手势，同时更新所有引用它的序列步骤。

        Returns:
            True 如果成功，False 如果旧名称不存在或新名称不合法。
        """
        if old_name not in self._custom_gestures:
            return False

        valid, err = self.validate_gesture_name(new_name)
        if not valid:
            raise ValueError(err)

        if old_name == new_name:
            return True

        self._custom_gestures[new_name] = self._custom_gestures.pop(old_name)
        self._custom_gestures[new_name]["updated_at"] = datetime.now().isoformat()

        # 更新引用该手势的序列步骤
        for seq_data in self._sequences.values():
            for step in seq_data.get("steps", []):
                if step.get("gesture_name") == old_name:
                    step["gesture_name"] = new_name
            if "updated_at" in seq_data:
                seq_data["updated_at"] = datetime.now().isoformat()

        self.save()
        self._notify_changed("gesture_deleted", old_name)
        self._notify_changed("gesture_created", new_name)
        return True

    # ── 序列 CRUD ─────────────────────────────────────────────────────

    def get_sequence(self, name: str) -> dict[str, Any] | None:
        """获取序列数据，返回 None 如果不存在。"""
        return self._sequences.get(name)

    def list_sequences(self) -> dict[str, dict[str, Any]]:
        """返回所有序列的浅拷贝 {name: data}。"""
        return dict(self._sequences)

    def create_sequence(
        self,
        name: str,
        steps: list[dict[str, Any]],
        loop: bool = False,
    ) -> dict[str, Any]:
        """创建手势序列。

        Args:
            name: 序列名称。
            steps: 步骤列表，每项格式: {"gesture_name": str, "duration": float, "delay_after": float}
            loop: 是否循环播放。

        Returns:
            创建的序列数据字典。

        Raises:
            ValueError: 名称或步骤不合法。
        """
        if not name:
            raise ValueError("序列名称不能为空")

        valid, err = self.validate_sequence_steps(steps)
        if not valid:
            raise ValueError(err)

        now = datetime.now().isoformat()
        data = {
            "steps": [dict(s) for s in steps],
            "loop": bool(loop),
            "created_at": now,
            "updated_at": now,
        }

        self._sequences[name] = data
        self.save()
        self._notify_changed("sequence_created", name)
        return dict(data)

    def update_sequence(
        self,
        name: str,
        steps: list[dict[str, Any]] | None = None,
        loop: bool | None = None,
    ) -> dict[str, Any]:
        """更新序列的步骤或循环设置。

        Args:
            name: 序列名称。
            steps: 新的步骤列表（可选）。
            loop: 新的循环设置（可选）。

        Returns:
            更新后的序列数据字典。

        Raises:
            KeyError: 序列不存在。
            ValueError: 步骤不合法。
        """
        if name not in self._sequences:
            raise KeyError(f"序列 '{name}' 不存在")

        data = self._sequences[name]

        if steps is not None:
            valid, err = self.validate_sequence_steps(steps)
            if not valid:
                raise ValueError(err)
            data["steps"] = [dict(s) for s in steps]

        if loop is not None:
            data["loop"] = bool(loop)

        data["updated_at"] = datetime.now().isoformat()

        self.save()
        self._notify_changed("sequence_updated", name)
        return dict(data)

    def delete_sequence(self, name: str) -> bool:
        """删除序列。

        Returns:
            True 如果成功删除，False 如果不存在。
        """
        if name not in self._sequences:
            return False

        del self._sequences[name]
        self.save()
        self._notify_changed("sequence_deleted", name)
        return True

    # ── 手势解析 ──────────────────────────────────────────────────────

    def resolve_gesture(self, name: str) -> tuple[int, ...] | None:
        """解析手势名称为 DOF 值元组。

        查找顺序: 自定义手势 → 内置手势。

        Returns:
            10 元素 DOF 值元组，或 None 如果未找到。
        """
        # 先查自定义
        custom = self._custom_gestures.get(name)
        if custom is not None:
            dof = custom.get("dof_values", [])
            if len(dof) == 10:
                return tuple(dof)

        # 再查内置
        builtin = self._get_builtin_gesture(name)
        if builtin is not None:
            return builtin

        return None

    def is_builtin_gesture(self, name: str) -> bool:
        """检查名称是否为内置手势。"""
        return name in self.BUILTIN_GESTURE_NAMES

    def is_custom_gesture(self, name: str) -> bool:
        """检查名称是否为自定义手势。"""
        return name in self._custom_gestures

    def get_all_gesture_names(self) -> list[str]:
        """返回所有可用手势名称（内置 + 自定义），内置在前。"""
        names = list(self.BUILTIN_GESTURE_NAMES)
        names.extend(sorted(self._custom_gestures.keys()))
        return names

    # ── 验证 ──────────────────────────────────────────────────────────

    def validate_gesture_name(self, name: str) -> tuple[bool, str]:
        """验证手势名称是否合法。

        Returns:
            (是否合法, 错误信息)。
        """
        if not name or not name.strip():
            return False, "手势名称不能为空"

        if name in self.BUILTIN_GESTURE_NAMES:
            return False, f"'{name}' 是内置手势名称，请使用其他名称"

        if name in self._custom_gestures:
            return False, f"自定义手势 '{name}' 已存在"

        return True, ""

    def validate_sequence_steps(
        self, steps: list[dict[str, Any]]
    ) -> tuple[bool, str]:
        """验证序列步骤的完整性。

        Returns:
            (是否合法, 错误信息)。
        """
        if not steps:
            return False, "序列至少需要 1 个步骤"

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                return False, f"步骤 {i + 1} 格式错误"

            gesture_name = step.get("gesture_name", "")
            if not gesture_name:
                return False, f"步骤 {i + 1} 缺少手势名称"

            if self.resolve_gesture(gesture_name) is None:
                return False, (
                    f"步骤 {i + 1} 的手势 '{gesture_name}' 不存在"
                )

            duration = step.get("duration")
            if duration is None or not isinstance(duration, (int, float)):
                return False, f"步骤 {i + 1} 的持续时间必须为数字"
            if duration <= 0:
                return False, f"步骤 {i + 1} 的持续时间必须大于 0"

            delay = step.get("delay_after", 0)
            if delay is not None and (not isinstance(delay, (int, float)) or delay < 0):
                return False, f"步骤 {i + 1} 的延迟时间不能为负数"

        return True, ""

    def get_invalid_sequence_steps(self, name: str) -> list[int]:
        """返回序列中引用不存在手势的步骤索引列表（0-based）。"""
        seq = self._sequences.get(name)
        if not seq:
            return []

        invalid = []
        for i, step in enumerate(seq.get("steps", [])):
            if self.resolve_gesture(step.get("gesture_name", "")) is None:
                invalid.append(i)
        return invalid
