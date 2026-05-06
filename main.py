# -*- coding: utf-8 -*-
import sys
import os
import cv2
import numpy as np
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel, QComboBox,
                               QGroupBox, QRadioButton, QLineEdit, QMessageBox,
                               QSplitter, QFrame, QStatusBar, QCheckBox)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

# 导入我们封装好的相机类
from hik_camera import HikCamera

# ==================== 纯白专业工业风样式表 ====================
STYLE_SHEET = """
QMainWindow { 
    background-color: #f5f6f7; 
}
QGroupBox {
    font-weight: bold; 
    border: 1px solid #cccccc;
    border-radius: 4px; 
    margin-top: 12px; 
    padding-top: 15px; 
    background-color: #ffffff;
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    left: 10px; 
    padding: 0 5px; 
    color: #333333; 
}
QPushButton {
    background-color: #ffffff; 
    border: 1px solid #bbbbbb; 
    border-radius: 3px; 
    padding: 6px;
    color: #333333;
}
QPushButton:hover { 
    background-color: #e6f7ff; 
    border-color: #1890ff; 
    color: #1890ff;
}
QPushButton#btn_connect { 
    background-color: #e6f7ff; 
    border: 1px solid #1890ff; 
    color: #1890ff; 
    font-weight: bold; 
}
QPushButton#btn_save { 
    background-color: #f6ffed; 
    border: 1px solid #52c41a; 
    color: #52c41a; 
    font-weight: bold; 
}
QPushButton#btn_disconnect {
    color: #ff4d4f;
}
QLineEdit { 
    border: 1px solid #d9d9d9; 
    padding: 4px; 
    border-radius: 2px; 
    background: #ffffff; 
}
QLineEdit:focus {
    border: 1px solid #1890ff;
}
QLabel { 
    color: #333333; 
}
"""


class ScalingImageLabel(QLabel):
    """自定义Label，实现图像的实时平滑缩放，解决右侧无法缩放的问题"""

    def __init__(self):
        super().__init__("等待视频流输入...")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(400, 300)
        self._pixmap = None

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update_display()

    def update_display(self):
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            super().setPixmap(scaled)

    def resizeEvent(self, event):
        self.update_display()
        super().resizeEvent(event)


class GrabThread(QThread):
    """独立的取流子线程"""
    signal_image_ready = Signal(np.ndarray)

    def __init__(self, cam):
        super().__init__()
        self.cam = cam
        self.active = False

    def run(self):
        self.active = True
        self.cam.start_grab()
        while self.active:
            frame = self.cam.get_frame(1000)
            if frame is not None:
                self.signal_image_ready.emit(frame)

    def stop(self):
        self.active = False
        self.quit()
        self.wait()
        self.cam.stop_grab()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("海康测试")
        self.resize(1250, 850)
        self.setStyleSheet(STYLE_SHEET)

        self.cam = HikCamera()
        self.grab_thread = None
        self.current_frame = None

        self.init_ui()
        self.update_ui_state(False)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # 使用 QSplitter 实现左右界面的自由拖拽缩放
        splitter = QSplitter(Qt.Horizontal)

        # ================= 左侧控制面板 =================
        left_panel = QFrame()
        left_panel.setMinimumWidth(320)
        left_panel.setMaximumWidth(450)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        # 1. 设备连接
        g1 = QGroupBox("📡 相机连接")
        v1 = QVBoxLayout(g1)
        self.btn_enum = QPushButton("🔍 搜索可用设备")
        self.btn_enum.setToolTip("发送广播寻找局域网内的工业相机")
        self.combo = QComboBox()
        self.combo.setStyleSheet("padding: 4px; border: 1px solid #ccc; background: white;")

        h_conn = QHBoxLayout()
        self.btn_conn = QPushButton("🔗 连接相机")
        self.btn_conn.setObjectName("btn_connect")
        self.btn_close = QPushButton("❌ 断开")
        self.btn_close.setObjectName("btn_disconnect")
        h_conn.addWidget(self.btn_conn)
        h_conn.addWidget(self.btn_close)

        v1.addWidget(self.btn_enum)
        v1.addWidget(self.combo)
        v1.addLayout(h_conn)

        # 2. 模式与触发
        g2 = QGroupBox("🕹️ 模式与触发")
        v2 = QVBoxLayout(g2)
        h_radio = QHBoxLayout()
        self.r_cont = QRadioButton("连续预览")
        self.r_soft = QRadioButton("软触发")
        self.r_hard = QRadioButton("硬触发")
        self.r_cont.setChecked(True)
        h_radio.addWidget(self.r_cont)
        h_radio.addWidget(self.r_soft)
        h_radio.addWidget(self.r_hard)

        self.btn_trig = QPushButton("⚡ 手动发送软触发指令")
        self.btn_save = QPushButton("💾 保存当前帧至本地")
        self.btn_save.setObjectName("btn_save")
        self.btn_save.setToolTip("将右侧画面保存为原始分辨率的 BMP 图片")

        v2.addLayout(h_radio)
        v2.addWidget(self.btn_trig)
        v2.addWidget(self.btn_save)

        # 3. 基础参数
        g3 = QGroupBox("⚙️ 基础参数")
        v3 = QVBoxLayout(g3)
        h_exp = QHBoxLayout()
        self.ed_exp = QLineEdit()
        self.btn_set_exp = QPushButton("设曝光(μs)")
        h_exp.addWidget(QLabel("曝光:"))
        h_exp.addWidget(self.ed_exp)
        h_exp.addWidget(self.btn_set_exp)

        h_gain = QHBoxLayout()
        self.ed_gain = QLineEdit()
        self.btn_set_gain = QPushButton("设增益(dB)")
        h_gain.addWidget(QLabel("增益:"))
        h_gain.addWidget(self.ed_gain)
        h_gain.addWidget(self.btn_set_gain)

        v3.addLayout(h_exp)
        v3.addLayout(h_gain)

        # 4. 高级参数 (ROI, 帧率, 延迟, 白平衡)
        g4 = QGroupBox("🛠️ 高级与 ROI (需连接后操作)")
        v4 = QVBoxLayout(g4)

        h_roi1 = QHBoxLayout()
        self.ed_w = QLineEdit("2592")
        self.ed_h = QLineEdit("1944")
        h_roi1.addWidget(QLabel("宽:"))
        h_roi1.addWidget(self.ed_w)
        h_roi1.addWidget(QLabel("高:"))
        h_roi1.addWidget(self.ed_h)

        h_roi2 = QHBoxLayout()
        self.ed_ox = QLineEdit("0")
        self.ed_oy = QLineEdit("0")
        h_roi2.addWidget(QLabel("偏移X:"))
        h_roi2.addWidget(self.ed_ox)
        h_roi2.addWidget(QLabel("偏移Y:"))
        h_roi2.addWidget(self.ed_oy)

        self.btn_set_roi = QPushButton("应用分辨率 / ROI 裁剪")
        self.btn_set_roi.setToolTip("裁剪图像可有效提升相机最高帧率。")

        h_fps = QHBoxLayout()
        self.ed_fps = QLineEdit("0")
        self.btn_set_fps = QPushButton("设最高帧率")
        self.btn_set_fps.setToolTip("填入 0 表示不限制帧率；填入数值可防止千兆网卡带宽占满。")
        h_fps.addWidget(self.ed_fps)
        h_fps.addWidget(self.btn_set_fps)

        h_delay = QHBoxLayout()
        self.ed_delay = QLineEdit("0")
        self.btn_set_delay = QPushButton("设触发延迟")
        self.btn_set_delay.setToolTip("硬触发模式下，收到硬件信号后延迟多少微秒再拍照。")
        h_delay.addWidget(self.ed_delay)
        h_delay.addWidget(self.btn_set_delay)

        self.chk_wb = QCheckBox("自动白平衡 (彩色相机)")
        self.chk_wb.setToolTip("消除工厂环境光源引起的偏色现象。")

        v4.addLayout(h_roi1)
        v4.addLayout(h_roi2)
        v4.addWidget(self.btn_set_roi)
        v4.addLayout(h_fps)
        v4.addLayout(h_delay)
        v4.addWidget(self.chk_wb)

        # 5. 系统设置
        g5 = QGroupBox("🛡️ 开发者选项")
        v5 = QVBoxLayout(g5)
        h_hb = QHBoxLayout()
        self.ed_hb = QLineEdit("60000")
        self.btn_set_hb = QPushButton("应用心跳超时(ms)")
        self.btn_set_hb.setToolTip("防止打断点调试时相机强制掉线。建议设为 60000 (1分钟)。")
        h_hb.addWidget(QLabel("心跳:"))
        h_hb.addWidget(self.ed_hb)
        h_hb.addWidget(self.btn_set_hb)
        v5.addLayout(h_hb)

        # 将所有组装入左侧布局
        for g in [g1, g2, g3, g4, g5]:
            left_layout.addWidget(g)
        left_layout.addStretch()  # 底部弹簧

        # ================= 右侧显示面板 =================
        self.display = ScalingImageLabel()
        self.display.setStyleSheet(
            "background-color: #2b2b2b; color: #888888; border: 1px solid #ccc; font-size: 16px;")

        # 装入分离器
        splitter.addWidget(left_panel)
        splitter.addWidget(self.display)
        splitter.setStretchFactor(1, 1)  # 让右侧图像区默认占据更大空间

        layout.addWidget(splitter)

        # 底部状态栏
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("系统就绪 | 等待枚举设备...")

        # ================= 绑定事件信号 =================
        self.btn_enum.clicked.connect(self.on_enum)
        self.btn_conn.clicked.connect(self.on_connect)
        self.btn_close.clicked.connect(self.on_disconnect)

        self.btn_trig.clicked.connect(self.on_trigger)
        self.btn_save.clicked.connect(self.on_save)

        self.btn_set_exp.clicked.connect(self.on_set_exp)
        self.btn_set_gain.clicked.connect(self.on_set_gain)
        self.btn_set_roi.clicked.connect(self.on_set_roi)
        self.btn_set_fps.clicked.connect(self.on_set_fps)
        self.btn_set_delay.clicked.connect(self.on_set_delay)
        self.btn_set_hb.clicked.connect(self.on_set_hb)

        self.chk_wb.stateChanged.connect(self.on_wb_changed)
        for r in [self.r_cont, self.r_soft, self.r_hard]:
            r.toggled.connect(self.on_mode_change)

    # ------------------- 核心逻辑处理 -------------------
    def update_ui_state(self, is_connected):
        """统一管理组件的启用/禁用状态"""
        self.btn_conn.setEnabled(not is_connected)
        self.btn_enum.setEnabled(not is_connected)
        self.combo.setEnabled(not is_connected)

        self.btn_close.setEnabled(is_connected)
        for w in [self.r_cont, self.r_soft, self.r_hard, self.btn_save,
                  self.btn_set_exp, self.btn_set_gain, self.btn_set_roi,
                  self.btn_set_fps, self.btn_set_delay, self.btn_set_hb, self.chk_wb]:
            w.setEnabled(is_connected)

        self.btn_trig.setEnabled(is_connected and self.r_soft.isChecked())

    @Slot()
    def on_enum(self):
        self.combo.clear()
        devs = HikCamera.enum_devices()
        for d in devs:
            self.combo.addItem(f"{d['ip']} ({d['model']})", d['ip'])
        self.statusBar().showMessage(f"扫描完毕：共发现 {len(devs)} 台相机")

    @Slot()
    def on_connect(self):
        ip = self.combo.currentData()
        if not ip: return

        if self.cam.connect_by_ip(ip):
            self.update_ui_state(True)
            # 自动读取并回显当前的参数
            self.ed_exp.setText(f"{self.cam.get_exposure():.0f}")
            self.ed_gain.setText(f"{self.cam.get_gain():.1f}")

            self.on_mode_change()  # 应用当前的触发模式

            # 启动取流线程
            self.grab_thread = GrabThread(self.cam)
            self.grab_thread.signal_image_ready.connect(self.on_new_frame)
            self.grab_thread.start()
            self.statusBar().showMessage(f"连接成功: {ip}")
        else:
            QMessageBox.warning(self, "连接失败", "无法建立连接，请检查网线或 IP 设置！")

    @Slot()
    def on_disconnect(self):
        if self.grab_thread:
            self.grab_thread.stop()
            self.grab_thread = None
        self.cam.close()
        self.display.set_pixmap(QPixmap())
        self.display.setText("连接已断开")
        self.update_ui_state(False)
        self.statusBar().showMessage("设备已安全断开")

    @Slot()
    def on_mode_change(self):
        if not self.cam.is_init: return
        mode = "continuous" if self.r_cont.isChecked() else "software" if self.r_soft.isChecked() else "hardware"
        self.cam.set_trigger_mode(mode)
        self.btn_trig.setEnabled(mode == "software")

    @Slot()
    def on_trigger(self):
        self.cam.trigger_software()

    @Slot()
    def on_save(self):
        if self.current_frame is not None:
            save_dir = "./captured_images"
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, f"IMG_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bmp")
            cv2.imwrite(path, self.current_frame)
            self.statusBar().showMessage(f"原图已保存: {path}")
        else:
            QMessageBox.warning(self, "提示", "当前无画面可保存！")

    # ----- 参数设置槽函数 -----
    @Slot()
    def on_set_exp(self):
        if self.cam.set_exposure(self.ed_exp.text()):
            self.statusBar().showMessage(f"曝光时间已更新为 {self.ed_exp.text()} μs")

    @Slot()
    def on_set_gain(self):
        if self.cam.set_gain(self.ed_gain.text()):
            self.statusBar().showMessage(f"增益已更新为 {self.ed_gain.text()} dB")

    @Slot()
    def on_set_roi(self):
        w, h, ox, oy = self.ed_w.text(), self.ed_h.text(), self.ed_ox.text(), self.ed_oy.text()
        if self.cam.set_roi(w, h, ox, oy):
            self.statusBar().showMessage(f"ROI 设置成功：{w}x{h}，偏移({ox},{oy})")
        else:
            QMessageBox.warning(self, "错误", "ROI 设置失败，请确保相机在支持的数值步进内。")

    @Slot()
    def on_set_fps(self):
        if self.cam.set_framerate(float(self.ed_fps.text())):
            self.statusBar().showMessage("帧率限制已更新")

    @Slot()
    def on_set_delay(self):
        if self.cam.set_trigger_delay(self.ed_delay.text()):
            self.statusBar().showMessage(f"触发延迟已设为 {self.ed_delay.text()} μs")

    @Slot()
    def on_set_hb(self):
        if self.cam.set_heartbeat_timeout(self.ed_hb.text()):
            self.statusBar().showMessage(f"心跳超时设为 {self.ed_hb.text()} ms")

    @Slot()
    def on_wb_changed(self, state):
        self.cam.set_white_balance(state == Qt.Checked)

    @Slot(np.ndarray)
    def on_new_frame(self, frame):
        """接收底层的 numpy 数组并渲染"""
        self.current_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, c = rgb.shape
        # 创建 QImage，注意 bytesPerLine 参数必须是 w * c 才能防止图像扭曲
        qimg = QImage(rgb.data, w, h, w * c, QImage.Format_RGB888)
        self.display.set_pixmap(QPixmap.fromImage(qimg))

    def closeEvent(self, event):
        """窗口关闭时安全断开相机"""
        self.on_disconnect()
        event.accept()


if __name__ == "__main__":
    # 针对高分屏进行优化，防止界面错乱
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 强制使用现代风格

    win = MainWindow()
    win.show()
    sys.exit(app.exec())