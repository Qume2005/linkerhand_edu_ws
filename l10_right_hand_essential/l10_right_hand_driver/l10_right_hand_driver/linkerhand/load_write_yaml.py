#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YAML 配置文件读写工具。

管理灵巧手 SDK 的配置文件，包括：

- ``setting.yaml``: 主配置文件（手型号、方向、触觉类型、sudo 密码）
- ``config/L{N}_positions.yaml``: 各型号手的预设动作位置文件

支持的型号: L7、L10、L20、L21、L25。

配置文件位于 ``linkerhand/`` 目录下，与 ``setting.yaml`` 同级。

用法::

    from linkerhand.load_write_yaml import LoadWriteYaml
    yml = LoadWriteYaml()
    setting = yml.load_setting_yaml()         # 加载主配置
    actions = yml.load_action_yaml("L10", "right")  # 加载 L10 右手预设动作
    yml.write_to_yaml("wave", [255, 0, ...], "L10", "right")  # 保存新动作
"""
import yaml
import os
import sys


class LoadWriteYaml():
    """灵巧手 YAML 配置文件管理器。

    管理多个配置文件路径，提供加载、读取、写入 YAML 配置的方法。

    Attributes:
        setting_path: setting.yaml 的绝对路径
        l7_positions ~ l25_positions: 各型号手的位置配置文件路径
        setting: 最近一次加载的 setting.yaml 内容（dict）
    """

    def __init__(self):
        """初始化配置文件路径。

        根据当前文件位置推算所有配置文件的绝对路径。
        配置文件约定位于 ``linkerhand/`` 目录下。
        """
        yaml_path = os.path.dirname(os.path.abspath(__file__))
        self.setting_path = yaml_path + "/setting.yaml"
        self.l7_positions = yaml_path + "/config/L7_positions.yaml"
        self.l10_positions = yaml_path + "/config/L10_positions.yaml"
        self.l20_positions = yaml_path + "/config/L20_positions.yaml"
        self.l21_positions = yaml_path + "/config/L21_positions.yaml"
        self.l25_positions = yaml_path + "/config/L25_positions.yaml"

    def load_setting_yaml(self):
        """加载主配置文件 setting.yaml。

        setting.yaml 的结构::

            VERSION: "sdk版本号"
            PASSWORD: "sudo密码"
            LINKER_HAND:
              LEFT_HAND:
                EXISTS: true/false
                NAME: "手名称"
                JOINT: "关节数"
                TOUCH: "触觉类型"
              RIGHT_HAND:
                EXISTS: true/false
                NAME: "手名称"
                JOINT: "关节数"
                TOUCH: "触觉类型"

        Returns:
            dict: 配置内容。文件不存在或解析失败时返回 ``None``
        """
        try:
            with open(self.setting_path, 'r', encoding='utf-8') as file:
                setting = yaml.safe_load(file)
                self.sdk_version = setting["VERSION"]
                self.left_hand_exists = setting['LINKER_HAND']['LEFT_HAND']['EXISTS']
                self.left_hand_names = setting['LINKER_HAND']['LEFT_HAND']['NAME']
                self.left_hand_joint = setting['LINKER_HAND']['LEFT_HAND']['JOINT']
                self.left_hand_force = setting['LINKER_HAND']['LEFT_HAND']['TOUCH']
                self.right_hand_exists = setting['LINKER_HAND']['RIGHT_HAND']['EXISTS']
                self.right_hand_names = setting['LINKER_HAND']['RIGHT_HAND']['NAME']
                self.right_hand_joint = setting['LINKER_HAND']['RIGHT_HAND']['JOINT']
                self.right_hand_force = setting['LINKER_HAND']['RIGHT_HAND']['TOUCH']
                self.password = setting['PASSWORD']
        except Exception as e:
            setting = None
            print(f"Error reading setting.yaml: {e}")
        self.setting = setting
        return self.setting

    def load_action_yaml(self, hand_joint="", hand_type=""):
        """加载指定型号手的预设动作位置文件。

        每个型号的位置文件包含 LEFT_HAND 和 RIGHT_HAND 两个列表，
        每个列表元素是一个 ``{"ACTION_NAME": str, "POSITION": list}`` 字典。

        Args:
            hand_joint: 手型号，支持 ``"L7"``、``"L10"``、``"L20"``、``"L21"``、``"L25"``
            hand_type: 手方向，``"left"`` 加载左手动作，其他值加载右手动作

        Returns:
            list: 动作列表，每个元素为 ``{"ACTION_NAME": str, "POSITION": list}``。
                  文件不存在或解析失败时返回 ``None``
        """
        if hand_joint == "L20":
            action_path = self.l20_positions
        elif hand_joint == "L10":
            action_path = self.l10_positions
        elif hand_joint == "L25":
            action_path = self.l25_positions
        elif hand_joint == "L21":
            action_path = self.l21_positions
        elif hand_joint == "L7":
            action_path = self.l7_positions
            print(action_path)
        try:
            with open(action_path, 'r', encoding='utf-8') as file:
                yaml_data = yaml.safe_load(file)
                if hand_type == "left":
                    self.action_yaml = yaml_data["LEFT_HAND"]
                else:
                    self.action_yaml = yaml_data["RIGHT_HAND"]
        except Exception as e:
            self.action_yaml = None
            print(f"yaml配置文件不存在: {e}")
        return self.action_yaml

    def write_to_yaml(self, action_name, action_pos, hand_joint="", hand_type=""):
        """向指定型号手的位置文件追加一个新动作。

        先读取整个 YAML 文件，向对应手的列表追加新动作，然后写回。
        如果列表为 ``None``，会自动初始化为空列表。

        Args:
            action_name: 动作名称（如 ``"wave"``、``"point"``）
            action_pos: 动作对应的关节位置列表
            hand_joint: 手型号（同 ``load_action_yaml``）
            hand_type: 手方向，``"left"`` 或 ``"right"``

        Returns:
            bool: ``True`` 表示写入成功，``False`` 表示写入失败
        """
        a = False
        if hand_joint == "L20":
            action_path = self.l20_positions
        elif hand_joint == "L10":
            action_path = self.l10_positions
        elif hand_joint == "L7":
            action_path = self.l7_positions
        elif hand_joint == "L21":
            action_path = self.l21_positions
        elif hand_joint == "L25":
            action_path = self.l25_positions
        try:
            with open(action_path, 'r', encoding='utf-8') as file:
                yaml_data = yaml.safe_load(file)
                print(yaml_data)
            if hand_type == "left":
                if yaml_data["LEFT_HAND"] is None:
                    yaml_data["LEFT_HAND"] = []
                yaml_data["LEFT_HAND"].append({"ACTION_NAME": action_name, "POSITION": action_pos})
            elif hand_type == "right":
                if yaml_data["RIGHT_HAND"] is None:
                    yaml_data["RIGHT_HAND"] = []
                yaml_data["RIGHT_HAND"].append({"ACTION_NAME": action_name, "POSITION": action_pos})
            with open(action_path, 'w', encoding='utf-8') as file:
                yaml.safe_dump(yaml_data, file, allow_unicode=True)
            a = True
        except Exception as e:
            a = False
            print(f"Error writing to yaml file: {e}")
        return a
