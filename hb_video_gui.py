# -*- coding: utf-8 -*-
"""
hb_video_gui.py - J6B 视频流 GUI 显示

使用 tkinter + OpenCV 实现:
  - 连接管理 (IP/端口输入)
  - 实时视频显示
  - FPS 统计
  - 帧信息面板
  - 截图保存

依赖:
  pip install opencv-python numpy pillow
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

import numpy as np
from PIL import Image, ImageTk

from hb_video_client import HBVideoClient
from hb_protocol import DEFAULT_PORT


class HBVideoGUI:
    """
    J6B 视频流 GUI 客户端.
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J6B Video Player - PC 客户端")
        self.root.geometry("1280x800")
        self.root.minsize(960, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 客户端实例
        self.client: HBVideoClient | None = None

        # 当前帧
        self._current_frame: np.ndarray | None = None
        self._current_info: dict | None = None
        self._frame_lock = threading.Lock()

        # FPS 统计
        self._fps_start_time = time.time()
        self._fps_frame_count = 0
        self._fps_value = 0.0

        # 截图
        self._snapshot_count = 0
        self._snapshot_dir = "./snapshots"

        # 构建 UI
        self._build_ui()

        # 定时刷新画面 (30ms ≈ 33fps)
        self._update_display()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        """构建完整的 GUI 界面."""
        # 主框架
        main_frame = ttk.Frame(self.root, padding=4)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---- 顶部: 控制面板 ----
        self._build_control_panel(main_frame)

        # ---- 中间: 视频显示 + 信息面板 ----
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        # 视频显示画布
        self._build_video_panel(content_frame)

        # 右侧信息面板
        self._build_info_panel(content_frame)

        # ---- 底部: 状态栏 ----
        self._build_status_bar(main_frame)

    def _build_control_panel(self, parent):
        """构建控制面板."""
        panel = ttk.LabelFrame(parent, text="控制面板", padding=6)
        panel.pack(fill=tk.X, pady=(0, 4))

        # 第一行: 连接设置
        row1 = ttk.Frame(panel)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="设备 IP:").pack(side=tk.LEFT, padx=2)
        self.ip_entry = ttk.Entry(row1, width=16)
        self.ip_entry.pack(side=tk.LEFT, padx=2)
        self.ip_entry.insert(0, "192.168.1.100")

        ttk.Label(row1, text="端口:").pack(side=tk.LEFT, padx=(10, 2))
        self.port_entry = ttk.Entry(row1, width=8)
        self.port_entry.pack(side=tk.LEFT, padx=2)
        self.port_entry.insert(0, str(DEFAULT_PORT))

        self.connect_btn = ttk.Button(row1, text="连接", command=self._toggle_connection)
        self.connect_btn.pack(side=tk.LEFT, padx=(10, 2))

        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.snapshot_btn = ttk.Button(
            row1, text="截图保存", command=self._save_snapshot, state=tk.DISABLED
        )
        self.snapshot_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(row1, text="选择保存目录", command=self._select_snapshot_dir).pack(
            side=tk.LEFT, padx=2
        )

        self.fps_label = ttk.Label(row1, text="FPS: --")
        self.fps_label.pack(side=tk.RIGHT, padx=10)

    def _build_video_panel(self, parent):
        """构建视频显示面板."""
        self.video_frame = ttk.LabelFrame(parent, text="视频画面", padding=2)
        self.video_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        self.video_canvas = tk.Canvas(
            self.video_frame, bg="black", highlightthickness=0
        )
        self.video_canvas.pack(fill=tk.BOTH, expand=True)

        # 无信号提示文字
        self.no_signal_text = self.video_canvas.create_text(
            400, 300, text="等待连接...\n请输入设备 IP 并点击「连接」",
            fill="gray", font=("DejaVu Sans", 14), justify=tk.CENTER
        )

        self._photo_image: ImageTk.PhotoImage | None = None

    def _build_info_panel(self, parent):
        """构建信息面板."""
        panel = ttk.LabelFrame(parent, text="帧信息", padding=6, width=260)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 0))
        panel.pack_propagate(False)

        self.info_text = tk.Text(
            panel, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10), bg="#f5f5f5", relief=tk.FLAT,
            height=20
        )
        self.info_text.pack(fill=tk.BOTH, expand=True)

        # 日志区域
        log_frame = ttk.LabelFrame(panel, text="日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.log_text = tk.Text(
            log_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            relief=tk.FLAT, height=8
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

    def _build_status_bar(self, parent):
        """构建状态栏."""
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(
            parent, textvariable=self.status_var,
            relief=tk.SUNKEN, anchor=tk.W, padding=(4, 2)
        )
        status_bar.pack(fill=tk.X)

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _toggle_connection(self):
        """切换连接状态."""
        if self.client and self.client.is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """连接到设备."""
        host = self.ip_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
        except ValueError:
            messagebox.showerror("错误", "端口号格式不正确")
            return

        if not host:
            messagebox.showerror("错误", "请输入设备 IP 地址")
            return

        self.connect_btn.config(state=tk.DISABLED, text="连接中...")
        self.status_var.set(f"正在连接 {host}:{port} ...")
        self._log(f"正在连接 {host}:{port} ...")

        # 在后台线程中连接
        def do_connect():
            client = HBVideoClient(host=host, port=port, enable_yuv=True)
            client.register_frame_callback(self._on_frame_received)
            if client.start():
                self.client = client
                self.root.after(0, self._on_connected, host, port)
            else:
                self.root.after(0, self._on_connect_failed)

        threading.Thread(target=do_connect, daemon=True).start()

    def _on_connected(self, host, port):
        """连接成功回调 (主线程)."""
        self.connect_btn.config(state=tk.NORMAL, text="断开")
        self.snapshot_btn.config(state=tk.NORMAL)
        self.status_var.set(f"已连接 {host}:{port}")
        self._log(f"✓ 已连接到 {host}:{port}")
        self._log("等待视频流数据...")

        # 清除无信号提示
        self.video_canvas.delete(self.no_signal_text)

    def _on_connect_failed(self):
        """连接失败回调 (主线程)."""
        self.connect_btn.config(state=tk.NORMAL, text="连接")
        self.status_var.set("连接失败")
        self._log("✗ 连接失败，请检查设备 IP 和端口")
        messagebox.showerror("连接失败", "无法连接到设备，请检查:\n"
                             "1. 设备 IP 地址是否正确\n"
                             "2. 设备端 hb_tool_server 是否运行\n"
                             "3. 网络是否通畅")

    def _disconnect(self):
        """断开连接."""
        if self.client:
            self.client.stop()
            self.client = None
        self.connect_btn.config(state=tk.NORMAL, text="连接")
        self.snapshot_btn.config(state=tk.DISABLED)
        self.status_var.set("已断开")
        self._log("已断开连接")
        self.fps_label.config(text="FPS: --")

        # 显示无信号
        with self._frame_lock:
            self._current_frame = None
            self._current_info = None
        self.video_canvas.delete("all")
        self.no_signal_text = self.video_canvas.create_text(
            400, 300, text="已断开\n点击「连接」重新开始",
            fill="gray", font=("DejaVu Sans", 14), justify=tk.CENTER
        )

    # ------------------------------------------------------------------
    # 帧回调 (接收线程中调用)
    # ------------------------------------------------------------------

    def _on_frame_received(self, frame_info: dict, bgr_image: np.ndarray):
        """
        接收到新帧.

        Args:
            frame_info: 帧信息字典
            bgr_image:  BGR 格式图像
        """
        with self._frame_lock:
            self._current_frame = bgr_image.copy()
            self._current_info = frame_info

        # FPS 统计
        self._fps_frame_count += 1
        now = time.time()
        elapsed = now - self._fps_start_time
        if elapsed >= 1.0:
            self._fps_value = self._fps_frame_count / elapsed
            self._fps_frame_count = 0
            self._fps_start_time = now

    # ------------------------------------------------------------------
    # 画面刷新 (主线程定时器)
    # ------------------------------------------------------------------

    def _update_display(self):
        """定时刷新画面 (30ms)."""
        frame = None
        info = None
        with self._frame_lock:
            if self._current_frame is not None:
                frame = self._current_frame.copy()
                info = dict(self._current_info) if self._current_info else None

        if frame is not None:
            self._render_frame(frame, info)

        self.root.after(30, self._update_display)

    def _render_frame(self, bgr_image: np.ndarray, frame_info: dict | None):
        """
        渲染帧到画布.

        Args:
            bgr_image:  BGR 格式图像
            frame_info: 帧信息
        """
        canvas_w = self.video_canvas.winfo_width()
        canvas_h = self.video_canvas.winfo_height()

        if canvas_w < 10 or canvas_h < 10:
            return  # 窗口尚未初始化

        h, w = bgr_image.shape[:2]
        if h == 0 or w == 0:
            return

        # 计算缩放比例 (保持宽高比)
        scale = min(canvas_w / w, canvas_h / h)
        new_w, new_h = int(w * scale), int(h * scale)

        # BGR -> RGB -> PIL -> ImageTk
        rgb = bgr_image[..., ::-1]  # BGR to RGB
        pil_img = Image.fromarray(rgb)
        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)

        self._photo_image = ImageTk.PhotoImage(pil_img)

        # 居中显示
        x = (canvas_w - new_w) // 2
        y = (canvas_h - new_h) // 2

        self.video_canvas.delete("all")
        self.video_canvas.create_image(x, y, anchor=tk.NW, image=self._photo_image)

        # 叠加 FPS 文字
        self.video_canvas.create_text(
            10, 10, text=f"FPS: {self._fps_value:.1f}",
            anchor=tk.NW, fill="lime", font=("Consolas", 12, "bold")
        )

        # 更新 FPS 标签
        self.fps_label.config(text=f"FPS: {self._fps_value:.1f}")

        # 更新信息面板
        if frame_info:
            self._update_info_panel(frame_info)

    def _update_info_panel(self, frame_info: dict):
        """更新帧信息面板."""
        info_lines = [
            f"帧类型:   {frame_info.get('type_name', '?')}",
            f"图像格式: {frame_info.get('format', '?')}",
            f"分辨率:   {frame_info['width']} × {frame_info['height']}",
            f"行步长:   {frame_info['stride']}",
            f"帧序号:   #{frame_info['frame_id']}",
            f"PIPE ID:  {frame_info['pipe_id']}",
            f"CHN ID:   {frame_info['chn_id']}",
            f"数据长度: {frame_info['data_len']} bytes",
            f"芯片版本: J{frame_info['chip_ver']}",
        ]
        text = "\n".join(info_lines)

        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", text)
        self.info_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 截图保存
    # ------------------------------------------------------------------

    def _save_snapshot(self):
        """保存当前帧为图片."""
        with self._frame_lock:
            if self._current_frame is None:
                messagebox.showinfo("提示", "当前没有画面可保存")
                return
            frame = self._current_frame.copy()

        os.makedirs(self._snapshot_dir, exist_ok=True)
        self._snapshot_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self._snapshot_dir,
            f"snapshot_{timestamp}_{self._snapshot_count:04d}.jpg"
        )

        # BGR -> RGB -> PIL
        rgb = frame[..., ::-1]
        pil_img = Image.fromarray(rgb)
        pil_img.save(filename, quality=95)

        self._log(f"截图已保存: {filename}")
        self.status_var.set(f"截图已保存: {os.path.basename(filename)}")

    def _select_snapshot_dir(self):
        """选择截图保存目录."""
        directory = filedialog.askdirectory(
            title="选择截图保存目录",
            initialdir=self._snapshot_dir,
        )
        if directory:
            self._snapshot_dir = directory
            self._log(f"截图目录: {directory}")

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _log(self, message: str):
        """添加日志消息."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"

        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def _on_close(self):
        """窗口关闭处理."""
        if self.client and self.client.is_connected:
            if messagebox.askyesno("确认退出", "正在接收视频流，确定要退出吗?"):
                self.client.stop()
                self.root.destroy()
        else:
            self.root.destroy()

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------

    def run(self):
        """启动 GUI 主循环."""
        self.root.mainloop()


# ============================================================================
# 入口
# ============================================================================

def main():
    """程序入口."""
    app = HBVideoGUI()
    app.run()


if __name__ == "__main__":
    main()