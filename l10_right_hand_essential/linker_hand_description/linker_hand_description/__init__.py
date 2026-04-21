import os


def get_urdf_path(filename="linker_hand_l10_right.xml"):
    """返回 MuJoCo XML 文件的绝对路径"""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right", filename
    )


def get_urdf_dir():
    """返回 URDF 目录的绝对路径"""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right"
    )


def get_model_path(filename="linker_hand_l10_right.urdf"):
    """返回 L10 右手 URDF/模型文件的绝对路径"""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right", filename
    )


def get_model_dir():
    """返回 L10 右手模型目录的绝对路径"""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right"
    )
