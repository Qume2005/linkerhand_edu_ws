#!/usr/bin/env python3
"""gesture_manager.py 数据层单元测试。

纯 Python 测试，无 Qt 依赖。
Mock 策略: mock linker_hand_description 以提供内置手势预设。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# 内置手势真实数据（用于 mock GESTURE_PRESETS.get()）
GESTURE_PRESETS_REAL: dict[str, tuple] = {
    "open":      (255, 255, 255, 255, 255, 255, 255, 255, 255, 255),
    "fist":      (122, 145,   0,   0,   0,   0,   0,   0,   0,  92),
    "ok":        (108,  56, 118, 255, 255, 255, 255, 255, 255, 234),
    "pinch":     (108,  56, 118,   0,   0,   0, 132,   0,   0, 234),
    "point":     (116, 142, 255,   0,   0,   0,  49,  36,  81,  50),
    "peace":     ( 96,  48, 255, 255,   0,   0, 255, 255, 255,  89),
    "thumbs_up": (255, 255,   0,   0,   0,   0,   0,   0,   0, 255),
}

# ── Mock 依赖（必须在 import gesture_manager 之前）───────────────
# 强制覆盖（test_gesture_dialogs.py 可能已设置不同值）
_mock_lhd = MagicMock()
sys.modules['linker_hand_description'] = _mock_lhd
_mock_presets = MagicMock()
# 让 GESTURE_PRESETS 成为一个真实 dict 的 mock
# 这样 GESTURE_PRESETS.get("nonexist") 返回 None 而不是 MagicMock
_mock_presets.GESTURE_PRESETS = GESTURE_PRESETS_REAL
sys.modules['linker_hand_description.gesture_presets'] = _mock_presets

from l10_hand_control_panel.gesture_manager import GestureManager


# ── 测试辅助 ────────────────────────────────────────────────────────

class _TmpDirTestCase(unittest.TestCase):
    """为每个测试方法提供临时目录作为配置目录。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)


def _make_manager(tmp_home=None) -> GestureManager:
    """创建已初始化的 GestureManager（load 已调用）。"""
    gm = GestureManager()
    if tmp_home is not None:
        with patch.object(gm, '_get_config_path',
                          return_value=os.path.join(tmp_home,
                                                    ".config",
                                                    GestureManager.CONFIG_DIR_NAME,
                                                    GestureManager.CONFIG_FILE_NAME)):
            gm.load()
    else:
        gm.load()
    return gm


# ──────────────────────────────────────────────────────────────────
# 1. 生命周期与持久化
# ──────────────────────────────────────────────────────────────────

class TestGestureManagerLifecycle(unittest.TestCase):
    """GestureManager 生命周期和文件持久化。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def test_load_missing_file_creates_empty(self):
        """文件不存在时 load() 不崩溃，状态为空。"""
        gm = _make_manager(self._tmpdir)
        self.assertEqual(gm.list_custom_gestures(), {})
        self.assertEqual(gm.list_sequences(), {})

    def test_save_creates_file(self):
        """save() 创建配置文件。"""
        gm = _make_manager(self._tmpdir)
        gm.create_custom_gesture("test", [128] * 10)

        config_dir = os.path.join(
            self._tmpdir, ".config", GestureManager.CONFIG_DIR_NAME
        )
        config_file = os.path.join(config_dir, GestureManager.CONFIG_FILE_NAME)
        self.assertTrue(os.path.exists(config_file))

    def test_round_trip_save_and_reload(self):
        """保存后重新加载，数据保持一致。"""
        gm = _make_manager(self._tmpdir)
        gm.create_custom_gesture("round_trip", [100, 200] + [128] * 8,
                                 description="test")
        gm.create_sequence("seq_rt", [
            {"gesture_name": "round_trip", "duration": 1.0, "delay_after": 0.5}
        ], loop=True)

        # 重新加载
        gm2 = _make_manager(self._tmpdir)
        self.assertIn("round_trip", gm2.list_custom_gestures())
        self.assertIn("seq_rt", gm2.list_sequences())

        data = gm2.get_custom_gesture("round_trip")
        self.assertEqual(data["dof_values"][0], 100)
        self.assertEqual(data["dof_values"][1], 200)
        self.assertEqual(data["description"], "test")

        seq = gm2.get_sequence("seq_rt")
        self.assertTrue(seq["loop"])
        self.assertEqual(len(seq["steps"]), 1)

    def test_atomic_write_no_tmp_file_left(self):
        """原子写入成功后，临时文件不存在。"""
        gm = _make_manager(self._tmpdir)
        gm.create_custom_gesture("atomic", [128] * 10)

        config_dir = os.path.join(
            self._tmpdir, ".config", GestureManager.CONFIG_DIR_NAME
        )
        tmp_file = os.path.join(config_dir, GestureManager.CONFIG_FILE_NAME + ".tmp")
        self.assertFalse(os.path.exists(tmp_file))

    def test_config_dir_created(self):
        """配置目录在首次 save 时自动创建。"""
        with patch.object(GestureManager, '_get_config_path') as mock_path:
            config_dir = os.path.join(
                self._tmpdir, ".config", GestureManager.CONFIG_DIR_NAME
            )
            mock_path.return_value = os.path.join(config_dir, GestureManager.CONFIG_FILE_NAME)
            gm = GestureManager()
            gm.load()
            gm.create_custom_gesture("dir_test", [128] * 10)

        self.assertTrue(os.path.isdir(config_dir))

    def test_load_corrupt_json_creates_empty(self):
        """加载损坏的 JSON 时不崩溃，状态初始化为空。"""
        config_dir = os.path.join(
            self._tmpdir, ".config", GestureManager.CONFIG_DIR_NAME
        )
        os.makedirs(config_dir, exist_ok=True)
        config_file = os.path.join(config_dir, GestureManager.CONFIG_FILE_NAME)
        with open(config_file, "w") as f:
            f.write("{NOT VALID JSON!!!")

        gm = _make_manager(self._tmpdir)
        self.assertEqual(gm.list_custom_gestures(), {})
        self.assertEqual(gm.list_sequences(), {})

    def test_schema_version_in_file(self):
        """保存的文件包含 schema version 字段。"""
        gm = _make_manager(self._tmpdir)
        gm.create_custom_gesture("vcheck", [128] * 10)

        config_dir = os.path.join(
            self._tmpdir, ".config", GestureManager.CONFIG_DIR_NAME
        )
        config_file = os.path.join(config_dir, GestureManager.CONFIG_FILE_NAME)
        with open(config_file, "r") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "1.0")


# ──────────────────────────────────────────────────────────────────
# 2. 自定义手势 CRUD
# ──────────────────────────────────────────────────────────────────

class TestCustomGestureCRUD(unittest.TestCase):
    """自定义手势的增删改查。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir
        self.gm = _make_manager(self._tmpdir)

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def test_create_valid_gesture(self):
        """合法创建自定义手势。"""
        data = self.gm.create_custom_gesture("my_gesture", [100] * 10)
        self.assertEqual(data["dof_values"], [100] * 10)
        self.assertIn("my_gesture", self.gm.list_custom_gestures())

    def test_create_with_description(self):
        """创建时包含描述。"""
        data = self.gm.create_custom_gesture(
            "desc_test", [50] * 10, description="测试描述"
        )
        self.assertEqual(data["description"], "测试描述")

    def test_create_duplicate_name_raises(self):
        """重复名称创建应失败。"""
        self.gm.create_custom_gesture("dup", [100] * 10)
        with self.assertRaises(ValueError):
            self.gm.create_custom_gesture("dup", [200] * 10)

    def test_create_builtin_name_raises(self):
        """使用内置名称创建应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_custom_gesture("fist", [100] * 10)

    def test_create_empty_name_raises(self):
        """空名称创建应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_custom_gesture("", [100] * 10)

    def test_create_invalid_dof_count_raises(self):
        """DOF 值数量不为 10 应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_custom_gesture("bad_dof", [100] * 5)

    def test_create_clamps_dof_values(self):
        """DOF 值超出范围时自动钳制到 0-255。"""
        data = self.gm.create_custom_gesture(
            "clamp", [-10, 300] + [128] * 8
        )
        self.assertEqual(data["dof_values"][0], 0)
        self.assertEqual(data["dof_values"][1], 255)

    def test_update_dof_values(self):
        """更新 DOF 值。"""
        self.gm.create_custom_gesture("upd", [100] * 10)
        data = self.gm.update_custom_gesture("upd", [200] * 10)
        self.assertEqual(data["dof_values"], [200] * 10)

    def test_update_description(self):
        """更新描述。"""
        self.gm.create_custom_gesture("upd_desc", [100] * 10)
        data = self.gm.update_custom_gesture("upd_desc",
                                              description="new desc")
        self.assertEqual(data["description"], "new desc")

    def test_update_non_existing_raises(self):
        """更新不存在的手势应失败。"""
        with self.assertRaises(KeyError):
            self.gm.update_custom_gesture("nonexist", [100] * 10)

    def test_delete_existing_returns_true(self):
        """删除存在的手势返回 True。"""
        self.gm.create_custom_gesture("del_me", [100] * 10)
        result = self.gm.delete_custom_gesture("del_me")
        self.assertTrue(result)
        self.assertNotIn("del_me", self.gm.list_custom_gestures())

    def test_delete_non_existing_returns_false(self):
        """删除不存在的手势返回 False。"""
        result = self.gm.delete_custom_gesture("nonexist")
        self.assertFalse(result)

    def test_get_custom_gesture(self):
        """get_custom_gesture 正确返回数据。"""
        self.gm.create_custom_gesture("get_test", [50] * 10)
        data = self.gm.get_custom_gesture("get_test")
        self.assertIsNotNone(data)
        self.assertEqual(data["dof_values"], [50] * 10)

    def test_get_custom_gesture_nonexist(self):
        """get_custom_gesture 对不存在的名称返回 None。"""
        self.assertIsNone(self.gm.get_custom_gesture("nonexist"))

    def test_list_custom_gestures_returns_copy(self):
        """list_custom_gestures 返回浅拷贝，顶层 dict 独立。"""
        self.gm.create_custom_gesture("copy_test", [100] * 10)
        result = self.gm.list_custom_gestures()
        # 浅拷贝: 顶层 dict 独立
        self.assertIsNot(result, self.gm._custom_gestures)
        # 添加新 key 不影响内部
        result["new_key"] = {}
        self.assertNotIn("new_key", self.gm.list_custom_gestures())

    def test_rename_custom_gesture(self):
        """重命名自定义手势。"""
        self.gm.create_custom_gesture("old_name", [100] * 10)
        result = self.gm.rename_custom_gesture("old_name", "new_name")
        self.assertTrue(result)
        self.assertIsNone(self.gm.get_custom_gesture("old_name"))
        self.assertIsNotNone(self.gm.get_custom_gesture("new_name"))

    def test_rename_updates_sequence_references(self):
        """重命名手势后，引用它的序列步骤同步更新。"""
        self.gm.create_custom_gesture("wave", [255] * 10)
        self.gm.create_sequence("greet", [
            {"gesture_name": "wave", "duration": 1.0, "delay_after": 0.0}
        ])
        self.gm.rename_custom_gesture("wave", "wave2")
        seq = self.gm.get_sequence("greet")
        self.assertEqual(seq["steps"][0]["gesture_name"], "wave2")


# ──────────────────────────────────────────────────────────────────
# 3. 序列 CRUD
# ──────────────────────────────────────────────────────────────────

class TestSequenceCRUD(unittest.TestCase):
    """序列的增删改查。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir
        self.gm = _make_manager(self._tmpdir)
        # 创建一个测试用自定义手势
        self.gm.create_custom_gesture("custom_g", [100] * 10)

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def test_create_valid_sequence(self):
        """合法创建序列。"""
        data = self.gm.create_sequence("my_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
            {"gesture_name": "fist", "duration": 0.5, "delay_after": 0.3},
        ])
        self.assertEqual(len(data["steps"]), 2)
        self.assertFalse(data["loop"])

    def test_create_with_loop(self):
        """创建循环序列。"""
        data = self.gm.create_sequence("loop_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
        ], loop=True)
        self.assertTrue(data["loop"])

    def test_create_empty_name_raises(self):
        """空名称创建序列应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_sequence("", [
                {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
            ])

    def test_create_empty_steps_raises(self):
        """空步骤列表创建序列应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_sequence("empty_steps", [])

    def test_create_invalid_gesture_ref_raises(self):
        """引用不存在手势的序列应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_sequence("bad_ref", [
                {"gesture_name": "nonexist", "duration": 1.0, "delay_after": 0.0}
            ])

    def test_create_zero_duration_raises(self):
        """duration <= 0 应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_sequence("zero_dur", [
                {"gesture_name": "open", "duration": 0, "delay_after": 0.0}
            ])

    def test_create_negative_delay_raises(self):
        """negative delay 应失败。"""
        with self.assertRaises(ValueError):
            self.gm.create_sequence("neg_delay", [
                {"gesture_name": "open", "duration": 1.0, "delay_after": -1.0}
            ])

    def test_update_steps(self):
        """更新序列步骤。"""
        self.gm.create_sequence("upd_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
        ])
        data = self.gm.update_sequence("upd_seq", steps=[
            {"gesture_name": "fist", "duration": 2.0, "delay_after": 1.0},
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        self.assertEqual(len(data["steps"]), 2)

    def test_update_loop_flag(self):
        """更新序列循环标志。"""
        self.gm.create_sequence("loop_upd", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
        ])
        data = self.gm.update_sequence("loop_upd", loop=True)
        self.assertTrue(data["loop"])

    def test_update_non_existing_raises(self):
        """更新不存在的序列应失败。"""
        with self.assertRaises(KeyError):
            self.gm.update_sequence("nonexist", steps=[])

    def test_delete_existing_returns_true(self):
        """删除存在的序列返回 True。"""
        self.gm.create_sequence("del_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
        ])
        result = self.gm.delete_sequence("del_seq")
        self.assertTrue(result)
        self.assertNotIn("del_seq", self.gm.list_sequences())

    def test_delete_non_existing_returns_false(self):
        """删除不存在的序列返回 False。"""
        result = self.gm.delete_sequence("nonexist")
        self.assertFalse(result)

    def test_sequence_with_custom_gesture(self):
        """序列可以引用自定义手势。"""
        self.gm.create_sequence("custom_seq", [
            {"gesture_name": "custom_g", "duration": 1.0, "delay_after": 0.0}
        ])
        seq = self.gm.get_sequence("custom_seq")
        self.assertEqual(seq["steps"][0]["gesture_name"], "custom_g")


# ──────────────────────────────────────────────────────────────────
# 4. 手势名称解析
# ──────────────────────────────────────────────────────────────────

class TestResolveGesture(unittest.TestCase):
    """手势名称解析逻辑。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir
        self.gm = _make_manager(self._tmpdir)

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def test_resolve_builtin_open(self):
        """内置名称 'open' 正确解析。"""
        result = self.gm.resolve_gesture("open")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0], 255)

    def test_resolve_builtin_fist(self):
        """内置名称 'fist' 正确解析。"""
        result = self.gm.resolve_gesture("fist")
        self.assertIsNotNone(result)
        self.assertEqual(result, (122, 145, 0, 0, 0, 0, 0, 0, 0, 92))

    def test_resolve_custom_gesture(self):
        """自定义手势名称正确解析。"""
        self.gm.create_custom_gesture("custom", [42] * 10)
        result = self.gm.resolve_gesture("custom")
        self.assertIsNotNone(result)
        self.assertEqual(result, tuple([42] * 10))

    def test_resolve_custom_overrides_builtin(self):
        """自定义手势优先级高于内置（虽然名称冲突被阻止，但结构上正确）。"""
        self.gm.create_custom_gesture("custom_x", [77] * 10)
        result = self.gm.resolve_gesture("custom_x")
        self.assertEqual(result, tuple([77] * 10))

    def test_resolve_unknown_returns_none(self):
        """未知名返回 None。"""
        self.assertIsNone(self.gm.resolve_gesture("does_not_exist"))

    def test_is_builtin_gesture(self):
        """is_builtin_gesture 正确识别内置名称。"""
        self.assertTrue(self.gm.is_builtin_gesture("open"))
        self.assertTrue(self.gm.is_builtin_gesture("fist"))
        self.assertFalse(self.gm.is_builtin_gesture("my_custom"))

    def test_is_custom_gesture(self):
        """is_custom_gesture 正确识别自定义名称。"""
        self.gm.create_custom_gesture("custom_check", [100] * 10)
        self.assertTrue(self.gm.is_custom_gesture("custom_check"))
        self.assertFalse(self.gm.is_custom_gesture("open"))

    def test_get_all_gesture_names(self):
        """get_all_gesture_names 返回内置 + 自定义。"""
        self.gm.create_custom_gesture("all_test", [100] * 10)
        names = self.gm.get_all_gesture_names()
        self.assertIn("open", names)
        self.assertIn("fist", names)
        self.assertIn("all_test", names)
        # 内置在前
        builtin_idx = names.index("open")
        custom_idx = names.index("all_test")
        self.assertLess(builtin_idx, custom_idx)


# ──────────────────────────────────────────────────────────────────
# 5. 验证
# ──────────────────────────────────────────────────────────────────

class TestValidation(unittest.TestCase):
    """名称和步骤验证逻辑。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir
        self.gm = _make_manager(self._tmpdir)

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def test_validate_gesture_name_valid(self):
        """合法名称验证通过。"""
        valid, err = self.gm.validate_gesture_name("new_gesture")
        self.assertTrue(valid)
        self.assertEqual(err, "")

    def test_validate_gesture_name_empty(self):
        """空名称验证失败。"""
        valid, err = self.gm.validate_gesture_name("")
        self.assertFalse(valid)

    def test_validate_gesture_name_whitespace(self):
        """纯空白名称验证失败。"""
        valid, err = self.gm.validate_gesture_name("   ")
        self.assertFalse(valid)

    def test_validate_gesture_name_builtin(self):
        """内置名称验证失败。"""
        valid, err = self.gm.validate_gesture_name("fist")
        self.assertFalse(valid)

    def test_validate_gesture_name_duplicate(self):
        """重复自定义名称验证失败。"""
        self.gm.create_custom_gesture("dup_v", [100] * 10)
        valid, err = self.gm.validate_gesture_name("dup_v")
        self.assertFalse(valid)

    def test_validate_sequence_steps_valid(self):
        """合法步骤验证通过。"""
        valid, err = self.gm.validate_sequence_steps([
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        self.assertTrue(valid)

    def test_validate_sequence_steps_empty(self):
        """空步骤列表验证失败。"""
        valid, err = self.gm.validate_sequence_steps([])
        self.assertFalse(valid)

    def test_validate_sequence_steps_invalid_gesture(self):
        """引用不存在手势的步骤验证失败。"""
        valid, err = self.gm.validate_sequence_steps([
            {"gesture_name": "nonexist", "duration": 1.0, "delay_after": 0.0},
        ])
        self.assertFalse(valid)

    def test_validate_sequence_steps_zero_duration(self):
        """零持续时间验证失败。"""
        valid, err = self.gm.validate_sequence_steps([
            {"gesture_name": "open", "duration": 0, "delay_after": 0.0},
        ])
        self.assertFalse(valid)

    def test_validate_sequence_steps_negative_delay(self):
        """负延迟验证失败。"""
        valid, err = self.gm.validate_sequence_steps([
            {"gesture_name": "open", "duration": 1.0, "delay_after": -1.0},
        ])
        self.assertFalse(valid)

    def test_get_invalid_sequence_steps(self):
        """get_invalid_sequence_steps 正确识别断裂引用。"""
        # 直接注入包含断裂引用的序列（跳过验证）
        self.gm._sequences["bad_seq"] = {
            "steps": [
                {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
                {"gesture_name": "nonexist", "duration": 1.0, "delay_after": 0.0},
            ],
            "loop": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        invalid = self.gm.get_invalid_sequence_steps("bad_seq")
        self.assertEqual(invalid, [1])


# ──────────────────────────────────────────────────────────────────
# 6. 事件通知
# ──────────────────────────────────────────────────────────────────

class TestChangeCallbacks(unittest.TestCase):
    """变更事件通知机制。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_home = os.environ.get("HOME")
        os.environ["HOME"] = self._tmpdir
        self.gm = _make_manager(self._tmpdir)
        self.events: list[tuple[str, str]] = []

    def tearDown(self):
        if self._orig_home is not None:
            os.environ["HOME"] = self._orig_home
        else:
            os.environ.pop("HOME", None)

    def _on_changed(self, change_type: str, key: str) -> None:
        self.events.append((change_type, key))

    def test_callback_on_create_gesture(self):
        """创建手势触发回调。"""
        self.gm.on_changed(self._on_changed)
        self.gm.create_custom_gesture("cb_test", [100] * 10)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][0], "gesture_created")
        self.assertEqual(self.events[0][1], "cb_test")

    def test_callback_on_delete_gesture(self):
        """删除手势触发回调。"""
        self.gm.create_custom_gesture("cb_del", [100] * 10)
        self.gm.on_changed(self._on_changed)
        self.gm.delete_custom_gesture("cb_del")
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][0], "gesture_deleted")

    def test_callback_on_create_sequence(self):
        """创建序列触发回调。"""
        self.gm.on_changed(self._on_changed)
        self.gm.create_sequence("cb_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}
        ])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][0], "sequence_created")

    def test_multiple_callbacks(self):
        """多个回调同时注册，全部被调用。"""
        events_a: list = []
        events_b: list = []

        def cb_a(ct, k):
            events_a.append((ct, k))

        def cb_b(ct, k):
            events_b.append((ct, k))

        self.gm.on_changed(cb_a)
        self.gm.on_changed(cb_b)
        self.gm.create_custom_gesture("multi", [100] * 10)
        self.assertEqual(len(events_a), 1)
        self.assertEqual(len(events_b), 1)

    def test_callback_exception_does_not_crash(self):
        """回调抛出异常不影响其他回调。"""
        good_called = False

        def bad_callback(ct, k):
            raise RuntimeError("intentional")

        def good_callback(ct, k):
            nonlocal good_called
            good_called = True

        self.gm.on_changed(bad_callback)
        self.gm.on_changed(good_callback)
        # 不应崩溃
        self.gm.create_custom_gesture("safe", [100] * 10)
        self.assertTrue(good_called)


if __name__ == '__main__':
    unittest.main()
