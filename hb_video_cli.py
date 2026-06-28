# -*- coding: utf-8 -*-
"""
hb_video_cli.py - J6B 视频流命令行客户端 (多路视频支持)

用法:
  python hb_video_cli.py <设备IP> [端口] [--pipe <pipe_id>] [--save] [--save-dir <目录>]

示例:
  python hb_video_cli.py 172.16.0.14
  python hb_video_cli.py 172.16.0.14 --pipe 7            # 只显示 pipe 7
  python hb_video_cli.py 172.16.0.14 --pipe 0 --save     # 只显示 pipe 0 并保存
  python hb_video_cli.py 172.16.0.14 --no-display --save # 保存所有通道
"""

import argparse
import os
import sys
import time
import signal
import cv2
import numpy as np
from collections import defaultdict

from hb_video_client import HBVideoClient
from hb_protocol import DEFAULT_PORT


class CLIVideoClient:
    """命令行多路视频客户端."""

    def __init__(self, host: str, port: int, target_pipe: int | None = None,
                 save_frames: bool = False, save_dir: str = "./frames",
                 enable_display: bool = True):
        self.host = host
        self.port = port
        self.target_pipe = target_pipe  # None = 显示所有通道
        self.save_frames = save_frames
        self.save_dir = save_dir
        self.enable_display = enable_display
        self.client: HBVideoClient | None = None
        self.running = False
        self.frame_count = 0

        # 各路帧缓冲
        self._pipe_frames: dict[int, tuple[np.ndarray, dict]] = {}
        self._pipe_count: dict[int, int] = defaultdict(int)

        self.last_fps_time = time.time()
        self.fps_frame_count = 0

        if save_frames:
            os.makedirs(save_dir, exist_ok=True)

        if enable_display:
            self._create_windows()

    def _create_windows(self):
        """创建显示窗口."""
        if self.target_pipe is not None:
            cv2.namedWindow(f"J6B Pipe {self.target_pipe}", cv2.WINDOW_NORMAL)
            cv2.resizeWindow(f"J6B Pipe {self.target_pipe}", 1280, 720)
        else:
            # 所有通道: 创建概览窗口
            cv2.namedWindow("J6B - All Pipes", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("J6B - All Pipes", 1600, 900)

    def on_frame(self, frame_info: dict, bgr_image: np.ndarray):
        """帧回调."""
        pipe_id = frame_info['pipe_id']

        # 如果指定了通道, 只处理该通道
        if self.target_pipe is not None and pipe_id != self.target_pipe:
            return

        self.frame_count += 1
        self._pipe_frames[pipe_id] = (bgr_image.copy(), dict(frame_info))
        self._pipe_count[pipe_id] += 1

        # FPS 统计
        self.fps_frame_count += 1
        now = time.time()
        elapsed = now - self.last_fps_time
        if elapsed >= 1.0:
            fps = self.fps_frame_count / elapsed
            self.fps_frame_count = 0
            self.last_fps_time = now

            if self.target_pipe is not None:
                print(f"\r帧: {self.frame_count:6d} | "
                      f"FPS: {fps:6.1f} | "
                      f"Pipe {self.target_pipe} | "
                      f"分辨率: {frame_info['width']}×{frame_info['height']} | "
                      f"ID: #{frame_info['frame_id']}",
                      end="", flush=True)
            else:
                counts = " | ".join(
                    f"P{p}:{self._pipe_count.get(p, 0)}"
                    for p in sorted(self._pipe_count.keys())
                )
                print(f"\r帧: {self.frame_count:6d} | "
                      f"FPS: {fps:6.1f} | [{counts}]",
                      end="", flush=True)

        # 保存帧
        if self.save_frames:
            filename = os.path.join(
                self.save_dir,
                f"frame_{self.frame_count:06d}_p{pipe_id}"
                f"_f{frame_info['frame_id']}.jpg"
            )
            cv2.imwrite(filename, bgr_image, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # 显示
        if self.enable_display:
            self._show_frame(pipe_id, bgr_image, frame_info)

    def _show_frame(self, pipe_id: int, bgr_image: np.ndarray, frame_info: dict):
        """显示帧."""
        if self.target_pipe is not None:
            display = bgr_image.copy()
            h, w = display.shape[:2]
            cv2.putText(display, f"Pipe {pipe_id} | FPS: --",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.putText(display, f"{w}×{h} | Frame #{frame_info['frame_id']}",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow(f"J6B Pipe {self.target_pipe}", display)
        else:
            # 多路: 拼成 2×3 网格
            self._show_grid()

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            self.running = False
        elif key == ord('s'):
            snap_dir = "./snapshots"
            os.makedirs(snap_dir, exist_ok=True)
            snap_name = os.path.join(
                snap_dir,
                f"snap_p{pipe_id}_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
            )
            cv2.imwrite(snap_name, bgr_image)
            print(f"\n[截图] {snap_name}")

    def _show_grid(self):
        """多路网格显示."""
        pipes = sorted(self._pipe_frames.keys())
        if not pipes:
            return

        # 最多显示 6 路 (2×3)
        pipes = pipes[:6]
        grid_cols = min(3, len(pipes))
        grid_rows = (len(pipes) + grid_cols - 1) // grid_cols

        cell_h, cell_w = 360, 640
        grid = np.zeros((grid_rows * cell_h, grid_cols * cell_w, 3), dtype=np.uint8)

        for i, pid in enumerate(pipes):
            frame, info = self._pipe_frames[pid]
            r, c = divmod(i, grid_cols)

            # 缩放
            h, w = frame.shape[:2]
            scale = min(cell_w / w, cell_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            resized = cv2.resize(frame, (new_w, new_h))

            y0 = r * cell_h + (cell_h - new_h) // 2
            x0 = c * cell_w + (cell_w - new_w) // 2
            grid[y0:y0 + new_h, x0:x0 + new_w] = resized

            # 叠加标签
            cv2.putText(grid, f"Pipe {pid}",
                        (x0 + 5, y0 + 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 0), 2)

        cv2.imshow("J6B - All Pipes", grid)

    def run(self):
        """运行客户端."""
        self.client = HBVideoClient(
            host=self.host, port=self.port, enable_yuv=True
        )
        self.client.register_frame_callback(self.on_frame)

        if not self.client.start():
            print("连接失败!")
            return 1

        print(f"已连接 {self.host}:{self.port}")
        if self.target_pipe is not None:
            print(f"仅显示 Pipe {self.target_pipe}")
        else:
            print("显示所有通道")
        print("按 q 或 ESC 退出, 按 s 截图\n")

        self.running = True

        def sig_handler(signum, frame):
            print("\n正在退出...")
            self.running = False
        signal.signal(signal.SIGINT, sig_handler)

        try:
            while self.running:
                time.sleep(0.1)
                if self.client and not self.client.is_connected:
                    print("\n连接已断开!")
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

        return 0

    def cleanup(self):
        """清理资源."""
        if self.client:
            self.client.stop()
        if self.enable_display:
            cv2.destroyAllWindows()
        print(f"\n共接收 {self.frame_count} 帧")
        if self._pipe_count:
            for pid in sorted(self._pipe_count.keys()):
                print(f"  Pipe {pid}: {self._pipe_count[pid]} 帧")
        stats = self.client.get_stats() if self.client else {}
        print(f"统计: {stats}")


def main():
    parser = argparse.ArgumentParser(
        description="J6B 多路视频流命令行客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python hb_video_cli.py 172.16.0.14
  python hb_video_cli.py 172.16.0.14 --pipe 7
  python hb_video_cli.py 172.16.0.14 --pipe 0 --save
  python hb_video_cli.py 172.16.0.14 --no-display --save
        """,
    )
    parser.add_argument("host", help="J6B 设备 IP 地址")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT,
                        help=f"TCP 端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("--pipe", type=int, default=None,
                        help="仅显示指定 pipe 通道 (默认: 显示所有)")
    parser.add_argument("--save", action="store_true", help="保存帧到文件")
    parser.add_argument("--save-dir", default="./frames", help="帧保存目录")
    parser.add_argument("--no-display", action="store_true",
                        help="不显示 GUI 窗口 (仅保存帧)")
    args = parser.parse_args()

    client = CLIVideoClient(
        host=args.host,
        port=args.port,
        target_pipe=args.pipe,
        save_frames=args.save,
        save_dir=args.save_dir,
        enable_display=not args.no_display,
    )
    sys.exit(client.run())


if __name__ == "__main__":
    main()