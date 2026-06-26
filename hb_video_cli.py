# -*- coding: utf-8 -*-
"""
hb_video_cli.py - J6B 视频流命令行客户端 (无 GUI)

用法:
  python hb_video_cli.py <设备IP> [端口] [--save] [--save-dir <目录>]

示例:
  python hb_video_cli.py 192.168.1.100
  python hb_video_cli.py 192.168.1.100 10086 --save
  python hb_video_cli.py 192.168.1.100 --save-dir ./frames

用于无 GUI 环境的测试和调试。
"""

import argparse
import os
import sys
import time
import signal
import cv2
import numpy as np

from hb_video_client import HBVideoClient
from hb_protocol import DEFAULT_PORT


class CLIVideoClient:
    """命令行视频客户端."""

    def __init__(self, host: str, port: int, save_frames: bool = False,
                 save_dir: str = "./frames", enable_display: bool = True):
        self.host = host
        self.port = port
        self.save_frames = save_frames
        self.save_dir = save_dir
        self.enable_display = enable_display
        self.client: HBVideoClient | None = None
        self.running = False
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.fps_frame_count = 0

        if save_frames:
            os.makedirs(save_dir, exist_ok=True)

        if enable_display:
            cv2.namedWindow("J6B Video Stream", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("J6B Video Stream", 1280, 720)

    def on_frame(self, frame_info: dict, bgr_image: np.ndarray):
        """帧回调."""
        self.frame_count += 1
        self.fps_frame_count += 1

        # FPS 统计
        now = time.time()
        elapsed = now - self.last_fps_time
        if elapsed >= 1.0:
            fps = self.fps_frame_count / elapsed
            self.fps_frame_count = 0
            self.last_fps_time = now
            print(f"\r帧: {self.frame_count:6d} | "
                  f"FPS: {fps:6.1f} | "
                  f"分辨率: {frame_info['width']}×{frame_info['height']} | "
                  f"ID: #{frame_info['frame_id']}",
                  end="", flush=True)

        # 保存帧
        if self.save_frames:
            filename = os.path.join(
                self.save_dir,
                f"frame_{self.frame_count:06d}_p{frame_info['pipe_id']}"
                f"_f{frame_info['frame_id']}.jpg"
            )
            cv2.imwrite(filename, bgr_image, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # 显示
        if self.enable_display:
            # 叠加 FPS
            display = bgr_image.copy()
            cv2.putText(display, f"FPS: {fps:.1f}" if 'fps' in dir() else "",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            cv2.putText(display, f"Frame: #{frame_info['frame_id']}",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 0), 2)
            cv2.imshow("J6B Video Stream", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # q 或 ESC 退出
                self.running = False
            elif key == ord('s'):  # s 键截图
                snap_dir = "./snapshots"
                os.makedirs(snap_dir, exist_ok=True)
                snap_name = os.path.join(
                    snap_dir,
                    f"snap_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                )
                cv2.imwrite(snap_name, bgr_image)
                print(f"\n[截图] {snap_name}")

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
        print("按 q 或 ESC 退出, 按 s 截图\n")

        self.running = True

        # 信号处理 (Ctrl+C)
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
        stats = self.client.get_stats() if self.client else {}
        print(f"统计: {stats}")


def main():
    parser = argparse.ArgumentParser(
        description="J6B 视频流命令行客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python hb_video_cli.py 192.168.1.100
  python hb_video_cli.py 192.168.1.100 10086 --save
  python hb_video_cli.py 192.168.1.100 --no-display --save
        """,
    )
    parser.add_argument("host", help="J6B 设备 IP 地址")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT,
                        help=f"TCP 端口 (默认: {DEFAULT_PORT})")
    parser.add_argument("--save", action="store_true", help="保存帧到文件")
    parser.add_argument("--save-dir", default="./frames", help="帧保存目录")
    parser.add_argument("--no-display", action="store_true",
                        help="不显示 GUI 窗口 (仅保存帧)")
    args = parser.parse_args()

    client = CLIVideoClient(
        host=args.host,
        port=args.port,
        save_frames=args.save,
        save_dir=args.save_dir,
        enable_display=not args.no_display,
    )
    sys.exit(client.run())


if __name__ == "__main__":
    main()