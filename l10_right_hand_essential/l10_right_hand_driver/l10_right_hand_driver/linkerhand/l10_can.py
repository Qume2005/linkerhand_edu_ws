#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L10 灵巧手 CAN 总线通信驱动。

通过 CAN 总线与灵巧手硬件通信的核心驱动类，支持：

- 10 自由度关节位置控制（分两帧发送：前 6 + 后 4）
- 关节速度、力矩限制设置
- 触觉传感器数据读取（单点压力、12×6 矩阵压力）
- 电机温度、故障码、电流、序列号查询
- 固件版本查询

CAN 帧格式::

    数据帧: [frame_property(1字节)] + [数据(0~7字节)]
    仲裁 ID: 右手固定为 0x27

通信架构:
    发送端: 调用各 set/get 方法 → send_frame() → CAN 总线
    接收端: 守护线程 receive_response() 持续监听 → process_response() 按帧类型分发

注意:
    - 使用 python-can 库，Linux 使用 SocketCAN，Windows 使用 PCAN/candle
    - 所有 CAN 帧发送后都有最小间隔（默认 2ms），避免总线拥塞
    - 发送命令期间设置 ``is_cmd=True``，阻止状态查询干扰
"""
import can
import time
import sys
import threading
import numpy as np
from enum import Enum
from l10_right_hand_driver.linkerhand.open_can import OpenCan
from l10_right_hand_driver.linkerhand.color_msg import ColorMsg
from can.exceptions import CanError



class FrameProperty(Enum):
    """CAN 帧类型标识枚举。

    每个值对应 CAN 数据帧的第一个字节，用于标识帧的用途。
    """
    INVALID_FRAME_PROPERTY = 0x00
    JOINT_POSITION_RCO = 0x01
    MAX_PRESS_RCO = 0x02
    MAX_PRESS_RCO2 = 0x03
    JOINT_POSITION2_RCO = 0x04
    JOINT_SPEED = 0x05
    JOINT_SPEED2 = 0x06
    REQUEST_DATA_RETURN = 0x09
    JOINT_POSITION_N = 0x11
    MAX_PRESS_N = 0x12
    HAND_NORMAL_FORCE = 0X20
    HAND_TANGENTIAL_FORCE = 0X21
    HAND_TANGENTIAL_FORCE_DIR = 0X22
    HAND_APPROACH_INC = 0X23
    MOTOR_TEMPERATURE_1 = 0x33
    MOTOR_TEMPERATURE_2 = 0x34

class LinkerHandL10Can:
    """L10 灵巧手 CAN 总线通信接口。

    封装了与 L10 灵巧手硬件通信的全部 CAN 协议细节。
    内部维护一个守护线程持续接收 CAN 响应，并按帧类型更新内部状态。

    Args:
        can_id: CAN 仲裁 ID，右手固定 ``0x27``
        can_channel: CAN 接口名称，默认 ``"can0"``
        baudrate: 波特率，默认 ``1000000`` (1Mbps)
        yaml: YAML 配置文件路径（可选）

    Attributes:
        joint_angles: 最近一次发送的 10 个关节角度缓存
        normal_force: 5 指法向力列表
        thumb_matrix ~ little_matrix: 5 指 12×6 矩阵触觉数据 (numpy array)
        version: 固件版本信息列表
    """
    def __init__(self,can_id, can_channel='can0', baudrate=1000000, yaml=""):
        self.can_id = can_id
        self.can_channel = can_channel
        self.baudrate = baudrate
        self.open_can = OpenCan(load_yaml=yaml)
        self.is_cmd = False
        self.x01 = [-1] * 5
        self.x02 = [-1] * 5
        self.x03 = [-1] * 5
        self.x04 = [-1] * 5
        self.x05 = [-1] * 5
        self.x06 = [-1] * 5
        self.x33 = self.x34 = [0] * 5
        # Fault codes
        self.x35,self.x36 = [0] * 5,[0] * 5
        # New pressure sensors
        self.xb0,self.xb1,self.xb2,self.xb3,self.xb4,self.xb5 = [-1] * 5,[-1] * 5,[-1] * 5,[-1] * 5,[-1] * 5,[-1] * 5
        
        self.thumb_matrix = np.full((12, 6), -1)
        self.index_matrix = np.full((12, 6), -1)
        self.middle_matrix = np.full((12, 6), -1)
        self.ring_matrix = np.full((12, 6), -1)
        self.little_matrix = np.full((12, 6), -1)
        self.matrix_map = {
            0: 0,
            16: 1,
            32: 2,
            48: 3,
            64: 4,
            80: 5,
            96: 6,
            112: 7,
            128: 8,
            144: 9,
            160: 10,
            176: 11,
        }
        self.serial_number = []
        self.serial_number_map = {
            0: 0,
            1: 1,
            2: 2,
            3: 3,
        }
        self.can_id = can_id
        self.joint_angles = [0] * 10
        self.pressures = [200] * 5  # Default torque 200
        self.bus = self.init_can_bus(can_channel, baudrate)
        self.normal_force, self.tangential_force, self.tangential_force_dir, self.approach_inc = [[-1] * 5 for _ in range(4)]
        self.version = None
        # Start receiving thread
        self.running = True
        self.receive_thread = threading.Thread(target=self.receive_response)
        self.receive_thread.daemon = True
        self.receive_thread.start()
        self.version = self.get_version()

    def init_can_bus(self, channel, baudrate):
        """
        尝试按优先级连接 CAN 总线，并实现回退机制。
        """
        # --- 统一异常处理块开始 ---
        try:
            if sys.platform == "linux":
                # Linux 优先级：1. socketcan
                try:
                    self.open_can.open_can(self.can_channel)
                    # 尝试 socketcan
                    bus = can.interface.Bus(channel=channel, interface="socketcan", bitrate=baudrate)
                    ColorMsg(msg=f"成功连接: interface='socketcan', channel='{channel}'", color="green")
                    return bus
                except CanError as e:
                    # 如果 socketcan 失败，可以考虑在这里尝试其他 Linux 接口 (如 'pcan')
                    ColorMsg(msg=f"socketcan 接口连接失败: {e}", color="yellow")
                    raise # 重新抛出异常，让外层 try 捕获
            elif sys.platform == "win32":
                # Windows 优先级：1. pcan
                try:
                    bus = can.interface.Bus(channel=channel, interface='pcan', bitrate=baudrate)
                    ColorMsg(msg=f"成功连接: interface='pcan', channel='{channel}'", color="green")
                    return bus
                except CanError as e:
                    ColorMsg(msg=f"pcan 接口连接失败，尝试回退到 'candle': {e}", color="yellow")
                # Windows 优先级：2. candle (回退方法)
                try:
                    bus = can.Bus(interface="candle", channel=channel, bitrate=baudrate)
                    ColorMsg(msg=f"成功连接: interface='candle', channel='{channel}'", color="green")
                    return bus
                except CanError as e:
                    ColorMsg(msg=f"candle 接口连接失败: {e}", color="yellow")
                    raise # 两个接口都失败，抛出异常
            else:
                raise EnvironmentError("Unsupported platform for CAN interface")
        # --- 统一异常处理块结束 ---
        except Exception as e:
            # 如果任何一个接口尝试失败并抛出异常（包括 EnvironmentError）
            ColorMsg(msg=f"致命错误：所有 CAN 接口连接尝试均失败或平台不受支持。请检查设备连接或驱动安装和配置文件中CAN参数的配置。\n错误详情: {e}", color="red")
            # 保持 raise 动作，将错误信息传递给调用者，避免程序继续运行
            raise

    def send_frame(self, frame_property, data_list,sleep=0.002):
        """Send a single CAN frame with specified properties and data."""
        frame_property_value = int(frame_property.value) if hasattr(frame_property, 'value') else frame_property
        data = [frame_property_value] + [int(val) for val in data_list]
        msg = can.Message(arbitration_id=self.can_id, data=data, is_extended_id=False)
        try:
            self.bus.send(msg)
        except can.CanError as e:
            print(f"Failed to send message: {e}")
            self.open_can.open_can(self.can_channel)
            time.sleep(1)
            self.is_can = self.open_can.is_can_up_sysfs(interface=self.can_channel)
            time.sleep(1)
            if self.is_can:
                self.bus = can.interface.Bus(channel=self.can_channel, interface="socketcan", bitrate=self.baudrate)
            else:
                print("Reconnecting CAN devices ....")
        time.sleep(sleep)

    def set_joint_positions(self, joint_angles):
        """Set the positions of 10 joints (joint_angles: list of 10 values)."""
        self.joint_angles = joint_angles
        self.is_cmd = True
        # Send angle control in frames, L10 protocol splits into first 6 and last 4
        self.send_frame(FrameProperty.JOINT_POSITION2_RCO, self.joint_angles[6:])
        self.send_frame(FrameProperty.JOINT_POSITION_RCO, self.joint_angles[:6])
        self.is_cmd = False
        

    def set_max_torque_limits(self, pressures,type="get"):
        """Set maximum torque limits"""
        if type == "get":
            self.pressures = [0.0]
        else:
            self.pressures = pressures[:5]
        #self.send_frame(FrameProperty.MAX_PRESS_RCO, self.pressures)
        
        
    def set_joint_speed_l10(self,speed=[180]*5):
        self.x05 = speed
        for i in range(2):
            time.sleep(0.01)
            self.send_frame(0x05, speed)
    def set_speed(self,speed=[180]*5):
        if len(speed) == 5:
            self.x05 = speed
            for i in range(2):
                time.sleep(0.01)
                self.send_frame(0x05, speed)
        elif len(speed) == 10:
            for i in range(2):
                time.sleep(0.01)
                self.send_frame(0x05, speed[:5])
                self.send_frame(0x06, speed[5:])
        else:
            raise ValueError("Speed list must have 10 elements.")
    def request_all_status(self):
        """Get all joint positions and pressures."""
        self.send_frame(FrameProperty.REQUEST_DATA_RETURN, [])

    # ============================================================
    #  压力传感器
    # ============================================================
    def get_normal_force(self):
        self.send_frame(FrameProperty.HAND_NORMAL_FORCE,[],sleep=0.004)

    def get_tangential_force(self):
        self.send_frame(FrameProperty.HAND_TANGENTIAL_FORCE,[],sleep=0.004)

    def get_tangential_force_dir(self):
        self.send_frame(FrameProperty.HAND_TANGENTIAL_FORCE_DIR,[],sleep=0.004)
    def get_approach_inc(self):
        self.send_frame(FrameProperty.HAND_APPROACH_INC, [], sleep=0.004)

    # ============================================================
    #  电机温度与故障码
    # ============================================================
    def get_motor_temperature(self):
        self.send_frame(FrameProperty.MOTOR_TEMPERATURE_1,[],sleep=0.01)
        self.send_frame(FrameProperty.MOTOR_TEMPERATURE_2,[],sleep=0.01)
    # Motor fault codes
    def get_motor_fault_code(self):
        self.send_frame(0x35,[],sleep=0.1)
        self.send_frame(0x36,[],sleep=0.1)
    def receive_response(self):
        """Receive CAN responses and process them."""
        while self.running:
            try:
                msg = self.bus.recv(timeout=1.0)
                if msg:
                    self.process_response(msg)
            except can.CanError as e:
                print(f"Error receiving CAN message: {e}")

    def process_response(self, msg):
        """Process received CAN messages."""
        if msg.arbitration_id == self.can_id:
            frame_type = msg.data[0]
            response_data = msg.data[1:]
            if len(list(response_data)) == 0:
                    return
            if frame_type == FrameProperty.JOINT_POSITION_RCO.value:   # 0x01
                self.x01 = list(response_data)  
            elif frame_type == FrameProperty.MAX_PRESS_RCO.value:    # 0x02
                self.x02 = list(response_data)
            elif frame_type == FrameProperty.MAX_PRESS_RCO2.value:    # 0x03
                self.x03 = list(response_data)
            elif frame_type == FrameProperty.JOINT_POSITION2_RCO.value:    # 0x04
                self.x04 = list(response_data)
            elif frame_type == 0x05:
                self.x05 = list(response_data)
            elif frame_type == 0x06:
                self.x06 = list(response_data)
            elif frame_type == 0x20:
                # Five-finger normal force
                d = list(response_data)
                self.normal_force = [float(i) for i in d]
            elif frame_type == 0x21:
                # Five-finger tangential force
                d = list(response_data)
                self.tangential_force = [float(i) for i in d]
            elif frame_type == 0x22:
                # Five-finger tangential force direction
                d = list(response_data)
                self.tangential_force_dir = [float(i) for i in d]
            elif frame_type == 0x23:
                # Five-finger approach increment
                d = list(response_data)
                self.approach_inc = [float(i) for i in d]
            elif frame_type == 0x33:
                self.x33 = list(response_data)
            elif frame_type == 0x34:
                self.x34 = list(response_data)
            elif frame_type == 0x35:
                self.x35 = list(response_data)
            elif frame_type == 0x36:
                self.x36 = list(response_data)
            elif frame_type == 0xb0:
                self.xb0 = list(response_data)
            elif frame_type == 0xb1:
                d = list(response_data)
                if len(d) == 2:
                    self.xb1 = d
                elif len(d) == 7:
                    index = self.matrix_map.get(d[0])
                    if index is not None:
                        self.thumb_matrix[index] = d[1:]  # Remove the first flag bit
            elif frame_type == 0xb2:
                d = list(response_data)
                if len(d) == 2:
                    self.xb2 = d
                elif len(d) == 7:
                    index = self.matrix_map.get(d[0])
                    if index is not None:
                        self.index_matrix[index] = d[1:]  # Remove the first flag bit
            elif frame_type == 0xb3:
                d = list(response_data)
                if len(d) == 2:
                    self.xb3 = d
                elif len(d) == 7:
                    index = self.matrix_map.get(d[0])
                    if index is not None:
                        self.middle_matrix[index] = d[1:]  # Remove the first flag bit
            elif frame_type == 0xb4:
                d = list(response_data)
                if len(d) == 2:
                    self.xb4 = d
                elif len(d) == 7:
                    index = self.matrix_map.get(d[0])
                    if index is not None:
                        self.ring_matrix[index] = d[1:]  # Remove the first flag bit
            elif frame_type == 0xb5:
                d = list(response_data)
                if len(d) == 2:
                    self.xb5 = d
                elif len(d) == 7:
                    index = self.matrix_map.get(d[0])
                    if index is not None:
                        self.little_matrix[index] = d[1:]  # Remove the first flag bit
            elif frame_type == 0x64:
                self.version =  list(response_data)
            elif frame_type == 0xC2: # version number
                self.version = list(response_data)
            elif frame_type == 0xC0:
                d = list(response_data)
                index = self.serial_number_map.get(d[0])
                if index is not None:
                    self.serial_number=self.serial_number + d[1:]
                else:
                    self.serial_number=self.serial_number + [-1] * 6

    def get_version(self):
        self.send_frame(0x64, [], sleep=0.1)
        time.sleep(0.1)
        if self.version is None:
            self.send_frame(0xC2, [], sleep=0.1)
            time.sleep(0.1)
        return self.version

    def set_torque(self,torque=[]):
        '''Set maximum torque'''
        if len(torque) == 5:
            self.send_frame(0x02, torque)
            time.sleep(0.002)
            self.send_frame(0x03,torque)
        elif len(torque) > 5:
            self.send_frame(0x02, torque[:5])
            time.sleep(0.002)
            self.send_frame(0x03,torque[5:])

    
    def get_current_status(self):
        '''Get current joint status'''
        if self.is_cmd == False:
            self.send_frame(0x01,[],sleep=0.003)
            self.send_frame(0x04,[],sleep=0.003)
            state = self.x01 + self.x04
            return state
        else:
            state = self.x01 + self.x04
            return state
        
    def get_current_pub_status(self):
        state = self.x01 + self.x04
        return state
        
    def get_speed(self):
        '''Get current speed'''
        self.send_frame(0x05,[],sleep=0.003)
        self.send_frame(0x06,[],sleep=0.003)
        return self.x05 + self.x06
        
    def get_force(self):
        '''Get pressure sensor data'''
        return [self.normal_force,self.tangential_force , self.tangential_force_dir , self.approach_inc]
    def get_temperature(self):
        '''Get current motor temperature'''
        self.get_motor_temperature()
        return self.x33+self.x34

    def get_touch_type(self):
        '''Get touch type'''
        self.send_frame(0xb0,[],sleep=0.03)
        self.send_frame(0xb1,[],sleep=0.03)
        t = []
        for i in range(3):
            t = self.xb1
            time.sleep(0.01)
        if len(t) == 2:
            return 2
        else:
            self.send_frame(0x20,[],sleep=0.03)
            time.sleep(0.01)
            if self.normal_force[0] == -1:
                return -1
            else:
                return 1
    
    def get_touch(self):
        '''Get touch data'''
        self.send_frame(0xb1,[],sleep=0.03)
        self.send_frame(0xb2,[],sleep=0.03)
        self.send_frame(0xb3,[],sleep=0.03)
        self.send_frame(0xb4,[],sleep=0.03)
        self.send_frame(0xb5,[],sleep=0.03)
        return [self.xb1[1],self.xb2[1],self.xb3[1],self.xb4[1],self.xb5[1],0] # The last digit is palm, currently not available

    def get_matrix_touch(self):
        self.send_frame(0xb1,[0xc6],sleep=0.06)
        self.send_frame(0xb2,[0xc6],sleep=0.06)
        self.send_frame(0xb3,[0xc6],sleep=0.06)
        self.send_frame(0xb4,[0xc6],sleep=0.06)
        self.send_frame(0xb5,[0xc6],sleep=0.06)
        return self.thumb_matrix , self.index_matrix , self.middle_matrix , self.ring_matrix , self.little_matrix
    
    def get_matrix_touch_v2(self):
        self.send_frame(0xb1,[0xc6],sleep=0.005)
        self.send_frame(0xb2,[0xc6],sleep=0.005)
        self.send_frame(0xb3,[0xc6],sleep=0.005)
        self.send_frame(0xb4,[0xc6],sleep=0.005)
        self.send_frame(0xb5,[0xc6],sleep=0.005)
        return self.thumb_matrix , self.index_matrix , self.middle_matrix , self.ring_matrix , self.little_matrix

    def get_thumb_matrix_touch(self,sleep_time=0.005):
        self.send_frame(0xb1,[0xc6],sleep=sleep_time)
        return self.thumb_matrix
    
    def get_index_matrix_touch(self,sleep_time=0.005):
        self.send_frame(0xb2,[0xc6],sleep=sleep_time)
        return self.index_matrix
    
    def get_middle_matrix_touch(self,sleep_time=0.005):
        self.send_frame(0xb3,[0xc6],sleep=sleep_time)
        return self.middle_matrix
    
    def get_ring_matrix_touch(self,sleep_time=0.005):
        self.send_frame(0xb4,[0xc6],sleep=sleep_time)
        return self.ring_matrix
    
    def get_little_matrix_touch(self,sleep_time=0.005):
        self.send_frame(0xb5,[0xc6],sleep=sleep_time)
        return self.little_matrix


    def get_torque(self):
        '''Get current motor torque'''
        if self.version != None and self.version[4]< 36:
            return [-1] * 5
        else:
            self.send_frame(0x02, [])
            time.sleep(0.002)
            self.send_frame(0x03,[])
            time.sleep(0.002)
            return self.x02+self.x03
    
    def get_fault(self):
        '''Get motor fault'''
        self.get_motor_fault_code()
        return self.x35+self.x36
    
    def get_current(self):
        '''Get current'''
        #return [-1] * 5
        self.send_frame(0x02, [])
        time.sleep(0.002)
        self.send_frame(0x03,[])
        return self.x02+self.x03
    
    def get_serial_number(self):
        try:
            self.send_frame(0xC0,[],sleep=0.005)
            # 1. 使用 bytes() 函数将整数列表转换为字节对象
            #    bytes() 接收一个由 0-255 之间的整数组成的列表。
            byte_data = bytes(self.serial_number)
            # 2. 使用 .decode() 方法将字节对象解码为 ASCII 字符串
            result_string = byte_data.decode('ascii')
            if result_string == "":
                return "-1"
            else:
                # print(f"原始 ASCII 码列表: {self.serial_number}")
                # print(f"解码后的字符串: {result_string}")
                return result_string
        except:
            return "-1"

    def get_finger_order(self):
        return ["thumb_cmc_pitch", "thumb_cmc_yaw", "index_mcp_pitch", "middle_mcp_pitch", "ring_mcp_pitch", "pinky_mcp_pitch",
                        "index_mcp_roll", "ring_mcp_roll", "pinky_mcp_roll", "thumb_cmc_roll"]

    def show_fun_table(self):
        # if len(data) != 8 or data[0] != 0x64:
        #     raise ValueError("数据格式不正确")
        data = self.version
        result = {
            "自由度": data[0],
            "机械版本": data[1],
            "版本序号": data[2],
            "手方向": chr(data[3]),  # ASCII 转字符
            "软件版本": f"V{data[4] >> 4}.{data[4] & 0x0F}",
            "硬件版本": f"V{data[5] >> 4}.{data[5] & 0x0F}",
            "修订标志": data[6],
            "set_position": "Y",
            "set_torque": "Y",
            "set_speed": "Y",
            "get_version": "Y",
            "get_current_status": "Y",
            "get_speed": "Y",
            "get_temperature": "Y",
            "get_touch_type": "Y",
            "get_matrix_touch": "Y",
            "get_fault": "Y",
            "get_current": "current == torque"
        }
        
        #return [data[0],data[1],data[2],chr(data[3]),f"V{data[4] >> 4}.{data[4] & 0x0F}",f"V{data[5] >> 4}.{data[5] & 0x0F}",data[6]]
        table = [[k, v] for k, v in result.items()]

    def close_can_interface(self):
        """Stop the CAN communication."""
        self.running = False
        if self.receive_thread.is_alive():
            self.receive_thread.join()
        if self.bus:
            self.bus.shutdown()
