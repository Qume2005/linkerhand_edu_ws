#! /usr/bin/env python3
"""带颜色的终端消息输出工具。

提供简单的彩色消息打印功能，支持红色、绿色、黄色三种颜色，
用于 CAN 驱动和 SDK 中状态信息的可视化输出。

输出格式: ``[时间戳] 消息内容``，其中消息内容会以指定颜色显示。

用法::

    from linkerhand.color_msg import ColorMsg
    ColorMsg(msg="CAN 接口连接成功", color="green")
    ColorMsg(msg="连接失败", color="red")
    ColorMsg(msg="正在重试...", color="yellow")
"""
import time


class ColorMsg():
    """带时间戳和颜色的终端消息打印器。

    构造时立即打印消息，无需额外调用。

    Args:
        msg: 要打印的消息文本
        color: 颜色名称，支持 ``"red"``、``"green"``、``"yellow"``。
               空字符串或其他值表示无颜色（白色）
        timestamp: 是否在消息前添加时间戳，默认 ``True``

    Example::

        ColorMsg(msg="成功", color="green")  # 打印绿色时间戳消息
    """

    def __init__(self, msg: str, color: str = '', timestamp: bool = True) -> None:
        """初始化并立即打印彩色消息。"""
        self.msg = msg
        self.color = color
        self.timestamp = timestamp
        self.colorMsg(msg=self.msg, color=self.color, timestamp=self.timestamp)

    def colorMsg(self, msg: str, color: str = '', timestamp: bool = True):
        """格式化并打印带颜色的消息。

        使用 ANSI 转义码实现终端颜色：

        - 红色 (``red``): 亮红色前景，黑色背景
        - 绿色 (``green``): 亮绿色前景，黑色背景
        - 黄色 (``yellow``): 亮黄色前景，黑色背景
        - 其他: 无颜色修饰

        Args:
            msg: 消息文本
            color: 颜色名称
            timestamp: 是否添加时间戳
        """
        output = ""
        if timestamp:
            output += time.strftime('%Y-%m-%d %H:%M:%S',
                                    time.localtime(time.time())) + "  "
        if color == "red":
            output += "\033[1;31;40m"
        elif color == "green":
            output += "\033[1;32;40m"
        elif color == "yellow":
            output += "\033[1;33;40m"
        else:
            print(output + msg, flush=True)
            return
        output += msg + "\033[0m"
        print(output, flush=True)
