# -*- coding: utf-8 -*-
"""
hik_camera.py
海康工业相机完整控制模块（工业级终极封装版）
支持：
- 静态设备发现 (枚举局域网内所有相机)
- 触发模式切换（连续流、软触发、硬触发）
- 曝光时间、增益等参数读写
- 分辨率与 ROI 裁剪、帧率限制、触发延迟、白平衡、心跳超时
- 安全的取流与内存转换 (自动处理单通道与彩色相机的 NumPy 维度)
- 基于海康 SDK 4.6.0.1 绿化轮子
-作者 李成龙
"""

import os
import sys
import socket
import struct
import traceback
from ctypes import *
import cv2
import numpy as np
from datetime import datetime

try:
    # 完美衔接打包的 whl 轮子
    import MvImport.MvCameraControl_class as MVC
except Exception as e:
    print(f"[错误] 导入 SDK 失败: {e}")
    sys.exit(1)


class HikCamera:
    def __init__(self, target_ip=None):
        self.target_ip = target_ip
        self.cam = None
        self.is_init = False
        self.is_grabbing = False

    # ==================== 日志函数 ====================
    def _log(self, level, msg, code=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if code is not None:
            print(f"[{timestamp}] [{level}] {msg} (0x{code:08X})")
        else:
            print(f"[{timestamp}] [{level}] {msg}")

    def log_success(self, msg):
        self._log("成功", msg)

    def log_error(self, msg, code=None):
        self._log("失败", msg, code)

    def log_info(self, msg):
        self._log("信息", msg)

    # ==================== 全局设备发现 (供UI下拉框使用) ====================
    @staticmethod
    def enum_devices():
        """静态方法：扫描并返回当前网络下所有海康相机的列表"""
        stDeviceList = MVC.MV_CC_DEVICE_INFO_LIST()
        ret = MVC.MvCamera.MV_CC_EnumDevices(MVC.MV_GIGE_DEVICE | MVC.MV_USB_DEVICE, stDeviceList)

        devices = []
        if ret != MVC.MV_OK or stDeviceList.nDeviceNum == 0:
            return devices

        for i in range(stDeviceList.nDeviceNum):
            dev_info = cast(stDeviceList.pDeviceInfo[i], POINTER(MVC.MV_CC_DEVICE_INFO)).contents
            dev_dict = {"index": i, "type": "Unknown", "ip": "", "model": "", "sn": ""}

            if dev_info.nTLayerType == MVC.MV_GIGE_DEVICE:
                dev_dict["type"] = "GigE"
                ip_int = dev_info.SpecialInfo.stGigEInfo.nCurrentIp
                try:
                    dev_dict["ip"] = socket.inet_ntoa(struct.pack('!I', ip_int))
                except:
                    pass
                dev_dict["model"] = ''.join(chr(b) for b in dev_info.SpecialInfo.stGigEInfo.chModelName if b != 0)
                dev_dict["sn"] = ''.join(chr(b) for b in dev_info.SpecialInfo.stGigEInfo.chSerialNumber if b != 0)

            elif dev_info.nTLayerType == MVC.MV_USB_DEVICE:
                dev_dict["type"] = "USB"
                dev_dict["model"] = ''.join(chr(b) for b in dev_info.SpecialInfo.stUsb3VInfo.chModelName if b != 0)
                dev_dict["sn"] = ''.join(chr(b) for b in dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber if b != 0)

            devices.append(dev_dict)

        return devices

    # ==================== 初始化与连接 ====================
    def connect_by_ip(self, ip_str):
        """通过 IP 连接相机 (通常在 UI 选中下拉框后调用)"""
        if self.is_init:
            return True

        self.target_ip = ip_str
        devices = self.enum_devices()

        # 匹配 IP 对应的设备索引
        target_index = -1
        for dev in devices:
            if dev["ip"] == self.target_ip:
                target_index = dev["index"]
                break

        if target_index == -1:
            self.log_error(f"未找到 IP 为 {self.target_ip} 的相机")
            return False

        # 重新获取设备信息指针
        stDeviceList = MVC.MV_CC_DEVICE_INFO_LIST()
        MVC.MvCamera.MV_CC_EnumDevices(MVC.MV_GIGE_DEVICE | MVC.MV_USB_DEVICE, stDeviceList)
        dev_info = cast(stDeviceList.pDeviceInfo[target_index], POINTER(MVC.MV_CC_DEVICE_INFO)).contents

        # 创建并打开句柄
        self.cam = MVC.MvCamera()
        ret = self.cam.MV_CC_CreateHandle(dev_info)
        if ret != MVC.MV_OK: return False

        ret = self.cam.MV_CC_OpenDevice(MVC.MV_ACCESS_Exclusive, 0)
        if ret != MVC.MV_OK:
            self.log_error("打开设备失败", ret)
            return False

        self.is_init = True
        self.log_success(f"相机 {self.target_ip} 连接成功")

        # 默认设置最优取流包大小 (网口相机必须)
        if dev_info.nTLayerType == MVC.MV_GIGE_DEVICE:
            self.cam.MV_CC_SetIntValue("GevSCPSPacketSize", self.cam.MV_CC_GetOptimalPacketSize())

        return True

    # ==================== 相机核心参数读写 ====================
    def set_exposure(self, exposure_time_us):
        """设置曝光时间 (微秒)"""
        if not self.is_init: return False
        self.cam.MV_CC_SetEnumValue("ExposureAuto", MVC.MV_EXPOSURE_AUTO_MODE_OFF)  # 必须先关自动曝光
        ret = self.cam.MV_CC_SetFloatValue("ExposureTime", float(exposure_time_us))
        return ret == MVC.MV_OK

    def get_exposure(self):
        """获取当前曝光时间"""
        if not self.is_init: return 0.0
        stFloatParam = MVC.MVCC_FLOATVALUE()
        ret = self.cam.MV_CC_GetFloatValue("ExposureTime", stFloatParam)
        return stFloatParam.fCurValue if ret == MVC.MV_OK else 0.0

    def set_gain(self, gain_value):
        """设置增益"""
        if not self.is_init: return False
        self.cam.MV_CC_SetEnumValue("GainAuto", MVC.MV_GAIN_MODE_OFF)
        ret = self.cam.MV_CC_SetFloatValue("Gain", float(gain_value))
        return ret == MVC.MV_OK

    def get_gain(self):
        """获取当前增益"""
        if not self.is_init: return 0.0
        stFloatParam = MVC.MVCC_FLOATVALUE()
        ret = self.cam.MV_CC_GetFloatValue("Gain", stFloatParam)
        return stFloatParam.fCurValue if ret == MVC.MV_OK else 0.0

    # ==================== 触发模式控制 ====================
    def set_trigger_mode(self, mode="continuous"):
        """
        设置触发模式
        :param mode: "continuous" (连续视频流), "software" (软触发), "hardware" (硬触发)
        """
        if not self.is_init: return False

        if mode == "continuous":
            ret = self.cam.MV_CC_SetEnumValue("TriggerMode", MVC.MV_TRIGGER_MODE_OFF)
            self.log_info("已切换为: 连续视频流模式")

        elif mode == "software":
            self.cam.MV_CC_SetEnumValue("TriggerMode", MVC.MV_TRIGGER_MODE_ON)
            ret = self.cam.MV_CC_SetEnumValue("TriggerSource", MVC.MV_TRIGGER_SOURCE_SOFTWARE)
            self.log_info("已切换为: 软件触发模式")

        elif mode == "hardware":
            self.cam.MV_CC_SetEnumValue("TriggerMode", MVC.MV_TRIGGER_MODE_ON)
            # 默认使用 Line0 作为硬触发输入源（根据实际接线可改为 Line1/Line2）
            ret = self.cam.MV_CC_SetEnumValue("TriggerSource", MVC.MV_TRIGGER_SOURCE_LINE0)
            self.log_info("已切换为: 硬件外触发模式 (Line0)")

        return ret == MVC.MV_OK

    # ==================== 高级工业级功能扩展 ====================
    def set_roi(self, width, height, offset_x=0, offset_y=0):
        """设置图像分辨率(ROI区域)。注意：大部分相机在修改分辨率时，必须先停止取流！"""
        if not self.is_init: return False
        was_grabbing = self.is_grabbing
        if was_grabbing:
            self.stop_grab()

        try:
            # 顺序很重要：先设 Offset 为 0，再设宽高，最后设期望的 Offset，防止超出边界报错
            self.cam.MV_CC_SetIntValue("OffsetX", 0)
            self.cam.MV_CC_SetIntValue("OffsetY", 0)

            ret_w = self.cam.MV_CC_SetIntValue("Width", int(width))
            ret_h = self.cam.MV_CC_SetIntValue("Height", int(height))
            ret_x = self.cam.MV_CC_SetIntValue("OffsetX", int(offset_x))
            ret_y = self.cam.MV_CC_SetIntValue("OffsetY", int(offset_y))

            if ret_w == MVC.MV_OK and ret_h == MVC.MV_OK:
                self.log_success(f"ROI 设置成功: {width}x{height} 偏移({offset_x},{offset_y})")
                success = True
            else:
                self.log_error("ROI 设置失败，请检查参数是否为相机支持的步进值(通常为4或8的倍数)")
                success = False
        except Exception as e:
            self.log_error(f"ROI 设置异常: {e}")
            success = False

        if was_grabbing:
            self.start_grab()
        return success

    def set_framerate(self, fps):
        """设置采集帧率。fps<=0 表示关闭帧率限制，全速采集"""
        if not self.is_init: return False
        if fps <= 0:
            ret = self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", False)
            self.log_info("已关闭帧率限制，相机将全速运行")
            return ret == MVC.MV_OK
        else:
            self.cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            ret = self.cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(fps))
            if ret == MVC.MV_OK:
                self.log_success(f"帧率已限制为: {fps} FPS")
            else:
                self.log_error("帧率设置失败，可能超出了当前曝光时间允许的最大上限")
            return ret == MVC.MV_OK

    def set_trigger_delay(self, delay_us):
        """设置硬件触发延迟时间 (微秒)"""
        if not self.is_init: return False
        ret = self.cam.MV_CC_SetFloatValue("TriggerDelay", float(delay_us))
        if ret == MVC.MV_OK:
            self.log_success(f"触发延迟已设置为: {delay_us} us")
        return ret == MVC.MV_OK

    def set_white_balance(self, auto=True, r_ratio=1024, g_ratio=1024, b_ratio=1024):
        """设置白平衡 (仅彩色相机有效)"""
        if not self.is_init: return False
        if auto:
            ret = self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", MVC.MV_BALANCEWHITE_AUTO_CONTINUOUS)
            self.log_info("已开启连续自动白平衡")
            return ret == MVC.MV_OK
        else:
            self.cam.MV_CC_SetEnumValue("BalanceWhiteAuto", MVC.MV_BALANCEWHITE_AUTO_OFF)
            self.cam.MV_CC_SetEnumValue("BalanceRatioSelector", 0)  # Red
            self.cam.MV_CC_SetIntValue("BalanceRatio", int(r_ratio))
            self.cam.MV_CC_SetEnumValue("BalanceRatioSelector", 1)  # Green
            self.cam.MV_CC_SetIntValue("BalanceRatio", int(g_ratio))
            self.cam.MV_CC_SetEnumValue("BalanceRatioSelector", 2)  # Blue
            ret = self.cam.MV_CC_SetIntValue("BalanceRatio", int(b_ratio))
            self.log_success(f"手动白平衡已设置 R:{r_ratio} G:{g_ratio} B:{b_ratio}")
            return ret == MVC.MV_OK

    def set_heartbeat_timeout(self, timeout_ms=60000):
        """设置网口相机心跳超时时间(毫秒)。默认60秒，防止打断点Debug时相机掉线"""
        if not self.is_init: return False
        ret = self.cam.MV_CC_SetIntValue("GevHeartbeatTimeout", int(timeout_ms))
        if ret == MVC.MV_OK:
            self.log_info(f"心跳超时已设置为 {timeout_ms} ms (防掉线 Debug 模式)")
        return ret == MVC.MV_OK

    # ==================== 取流控制 ====================
    def start_grab(self):
        """开始取流"""
        if not self.is_init or self.is_grabbing: return True
        ret = self.cam.MV_CC_StartGrabbing()
        if ret == MVC.MV_OK:
            self.is_grabbing = True
            return True
        return False

    def stop_grab(self):
        """停止取流"""
        if self.is_grabbing:
            self.cam.MV_CC_StopGrabbing()
            self.is_grabbing = False

    def trigger_software(self):
        """发送软触发命令"""
        if not self.is_grabbing: return False
        ret = self.cam.MV_CC_SetCommandValue("TriggerSoftware")
        return ret == MVC.MV_OK

    def get_frame(self, timeout_ms=3000):
        """获取一帧图像 (统一接口，自动处理黑白/Bayer/RGB数据与 NumPy 维度的转换)"""
        if not self.is_grabbing:
            return None

        stFrame = MVC.MV_FRAME_OUT()
        ret = self.cam.MV_CC_GetImageBuffer(stFrame, timeout_ms)
        if ret != MVC.MV_OK:
            return None  # 超时或取流失败

        w = stFrame.stFrameInfo.nWidth
        h = stFrame.stFrameInfo.nHeight
        pixel_type = stFrame.stFrameInfo.enPixelType
        data_len = stFrame.stFrameInfo.nFrameLen
        p_buf = stFrame.pBufAddr

        if p_buf is None or p_buf == 0:
            self.cam.MV_CC_FreeImageBuffer(stFrame)
            return None

        img_bgr = None
        try:
            # 将内存指针转换为 numpy 一维数组
            p_data = cast(p_buf, POINTER(c_ubyte))
            img_np = np.frombuffer((c_ubyte * data_len).from_address(addressof(p_data.contents)), dtype=np.uint8)

            # ======== 核心：根据像素格式分配 shape 并转换颜色空间 ========
            if pixel_type == MVC.PixelType_Gvsp_Mono8:
                img_np = img_np.reshape(h, w)
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)

            elif pixel_type in [MVC.PixelType_Gvsp_BayerRG8, MVC.PixelType_Gvsp_BayerGR8,
                                MVC.PixelType_Gvsp_BayerGB8, MVC.PixelType_Gvsp_BayerBG8]:
                img_np = img_np.reshape(h, w)
                bayer_code = {
                    MVC.PixelType_Gvsp_BayerRG8: cv2.COLOR_BayerRG2BGR,
                    MVC.PixelType_Gvsp_BayerGR8: cv2.COLOR_BayerGR2BGR,
                    MVC.PixelType_Gvsp_BayerGB8: cv2.COLOR_BayerGB2BGR,
                    MVC.PixelType_Gvsp_BayerBG8: cv2.COLOR_BayerBG2BGR,
                }.get(pixel_type, cv2.COLOR_BayerBG2BGR)
                img_bgr = cv2.cvtColor(img_np, bayer_code)

            elif pixel_type in [MVC.PixelType_Gvsp_RGB8_Packed, MVC.PixelType_Gvsp_BGR8_Packed]:
                img_np = img_np.reshape(h, w, 3)  # 彩色相机：3通道
                img_bgr = cv2.cvtColor(img_np,
                                       cv2.COLOR_RGB2BGR) if pixel_type == MVC.PixelType_Gvsp_RGB8_Packed else img_np.copy()

            else:
                self.log_error(f"暂不支持的像素格式: 0x{pixel_type:08X}")

        except Exception as e:
            self.log_error(f"图像转换失败: {e}")

        finally:
            # 【关键】必须释放底层图像缓存
            self.cam.MV_CC_FreeImageBuffer(stFrame)

        return img_bgr

    # ==================== 关闭与销毁 ====================
    def close(self):
        if self.cam:
            self.stop_grab()
            self.cam.MV_CC_CloseDevice()
            self.cam.MV_CC_DestroyHandle()
        MVC.MvCamera.MV_CC_Finalize()
        self.is_init = False
        self.log_info("相机已安全关闭")