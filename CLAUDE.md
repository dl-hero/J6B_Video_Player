# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

PC 端通过 TCP 连接 J6B (地平线) 设备接收实时视频流并显示的工具。支持 GUI (tkinter+Pillow) 和 CLI (OpenCV HighGUI) 两种模式，单连接承载多路视频通道。

**双数据格式自动识别**：
- **NV12 原始像素流** (camera_sample) — 纯 numpy BT.601 转换，无需额外依赖
- **H.264 压缩码流** (venc_stream) — PyAV 软件解码，带宽占用降低 95%+

J6B 设备端 `tools/viotool/venc_stream/` — CIM4 四路视频流 VPU 硬件 H.264 编码 + TCP 输出 (已调通, SC361AT ×4, 1696×1168, 4Mbps/路)。

**延迟优化 (v1.5.0)**:
- J6B 编码器: `vbv_buffer_size=300ms`, `frame_buf_count=3` (低延迟配置)
- PC 解码器: `av.Packet(data)` 直送 (非 `decoder.parse`), `thread_count=1`

## 命令

```bash
# 安装依赖
pip install -r requirements.txt      # 完整安装 (GUI + CLI + H.264 解码)
pip install numpy Pillow              # 仅 GUI (NV12 流)
pip install numpy opencv-python      # 仅 CLI (NV12 流)
pip install numpy av                  # 仅 H.264 解码 (无 GUI)

# 启动 GUI
python hb_video_gui.py

# 启动 CLI (多路网格显示)
python hb_video_cli.py <设备IP>

# 启动 GUI (田字格多路 + 带宽显示 + 配置持久化)
python hb_video_gui.py

# CLI 指定通道 + 保存帧
python hb_video_cli.py 192.168.0.140 --pipe 0 --save --save-dir ./frames

# CLI 无头模式 (仅保存帧)
python hb_video_cli.py 192.168.0.140 --no-display --save

# 设备端启动 (二选一)
# 方案 A: camera_sample — NV12 原始视频流 (低延迟, 高带宽)
#   设备端: camera_sample -s 1 -S 0
# 方案 B: venc_stream — H.264 压缩视频流 (低带宽, ~200ms 延迟, 需先 kill camera_sample)
#   设备端: cd /app/sample/S83_Sample/S83E04_Module/venc_stream/bin && ./run.sh
#   PC端:   python hb_video_gui.py (连接 192.168.0.140:10086)

# 编译 venc_stream (SDK 开发机)
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS/tools/viotool/venc_stream/src
source build_tools/Compiler/qnx800/qnxsdp-env.sh && source envsetup.sh
make clean && make && cp venc_stream ../bin/
```

## 架构

三层模块依赖 + 设备端工具，自底向上：

```
hb_protocol.py          # 纯协议层 — 常量、枚举、struct 打包/解包/验证
    ↑
hb_video_client.py      # 核心通信层 — TCP 连接、帧接收、自动识别 NV12/H.264、解码、回调通知
    ↑
hb_video_gui.py         # GUI (tkinter + Pillow) — 田字格多路显示、截图
hb_video_cli.py         # CLI (OpenCV) — 命令行参数、多路网格显示、帧保存

【J6B 设备端】
tools/viotool/
├── libhbplayer/        # TCP Server 库 (hb_tool_server)
└── venc_stream/        # CIM4 四路 H.264 编码工具 (新增)
    ├── src/venc_stream.c  # 主程序: CIM DDR→VPU编码→hb_tool_send_video_pic
    └── bin/run.sh          # 一键启动脚本
```

- **`hb_protocol.py`** — 无状态纯函数模块。定义 `cmd_header_new_t` (80 字节) 和 `tranfer_info_t` (24 字节) 的 struct 布局、DataType/RawBit/YuvType 等枚举、`pack_cmd_header`/`unpack_cmd_header`/`verify_header`/`make_net_send_cfg_packet`/`parse_frame_info` 等辅助函数。`parse_frame_info` 返回字典含 `code_type` 字段 (H264=0, H265=1)。

- **`hb_video_client.py`** — `HBVideoClient` 类。连接流程：TCP connect → 发送 NET_SEND_CFG (104 字节) → 启动 daemon 接收线程 `_recv_loop()`。接收线程循环：读取 80B 帧头 → 魔数验证 → 读取数据体 → 根据 `data_type` 自动选择解码器:
  - `YUV_DATA (1)` → `_nv12_to_bgr()` 纯 numpy ITU-R BT.601 转换 (无需 PyAV)
  - `VIDEO_DATA (3)` → `_decode_h264()` PyAV 解码 (需 `pip install av`)
  帧同步 `_sync_to_header()` 在魔数不匹配时逐字节滑动搜索 `0xCCDDEEFF`。

- **`hb_video_gui.py`** — `HBVideoGUI` 类。连接在后台线程执行，帧回调 `_on_frame_received` 按 `pipe_id` 分路存入 `_pipe_frames` 字典，主线程 `_update_display()` 每 30ms 定时刷新(零拷贝引用传递)。田字格多路同时显示，各路独立渲染单元。BGR→RGB→PIL Image→ImageTk 渲染管线。顶部控制栏显示实时带宽(Mbps)和总FPS。配置文件 `.j6b_player_config.json` 持久化 IP/端口/截图目录。

- **`hb_video_cli.py`** — `CLIVideoClient` 类。支持 `--pipe` 单通道窗口或 2×3 网格多路显示。无头模式 `--no-display` 仅保存帧。

- **`tools/viotool/venc_stream/`** — J6B 设备端工具 (v1.5.0 已调通)。`venc_stream.c` (~540行) 复用 `camera_sample` 的 VIO JSON 配置 + MediaCodec API 实现 4 路并发 H.264 硬件编码 (SC361AT, 1696×1168, 30fps, 4Mbps/路), 通过 `hb_tool_send_video_pic()` 走 libhbplayer TCP 发送。低延迟配置: `vbv_buffer_size=300ms` + `frame_buf_count=3`。配置文件: `case_matrix/GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4`。

## 关键设计要点

- **多路视频**：5 路视频通过同一 TCP 连接交错传输，帧头 `pipe_id` 字段 (偏移 56) 区分通道。设备端 `send_data_load_balance` 在 5 通道间动态调度。
- **双解码模式**：帧头 `type=1` (YUV_DATA) 走 `_nv12_to_bgr()` numpy 转换；`type=3` (VIDEO_DATA) 走 `_decode_h264()` PyAV 解码。两种模式对上层透明，GUI/CLI 无需改动。
- **NV12 布局**：`stride × height` Y 平面 + `stride × height / 2` 交错 UV 平面。当 `stride > width` 时需裁剪到有效宽度。
- **H.264 码流**：`code_type` 字段 (偏移 48) 标识编码类型 (H264=0, H265=1)。PC 端用 `av.Packet(data)` 直送解码器 (非 `decoder.parse`, 避免缓冲累积延迟)。解码器按 `pipe_id` 独立管理, `thread_count=1` 单线程。
- **连接限制**：设备端每次启动仅接受一次 TCP 连接，断开后需重启设备 (`ssh root@<IP> "reboot"`)。
- **Python ≥ 3.10**：代码使用了 `X | None` 联合类型语法。
- **帧回调线程安全**：`register_frame_callback` 注册的回调在**接收线程中同步调用**，回调内部必须尽快返回（只做深拷贝，不做耗时操作）。GUI/CLI 的上层渲染在主线程中异步执行。
- **调试日志**：`HBVideoClient` 使用 `logging.getLogger("HBVideoClient")`，设置 `logging.basicConfig(level=logging.DEBUG)` 可查看协议级详细日志。
- **Windows / Linux 双平台兼容**：PC 端程序的每次变更都需考虑 Windows 和 Linux 的兼容性，包括但不限于：路径分隔符（使用 `os.path.join` / `pathlib`）、网络行为差异、字体回退、子进程调用、可选依赖（如 PyAV、tkinter）的导入保护。

## 参考文档

- **`DESIGN_DOC.md`** — 完整架构设计文档（1.4.0），含协议详解、线程模型图、NV12→BGR 转换流程、帧同步算法、H.264 编解码链路、GUI 状态机、FAQ 等。
- **`ref_docs/`** — 协议参考源文件（`hb_tool_server.h` 等 C 源码）、J6B SDK 手册（VPU/CIM/CODEC 文档）、`S83E04_Module` Sample 源码。
- **`tools/viotool/venc_stream/`** — J6B 设备端 VPU H.264 编码+流式输出工具源码。