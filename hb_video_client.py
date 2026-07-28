# -*- coding: utf-8 -*-
"""
hb_video_client.py - J6B 视频流客户端 (网络通信层)

功能:
  1. 通过 TCP 连接远端 J6B 设备 (默认端口 10086)
  2. 发送 NET_SEND_CFG 配置包启用视频流传输
  3. 接收并解析 cmd_header_new_t + 数据帧, 自动识别:
     - NV12 (YUV_DATA)    → _nv12_to_bgr()  纯 numpy 转换
     - H.264 (VIDEO_DATA) → PyAV 硬件解码 → BGR
  4. 将解码后的 BGR 图像通过回调通知上层

协议说明:
  每帧 = 80 字节帧头 (cmd_header_new_t) + 数据体

  关键帧头字段:
    - header_start  : 0xCCDDEEFF  (魔数)
    - header_check1 : 0x6789ABCD  (魔数)
    - header_end    : 0xFFEEDDCC  (魔数)
    - len           : 数据体长度
    - type          : 1=YUV_DATA(NV12), 3=VIDEO_DATA(H.264)
    - format        : 0=YUVNV12
    - width/height/stride : 图像尺寸信息
    - frame_id      : 帧序号
    - code_type     : 编码类型 (0=H264, 1=H265)

NV12 格式:
  Y plane:  width * height 字节 (亮度)
  UV plane: width * height / 2 字节 (交错色度, UVUV...)

参考文件:
  - hb_tool_server.c  : 服务端发送逻辑
  - camera_sample.c   : 发送端调用示例
  - socket_manager.c  : socket 收发逻辑
"""

import socket
import struct
import queue
import threading
import time
import logging
import numpy as np

from hb_protocol import (
    CMD_HEADER_SIZE,
    DEFAULT_PORT,
    DataType,
    IDX_HEADER_START, IDX_HEADER_CHECK1, IDX_HEADER_END,
    IDX_LEN, IDX_TYPE, IDX_FORMAT, IDX_WIDTH, IDX_HEIGHT, IDX_STRIDE,
    IDX_PIPE_ID, IDX_CHN_ID, IDX_FRAME_ID, IDX_CODE_TYPE,
    unpack_cmd_header, verify_header, make_net_send_cfg_packet,
    parse_frame_info,
)

# PyAV 可选依赖 (仅 H.264 解码时需要)
try:
    import av
    _HAS_PYAV = True
except ImportError:
    _HAS_PYAV = False
    av = None

logger = logging.getLogger("HBVideoClient")


class HBVideoClient:
    """
    J6B 视频流客户端.

    自动识别数据类型并解码:
      - NV12 (YUV_DATA, type=1)   → 纯 numpy BT.601 转换
      - H.264 (VIDEO_DATA, type=3) → PyAV 软件解码
    两种模式统一输出 BGR 图像, 对上层 GUI/CLI 透明。
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT,
                 enable_yuv: bool = True, enable_raw: bool = False,
                 pipe_line: int = 0, channel_id: int = 0):
        """
        初始化客户端.

        Args:
            host:        设备 IP 地址
            port:        TCP 端口 (默认 10086)
            enable_yuv:  启用 YUV 数据接收
            enable_raw:  启用 RAW 数据接收
            pipe_line:   pipeline 编号
            channel_id:  通道编号
        """
        self.host = host
        self.port = port
        self.enable_yuv = enable_yuv
        self.enable_raw = enable_raw
        self.pipe_line = pipe_line
        self.channel_id = channel_id

        self._sock: socket.socket | None = None
        self._running = False
        self._recv_thread: threading.Thread | None = None

        # 帧回调 (多线程访问, 需 _callbacks_lock 保护)
        self._frame_callbacks: list = []
        self._callbacks_lock = threading.Lock()

        # 统计信息
        self.frame_count = 0
        self.error_count = 0
        self.total_bytes = 0   # 累计接收字节数 (含所有帧, 用于带宽计算)
        self._lock = threading.Lock()

        # H.264 解码器 (按 pipe_id 独立, 仅 VIDEO_DATA 时使用)
        self._h264_decoders: dict[int, 'av.CodecContext'] = {}

        # 每路独立解码线程 (并行解码, 突破单线程串行瓶颈)
        self._pipe_queues: dict[int, queue.Queue] = {}
        self._pipe_threads: dict[int, threading.Thread] = {}

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        连接到设备并发送配置包.

        Returns:
            True 表示连接成功
        """
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock.settimeout(5.0)
            logger.info(f"正在连接 {self.host}:{self.port} ...")
            self._sock.connect((self.host, self.port))
            logger.info("TCP 连接成功")

            # 发送 NET_SEND_CFG 配置包
            cfg_packet = make_net_send_cfg_packet(
                enable_yuv=self.enable_yuv,
                enable_raw=self.enable_raw,
                pipe_line=self.pipe_line,
                channel_id=self.channel_id,
            )
            self._sock.sendall(cfg_packet)
            logger.info("已发送 NET_SEND_CFG 配置包 (YUV 已启用)")
            return True

        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            logger.error(f"连接失败: {e}")
            self._sock = None
            return False

    def disconnect(self):
        """断开连接, 等待所有解码线程退出."""
        self._running = False

        # 关闭 socket 使接收线程退出
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

        # 等待接收线程退出
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=2.0)

        # 等待各解码线程退出
        for pipe_id, t in list(self._pipe_threads.items()):
            if t.is_alive():
                t.join(timeout=2.0)
        self._pipe_threads.clear()
        self._pipe_queues.clear()

        # 清理 H.264 解码器 (下次连接时重建)
        self._h264_decoders.clear()
        logger.info("已断开连接")

    @property
    def is_connected(self) -> bool:
        return self._sock is not None

    # ------------------------------------------------------------------
    # 帧回调注册
    # ------------------------------------------------------------------

    def register_frame_callback(self, callback):
        """注册帧回调函数 (线程安全)."""
        with self._callbacks_lock:
            self._frame_callbacks.append(callback)

    def remove_frame_callback(self, callback):
        """移除帧回调 (线程安全)."""
        with self._callbacks_lock:
            if callback in self._frame_callbacks:
                self._frame_callbacks.remove(callback)

    def _notify_frame(self, frame_info: dict, bgr_image: np.ndarray):
        """通知所有注册的回调 (会被多个解码线程并发调用)."""
        with self._callbacks_lock:
            callbacks = list(self._frame_callbacks)
        for cb in callbacks:
            try:
                cb(frame_info, bgr_image)
            except Exception as e:
                logger.error(f"帧回调异常: {e}")

    # ------------------------------------------------------------------
    # 数据接收
    # ------------------------------------------------------------------

    def _recv_exact(self, size: int) -> bytes | None:
        """精确接收指定字节数."""
        data = b""
        while len(data) < size:
            try:
                chunk = self._sock.recv(size - len(data))
            except socket.timeout:
                return None
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _read_one_frame(self) -> tuple[bytes, dict] | None:
        """
        从 socket 读取一帧 (header + body), 仅读取不解码.

        Returns:
            (body_data, frame_info) 或 None
        """
        # 1. 接收帧头
        header_data = self._recv_exact(CMD_HEADER_SIZE)
        if header_data is None:
            return None

        # 2. 解包帧头
        try:
            header_fields = unpack_cmd_header(header_data)
        except struct.error:
            logger.warning("帧头解包失败, 跳过")
            return None

        # 3. 验证魔数
        if not verify_header(header_fields):
            synced = self._sync_to_header(header_data)
            if not synced:
                self.error_count += 1
            return None

        data_len = header_fields[IDX_LEN]
        data_type = header_fields[IDX_TYPE]

        # 4. 跳过非视频数据
        if data_type not in (DataType.YUV_DATA, DataType.RAW_DATA,
                              DataType.VIDEO_DATA):
            if data_len > 0:
                self._recv_exact(data_len)
            return None

        # 5. 接收数据体
        if data_len == 0:
            return None
        body_data = self._recv_exact(data_len)
        if body_data is None:
            self.error_count += 1
            return None

        # 6. 解析帧信息 + 统计带宽
        frame_info = parse_frame_info(header_fields)
        with self._lock:
            self.total_bytes += CMD_HEADER_SIZE + data_len
        return (body_data, frame_info)

    def _decode_one_frame(self, body_data: bytes, frame_info: dict,
                          pipe_id: int, data_type: int) -> np.ndarray | None:
        """解码单帧数据 → BGR (在解码线程中调用)."""
        if data_type == DataType.VIDEO_DATA:
            return self._decode_h264(body_data, pipe_id, frame_info)
        else:
            try:
                return self._nv12_to_bgr(
                    body_data,
                    frame_info['width'],
                    frame_info['height'],
                    frame_info['stride'],
                )
            except Exception as e:
                logger.error(f"Pipe {pipe_id}: NV12转BGR失败: {e}")
                return None

    def _get_or_start_pipe_worker(self, pipe_id: int):
        """获取或创建指定 pipe 的解码队列+线程 (惰性创建)."""
        if pipe_id not in self._pipe_queues:
            q = queue.Queue(maxsize=2)  # 小容量 → 解码慢时快速背压
            self._pipe_queues[pipe_id] = q
            t = threading.Thread(
                target=self._pipe_decode_loop,
                args=(pipe_id, q),
                name=f"HB-Decode-Pipe{pipe_id}",
                daemon=True,
            )
            self._pipe_threads[pipe_id] = t
            t.start()
            logger.debug(f"Pipe {pipe_id}: 解码线程已创建")
        return self._pipe_queues[pipe_id]

    def _pipe_decode_loop(self, pipe_id: int, q: queue.Queue):
        """
        单路解码线程主循环.

        从队列取出原始帧数据 → 解码 → 推送回调.
        多路并行: Pipe 7/8/9/10 各一个独立线程, 利用多核 CPU 并行解码.
        """
        while self._running:
            try:
                body_data, frame_info = q.get(timeout=0.5)
            except queue.Empty:
                continue

            data_type = frame_info['type']
            bgr_image = self._decode_one_frame(
                body_data, frame_info, pipe_id, data_type)

            if bgr_image is not None:
                with self._lock:
                    self.frame_count += 1
                self._notify_frame(frame_info, bgr_image)

        logger.debug(f"Pipe {pipe_id}: 解码线程退出")

    def _recv_loop(self):
        """
        接收线程主循环 — 仅负责从 socket 读取帧并分发到各 pipe 的解码队列.

        解码由每路独立的 _pipe_decode_loop 线程并行处理, 突破单线程串行瓶颈。
        队列 maxsize=2 提供自然背压: 某路解码慢时 put() 阻塞 → TCP recv 阻塞 →
        J6B 发送端降速, 全局流控。
        """
        self._running = True
        self._sock.settimeout(1.0)

        while self._running:
            result = self._read_one_frame()
            if result is None:
                if not self._running:
                    break
                self.error_count += 1
                continue

            body_data, frame_info = result
            pipe_id = frame_info['pipe_id']

            # 分发到对应 pipe 的解码线程
            q = self._get_or_start_pipe_worker(pipe_id)
            q.put((body_data, frame_info))  # 阻塞直到解码线程消费 (背压)

        logger.info("接收线程退出")

    def _sync_to_header(self, partial_data: bytes) -> bool:
        """
        同步到下一个有效帧头.

        当帧头魔数不匹配时, 逐字节滑动搜索 0xCCDDEEFF 起始标志.

        Args:
            partial_data: 已读取的 80 字节 (可能包含无效数据)

        Returns:
            True 表示成功同步到下一帧
        """
        start_magic = struct.pack("<I", 0xCCDDEEFF)
        check_magic = struct.pack("<I", 0x6789ABCD)
        end_magic = struct.pack("<I", 0xFFEEDDCC)

        # 在当前数据中搜索
        sync_buffer = bytearray(partial_data)
        max_scan = 1024 * 1024  # 最多扫描 1MB

        for _ in range(max_scan):
            pos = sync_buffer.find(start_magic)
            if pos == -1:
                # 读取更多数据
                try:
                    chunk = self._sock.recv(4096)
                except (socket.timeout, OSError):
                    return False
                if not chunk:
                    return False
                sync_buffer.extend(chunk)
                # 保留最后 4 字节防止跨边界
                if len(sync_buffer) > 4:
                    sync_buffer = sync_buffer[-4:]
                continue

            # 找到起始魔数，检查是否构成完整帧头
            if len(sync_buffer) >= pos + CMD_HEADER_SIZE:
                candidate = bytes(sync_buffer[pos:pos + CMD_HEADER_SIZE])
                try:
                    fields = unpack_cmd_header(candidate)
                    if verify_header(fields):
                        data_len = fields[IDX_LEN]
                        # 确保数据体也被完整接收
                        if data_len > 0:
                            body = self._recv_exact(data_len)
                            if body is not None:
                                logger.info(f"同步成功, 跳过 {pos} 字节")
                                return True
                            return False
                        return True
                except struct.error:
                    pass
                # 不是有效帧头，继续搜索
                sync_buffer = sync_buffer[pos + 1:]
            else:
                # 数据不足，读取更多
                try:
                    chunk = self._sock.recv(4096)
                except (socket.timeout, OSError):
                    return False
                if not chunk:
                    return False
                sync_buffer.extend(chunk)

        logger.warning("同步超时, 未找到有效帧头")
        return False

    # ------------------------------------------------------------------
    # H.264 解码
    # ------------------------------------------------------------------

    def _get_h264_decoder(self, pipe_id: int) -> 'av.CodecContext':
        """获取或创建指定 pipe 的 H.264 解码器."""
        if not _HAS_PYAV:
            raise RuntimeError(
                "接收到了 H.264 视频流, 但 PyAV 未安装。"
                "请运行: pip install av"
            )
        if pipe_id not in self._h264_decoders:
            codec = av.CodecContext.create('h264', 'r')
            codec.thread_count = 0  # 0=auto (FFmpeg 多线程, 利用多核CPU, 绕过 GIL)
            # 启用错误恢复: 缺失参考帧或数据损坏时尽量输出画面而非报错
            codec.flags |= 4  # AV_CODEC_FLAG_OUTPUT_CORRUPT
            self._h264_decoders[pipe_id] = codec
            logger.info(f"Pipe {pipe_id}: 已创建 H.264 解码器 (thread_count=auto)")
        return self._h264_decoders[pipe_id]

    def _decode_h264(self, data: bytes, pipe_id: int,
                       frame_info: dict) -> np.ndarray | None:
        """
        将 H.264 Annex B 码流解码为 BGR 图像.

        使用 decoder.parse() 将 Annex B 字节流拆分为 NAL 单元对齐的 Packet,
        再逐个送入 decoder.decode()。parse() 内部 av_parser_parse2() 自动
        提取 SPS/PPS 并更新解码器内部状态 — 这解决了 av.Packet(data) 直送时
        解码器因缺少上下文将首个 P-frame 之前所有帧都拒绝的问题。

        排空机制 (_recv_loop 中的 _read_and_decode_one_frame non-blocking 批量调用)
        确保长期运行时不会因 parser 内部缓冲渐进式累积延迟。

        Args:
            data:       H.264 Annex B 码流数据
            pipe_id:    Pipeline 编号
            frame_info: 帧信息字典

        Returns:
            BGR 格式 numpy 数组, 或 None
        """
        decoder = self._get_h264_decoder(pipe_id)

        try:
            packets = decoder.parse(data)
            if not packets:
                return None  # parser 缓冲中, 等待更多数据拼接完整 NAL 单元

            bgr = None
            for packet in packets:
                try:
                    frames = decoder.decode(packet)
                    for frame in frames:
                        bgr = frame.to_ndarray(format='bgr24')
                except Exception:
                    continue  # 单个 packet 解码失败, 跳过继续
            return bgr
        except Exception as e:
            logger.debug(f"Pipe {pipe_id}: 解码异常: {e}")
            return None

    # ------------------------------------------------------------------
    # NV12 -> BGR 转换
    # ------------------------------------------------------------------

    @staticmethod
    def _nv12_to_bgr(data: bytes, width: int, height: int, stride: int) -> np.ndarray:
        """
        将 NV12 数据转换为 BGR 图像 (OpenCV 格式).

        NV12 布局:
          Y plane:  stride * height 字节 (实际有效宽度为 width)
          UV plane: stride * height / 2 字节 (交错 UVUV...)

        Args:
            data:   NV12 原始数据
            width:  图像宽度
            height: 图像高度
            stride: 行步长 (可能 >= width)

        Returns:
            BGR 格式的 numpy 数组 (height, width, 3), dtype=uint8
        """
        y_size = stride * height
        uv_size = stride * height // 2

        if len(data) < y_size + uv_size:
            raise ValueError(f"数据不足: 需要 {y_size + uv_size}, 实际 {len(data)}")

        # 提取 Y 和 UV 平面
        y_data = data[:y_size]
        uv_data = data[y_size:y_size + uv_size]

        # 转换为 numpy 数组
        y = np.frombuffer(y_data, dtype=np.uint8).reshape((height, stride))
        uv = np.frombuffer(uv_data, dtype=np.uint8).reshape((height // 2, stride))

        # 如果 stride > width, 裁剪到有效宽度
        if stride > width:
            y = y[:, :width]
            uv = uv[:, :width]

        # NV12 -> BGR
        # Y: 全分辨率亮度
        # U/V: 从交错 UV 中提取
        u = uv[:, 0::2]    # 偶数列: U
        v = uv[:, 1::2]    # 奇数列: V

        # 上采样 U/V 到全分辨率 (最近邻)
        u_upsampled = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)
        v_upsampled = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)

        # 确保尺寸匹配
        h, w = y.shape
        u_upsampled = u_upsampled[:h, :w]
        v_upsampled = v_upsampled[:h, :w]

        # YUV -> RGB (使用 ITU-R BT.601 标准)
        y_f = y.astype(np.float32) - 16.0
        u_f = u_upsampled.astype(np.float32) - 128.0
        v_f = v_upsampled.astype(np.float32) - 128.0

        r = np.clip(1.164 * y_f + 1.596 * v_f, 0, 255).astype(np.uint8)
        g = np.clip(1.164 * y_f - 0.392 * u_f - 0.813 * v_f, 0, 255).astype(np.uint8)
        b = np.clip(1.164 * y_f + 2.017 * u_f, 0, 255).astype(np.uint8)

        # 合并为 BGR (OpenCV 默认格式)
        bgr = np.stack([b, g, r], axis=-1)
        return bgr

    # ------------------------------------------------------------------
    # 启动/停止
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        启动视频流接收.

        Returns:
            True 表示启动成功
        """
        if not self.connect():
            return False

        self._recv_thread = threading.Thread(
            target=self._recv_loop,
            name="HB-Recv",
            daemon=True,
        )
        self._recv_thread.start()
        logger.info("视频流接收已启动")
        return True

    def stop(self):
        """停止视频流接收 (disconnect 会等待所有线程退出)."""
        self.disconnect()

    def get_stats(self) -> dict:
        """获取统计信息 (包含所有帧的实际接收字节数)."""
        with self._lock:
            return {
                'frame_count': self.frame_count,
                'error_count': self.error_count,
                'total_bytes': self.total_bytes,
            }