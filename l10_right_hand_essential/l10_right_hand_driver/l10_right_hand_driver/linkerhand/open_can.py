#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAN 总线接口管理工具。

提供 CAN 接口的自动检测、配置、启动和关闭功能。
使用 Linux ip link 命令通过 sudo 配置 SocketCAN 接口（默认波特率 1Mbps）。
sudo 密码从 setting.yaml 配置文件中读取。

典型用法::

    from linkerhand.open_can import OpenCan
    oc = OpenCan()
    oc.open_can("can0")        # 自动检测并启动 can0
    oc.is_can_up_sysfs("can0") # 检查接口状态
    oc.close_can("can0")       # 关闭接口

注意事项:
    - 需要系统已安装 ``ip`` 命令（iproute2 包）
    - 需要当前用户有 sudo 权限
    - 所有异常均被静默吞掉（不向上层抛出），确保不因 CAN 初始化问题阻断主流程
"""
import sys
import os
import time
import subprocess

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from l10_right_hand_driver.linkerhand.color_msg import ColorMsg
from l10_right_hand_driver.linkerhand.load_write_yaml import LoadWriteYaml
import os


class OpenCan:
    """CAN 总线接口管理器。

    负责通过 Linux ``ip link`` 命令管理 SocketCAN 接口的启停。
    启动时会先检测接口是否已经 UP，避免重复配置。

    Args:
        load_yaml: YAML 配置文件路径（可选，默认使用内置 setting.yaml）

    Attributes:
        password: sudo 密码，从 setting.yaml 中读取
    """

    def __init__(self, load_yaml=None):
        """初始化 CAN 接口管理器，加载配置文件中的 sudo 密码。"""
        self.yaml = LoadWriteYaml()
        self.password = self.yaml.load_setting_yaml()["PASSWORD"]

    def open_can0(self):
        """启动 can0 接口（波特率 1Mbps）。

        先检测 can0 是否已处于 UP 状态，如果是则直接返回。
        否则通过 ``sudo ip link set can0 up type can bitrate 1000000`` 配置并启动。
        所有异常被静默处理。
        """
        try:
            # 检查 can0 接口是否已存在并处于 up 状态
            result = subprocess.run(
                ["ip", "link", "show", "can0"],
                check=True,
                text=True,
                capture_output=True
            )
            if "state UP" in result.stdout:
                return
            # 如果没有处于 UP 状态，则配置接口
            subprocess.run(
                ["sudo", "-S", "ip", "link", "set", "can0", "up", "type", "can", "bitrate", "1000000"],
                input=f"{self.password}\n",
                check=True,
                text=True,
                capture_output=True
            )

        except subprocess.CalledProcessError as e:
            pass
        except Exception as e:
            pass

    def open_can(self, can="can0"):
        """启动指定 CAN 接口（波特率 1Mbps）。

        功能与 ``open_can0`` 相同，但支持自定义接口名。

        Args:
            can: CAN 接口名称，默认 ``"can0"``
        """
        try:
            # 检查 can0 接口是否已存在并处于 up 状态
            result = subprocess.run(
                ["ip", "link", "show", can],
                check=True,
                text=True,
                capture_output=True
            )
            if "state UP" in result.stdout:
                return
            # 如果没有处于 UP 状态，则配置接口
            subprocess.run(
                ["sudo", "-S", "ip", "link", "set", can, "up", "type", "can", "bitrate", "1000000"],
                input=f"{self.password}\n",
                check=True,
                text=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            pass
        except Exception as e:
            pass

    def is_can_up_sysfs(self, interface="can0"):
        """通过 sysfs 检查 CAN 接口是否已启动。

        读取 ``/sys/class/net/{interface}/operstate`` 文件判断接口状态。

        Args:
            interface: CAN 接口名称，默认 ``"can0"``

        Returns:
            bool: ``True`` 表示接口已 UP，``False`` 表示接口不存在或未启动
        """
        # 检查接口目录是否存在
        if not os.path.exists(f"/sys/class/net/{interface}"):
            return False
        # 读取接口状态
        try:
            with open(f"/sys/class/net/{interface}/operstate", "r") as f:
                state = f.read().strip()
            if state == "up":
                return True
        except Exception as e:
            print(f"Error reading CAN interface state: {e}")
            return False

    def close_can0(self):
        """关闭 can0 接口。

        如果 can0 存在且处于 UP 状态，通过 ``sudo ip link set can0 down`` 关闭。

        Returns:
            bool: ``True`` 表示成功关闭，``False`` 表示接口不存在、未启动或关闭失败
        """
        try:
            # 检查 can0 接口是否存在
            result = subprocess.run(
                ["ip", "link", "show", "can0"],
                check=True,
                text=True,
                capture_output=True
            )

            # 如果接口存在且处于 UP 状态，则关闭它
            if "state UP" in result.stdout:
                subprocess.run(
                    ["sudo", "-S", "ip", "link", "set", "can0", "down"],
                    input=f"{self.password}\n",
                    check=True,
                    text=True,
                    capture_output=True
                )
                return True
            return False

        except subprocess.CalledProcessError as e:
            print(f"Error closing CAN interface: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False

    def close_can(self, can="can0"):
        """关闭指定 CAN 接口。

        功能与 ``close_can0`` 相同，但支持自定义接口名。

        Args:
            can: CAN 接口名称，默认 ``"can0"``

        Returns:
            bool: ``True`` 表示成功关闭，``False`` 表示接口不存在、未启动或关闭失败
        """
        try:
            # 检查 can0 接口是否存在
            result = subprocess.run(
                ["ip", "link", "show", can],
                check=True,
                text=True,
                capture_output=True
            )

            # 如果接口存在且处于 UP 状态，则关闭它
            if "state UP" in result.stdout:
                subprocess.run(
                    ["sudo", "-S", "ip", "link", "set", can, "down"],
                    input=f"{self.password}\n",
                    check=True,
                    text=True,
                    capture_output=True
                )
                return True
            return False

        except subprocess.CalledProcessError as e:
            print(f"Error closing CAN interface: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
