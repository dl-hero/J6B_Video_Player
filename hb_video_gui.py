# -*- coding: utf-8 -*-
"""
hb_video_gui.py - J6B 视频流 GUI 显示 (多路视频支持)

功能:
  - 连接管理 (IP/端口输入)
  - 多路视频自动识别与切换 (下拉选择 pipe)
  - 实时视频显示 (单路大画面)
  - 各路 FPS 独立统计
  - 帧信息面板
  - 截图保存

依赖:
  pip install numpy pillow
  (tkinter 为 Python 标准库, 无需额外安装)
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from collections import defaultdict

import numpy as np
from PIL import Image, ImageTk

from hb_video_client import HBVideoClient
from hb_protocol import DEFAULT_PORT


class HBVideoGUI:
    """J6B 多路视频流 GUI 客户端."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J6B Video Player - 多路视频客户端")
        self.root.geometry("1400x900")
        self.root.minsize(1024, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 客户端实例
        self.client: HBVideoClient | None = None

        # 多路帧缓冲: pipe_id -> (bgr_image, frame_info)
        self._pipe_frames: dict[int, tuple[np.ndarray, dict]] = {}
        self._frame_lock = threading.Lock()

        # 各路 FPS 统计
        self._pipe_fps: dict[int, float] = {}
        self._pipe_fps_count: dict[int, int] = defaultdict(int)
        self._fps_start_time = time.time()

        # 当前选中的 pipe
        self._selected_pipe: int | None = None
        self._available_pipes: list[int] = []

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
        main_frame = ttk.Frame(self.root, padding=4)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---- 顶部: 控制面板 ----
        self._build_control_panel(main_frame)

        # ---- 中间: 视频显示 + 信息面板 ----
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self._build_video_panel(content_frame)
        self._build_info_panel(content_frame)

        # ---- 底部: 状态栏 ----
        self._build_status_bar(main_frame)

    def _build_control_panel(self, parent):
        """构建控制面板."""
        panel = ttk.LabelFrame(parent, text="控制面板", padding=6)
        panel.pack(fill=tk.X, pady=(0, 4))

        row1 = ttk.Frame(panel)
        row1.pack(fill=tk.X, pady=2)

        ttk.Label(row1, text="设备 IP:").pack(side=tk.LEFT, padx=2)
        self.ip_entry = ttk.Entry(row1, width=16)
        self.ip_entry.pack(side=tk.LEFT, padx=2)
        self.ip_entry.insert(0, "172.16.0.14")

        ttk.Label(row1, text="端口:").pack(side=tk.LEFT, padx=(10, 2))
        self.port_entry = ttk.Entry(row1, width=8)
        self.port_entry.pack(side=tk.LEFT, padx=2)
        self.port_entry.insert(0, str(DEFAULT_PORT))

        self.connect_btn = ttk.Button(row1, text="连接", command=self._toggle_connection)
        self.connect_btn.pack(side=tk.LEFT, padx=(10, 2))

        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        # 通道选择
        ttk.Label(row1, text="通道:").pack(side=tk.LEFT, padx=2)
        self.pipe_combo = ttk.Combobox(row1, values=[], state="readonly", width=8)
        self.pipe_combo.pack(side=tk.LEFT, padx=2)
        self.pipe_combo.set("全部")
        self.pipe_combo.bind("<<ComboboxSelected>>", self._on_pipe_selected)

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

        self.no_signal_text = self.video_canvas.create_text(
            400, 300, text="等待连接...\n请输入设备 IP 并点击「连接」",
            fill="gray", font=("DejaVu Sans", 14), justify=tk.CENTER
        )

        self._photo_image: ImageTk.PhotoImage | None = None

    def _build_info_panel(self, parent):
        """构建信息面板."""
        panel = ttk.LabelFrame(parent, text="通道信息", padding=6, width=280)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 0))
        panel.pack_propagate(False)

        # 各通道概况
        overview_frame = ttk.LabelFrame(panel, text="各通道概况", padding=4)
        overview_frame.pack(fill=tk.X, pady=(0, 4))

        self.overview_text = tk.Text(
            overview_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 9), bg="#f0f0f0", relief=tk.FLAT,
            height=8
        )
        self.overview_text.pack(fill=tk.X)

        # 当前帧详情
        detail_frame = ttk.LabelFrame(panel, text="当前帧详情", padding=4)
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.info_text = tk.Text(
            detail_frame, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 10), bg="#f5f5f5", relief=tk.FLAT,
            height=12
        )
        self.info_text.pack(fill=tk.BOTH, expand=True)

        # 日志区域
        log_frame = ttk.LabelFrame(panel, text="日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        log_container = ttk.Frame(log_frame)
        log_container.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_container, wrap=tk.WORD, state=tk.DISABLED,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            relief=tk.FLAT, height=6
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_container, command=self.log_text.yview)
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
        self.status_var.set(f"已连接 {host}:{port} | 等待视频流...")
        self._log(f"✓ 已连接到 {host}:{port}")
        self._log("等待视频流数据...")

        self.video_canvas.delete(self.no_signal_text)

    def _on_connect_failed(self):
        """连接失败回调 (主线程)."""
        self.connect_btn.config(state=tk.NORMAL, text="连接")
        self.status_var.set("连接失败")
        self._log("✗ 连接失败，请检查设备 IP 和端口")
        messagebox.showerror("连接失败", "无法连接到设备，请检查:\n"
                             "1. 设备 IP 地址是否正确\n"
                             "2. 设备端 camera_sample 是否运行\n"
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

        with self._frame_lock:
            self._pipe_frames.clear()
            self._available_pipes.clear()
        self._selected_pipe = None
        self.pipe_combo["values"] = []
        self.pipe_combo.set("全部")

        self.video_canvas.delete("all")
        self.no_signal_text = self.video_canvas.create_text(
            400, 300, text="已断开\n点击「连接」重新开始",
            fill="gray", font=("DejaVu Sans", 14), justify=tk.CENTER
        )

    # ------------------------------------------------------------------
    # 通道选择
    # ------------------------------------------------------------------

    def _on_pipe_selected(self, event=None):
        """通道下拉选择事件."""
        value = self.pipe_combo.get()
        if value == "全部":
            self._selected_pipe = None
        else:
            try:
                self._selected_pipe = int(value)
            except ValueError:
                self._selected_pipe = None

    def _update_pipe_combo(self):
        """更新通道下拉列表."""
        with self._frame_lock:
            current_pipes = sorted(self._available_pipes)

        if not current_pipes:
            return

        values = ["全部"] + [str(p) for p in current_pipes]
        current_values = list(self.pipe_combo["values"])

        if values != current_values:
            self.pipe_combo["values"] = values
            if self._selected_pipe is None and self.pipe_combo.get() != "全部":
                self.pipe_combo.set("全部")
            elif self._selected_pipe is not None:
                pipe_str = str(self._selected_pipe)
                if pipe_str in values:
                    self.pipe_combo.set(pipe_str)

    # ------------------------------------------------------------------
    # 帧回调 (接收线程中调用)
    # ------------------------------------------------------------------

    def _on_frame_received(self, frame_info: dict, bgr_image: np.ndarray):
        """
        接收到新帧. 按 pipe_id 分路存储.

        Args:
            frame_info: 帧信息字典
            bgr_image:  BGR 格式图像
        """
        pipe_id = frame_info['pipe_id']

        with self._frame_lock:
            # 深拷贝存储
            self._pipe_frames[pipe_id] = (bgr_image.copy(), dict(frame_info))

            # 跟踪可用 pipe
            if pipe_id not in self._available_pipes:
                self._available_pipes.append(pipe_id)

        # 各路 FPS 统计
        self._pipe_fps_count[pipe_id] = self._pipe_fps_count.get(pipe_id, 0) + 1

        # 全局 FPS 统计
        now = time.time()
        elapsed = now - self._fps_start_time
        if elapsed >= 1.0:
            # 更新各路 FPS
            for pid, count in self._pipe_fps_count.items():
                self._pipe_fps[pid] = count / elapsed
            self._pipe_fps_count.clear()
            self._fps_start_time = now

    # ------------------------------------------------------------------
    # 画面刷新 (主线程定时器)
    # ------------------------------------------------------------------

    def _update_display(self):
        """定时刷新画面 (30ms)."""
        # 更新通道下拉列表
        self._update_pipe_combo()

        # 获取要显示的帧
        frame = None
        info = None
        pipe_id = None

        with self._frame_lock:
            if self._selected_pipe is not None:
                # 显示指定通道
                if self._selected_pipe in self._pipe_frames:
                    frame, info = self._pipe_frames[self._selected_pipe]
                    frame = frame.copy()
                    info = dict(info) if info else None
                    pipe_id = self._selected_pipe
            elif self._pipe_frames:
                # "全部" 模式: 显示最新收到的帧
                pipe_id = max(self._pipe_frames.keys(),
                              key=lambda p: self._pipe_frames[p][1].get('frame_id', 0))
                frame, info = self._pipe_frames[pipe_id]
                frame = frame.copy()
                info = dict(info) if info else None

        if frame is not None:
            self._render_frame(frame, info, pipe_id)

        self._update_overview_panel()
        self.root.after(30, self._update_display)

    def _render_frame(self, bgr_image: np.ndarray, frame_info: dict | None, pipe_id: int):
        """渲染帧到画布."""
        canvas_w = self.video_canvas.winfo_width()
        canvas_h = self.video_canvas.winfo_height()

        if canvas_w < 10 or canvas_h < 10:
            return

        h, w = bgr_image.shape[:2]
        if h == 0 or w == 0:
            return

        # 计算缩放比例 (保持宽高比, 留边距给文字叠加)
        margin = 40
        scale = min((canvas_w - 20) / w, (canvas_h - margin) / h)
        new_w, new_h = int(w * scale), int(h * scale)

        # BGR -> RGB -> PIL -> ImageTk
        rgb = bgr_image[..., ::-1]
        pil_img = Image.fromarray(rgb)
        pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)

        self._photo_image = ImageTk.PhotoImage(pil_img)

        x = (canvas_w - new_w) // 2
        y = (canvas_h - new_h) // 2

        self.video_canvas.delete("all")
        self.video_canvas.create_image(x, y, anchor=tk.NW, image=self._photo_image)

        # 叠加信息
        fps = self._pipe_fps.get(pipe_id, 0)
        self.video_canvas.create_text(
            10, 10, text=f"Pipe {pipe_id} | FPS: {fps:.1f}",
            anchor=tk.NW, fill="lime", font=("Consolas", 12, "bold")
        )
        self.video_canvas.create_text(
            10, 30, text=f"{frame_info['width']}×{frame_info['height']} | "
                         f"Frame #{frame_info['frame_id']}",
            anchor=tk.NW, fill="lime", font=("Consolas", 10)
        )

        # 更新 FPS 标签
        total_fps = sum(self._pipe_fps.values())
        self.fps_label.config(text=f"总FPS: {total_fps:.1f}")

        # 更新状态栏
        pipe_name = f"Pipe {pipe_id}" if self._selected_pipe else f"最新 Pipe {pipe_id}"
        self.status_var.set(
            f"已连接 | {pipe_name} | "
            f"{frame_info['width']}×{frame_info['height']} | "
            f"Frame #{frame_info['frame_id']}"
        )

        # 更新详情面板
        if frame_info:
            self._update_info_panel(frame_info, pipe_id)

    def _update_info_panel(self, frame_info: dict, pipe_id: int):
        """更新当前帧详情面板."""
        fps = self._pipe_fps.get(pipe_id, 0)
        info_lines = [
            f"通道:     Pipe {pipe_id}",
            f"FPS:      {fps:.1f}",
            f"帧类型:   {frame_info.get('type_name', '?')}",
            f"图像格式: {frame_info.get('format', '?')}",
            f"分辨率:   {frame_info['width']} × {frame_info['height']}",
            f"行步长:   {frame_info['stride']}",
            f"帧序号:   #{frame_info['frame_id']}",
            f"CHN ID:   {frame_info['chn_id']}",
            f"数据长度: {frame_info['data_len']:,} bytes",
            f"芯片版本: J{frame_info['chip_ver']}",
        ]
        text = "\n".join(info_lines)

        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", text)
        self.info_text.config(state=tk.DISABLED)

    def _update_overview_panel(self):
        """更新各通道概况面板."""
        with self._frame_lock:
            pipes = sorted(self._available_pipes)

        if not pipes:
            return

        lines = []
        for pid in pipes:
            fps = self._pipe_fps.get(pid, 0)
            if pid in self._pipe_frames:
                _, info = self._pipe_frames[pid]
                lines.append(
                    f"Pipe {pid:2d}: {info['width']}×{info['height']} | "
                    f"FPS {fps:5.1f} | Frame #{info['frame_id']}"
                )
            else:
                lines.append(f"Pipe {pid:2d}: 等待数据...")

        text = "\n".join(lines)

        self.overview_text.config(state=tk.NORMAL)
        self.overview_text.delete("1.0", tk.END)
        self.overview_text.insert("1.0", text)
        self.overview_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # 截图保存
    # ------------------------------------------------------------------

    def _save_snapshot(self):
        """保存当前帧为图片."""
        pipe_id = self._selected_pipe
        with self._frame_lock:
            if pipe_id is not None:
                if pipe_id not in self._pipe_frames:
                    messagebox.showinfo("提示", "当前通道没有画面可保存")
                    return
                frame, info = self._pipe_frames[pipe_id]
                frame = frame.copy()
            elif self._pipe_frames:
                # 全部模式: 保存最新帧
                pid = max(self._pipe_frames.keys(),
                          key=lambda p: self._pipe_frames[p][1].get('frame_id', 0))
                frame, info = self._pipe_frames[pid]
                frame = frame.copy()
                pipe_id = pid
            else:
                messagebox.showinfo("提示", "当前没有画面可保存")
                return

        os.makedirs(self._snapshot_dir, exist_ok=True)
        self._snapshot_count += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self._snapshot_dir,
            f"snapshot_pipe{pipe_id}_{timestamp}_{self._snapshot_count:04d}.jpg"
        )

        rgb = frame[..., ::-1]
        pil_img = Image.fromarray(rgb)
        pil_img.save(filename, quality=95)

        self._log(f"截图已保存: {filename} (Pipe {pipe_id})")
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