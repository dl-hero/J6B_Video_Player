# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

PC 端通过 TCP 连接 J6B (地平线) 设备接收实时 NV12 视频流并显示的工具。支持 GUI (tkinter+Pillow) 和 CLI (OpenCV HighGUI) 两种模式，单连接承载多路视频通道。

## 命令

```bash
# 安装依赖
pip install -r requirements.txt      # 完整安装 (GUI + CLI)
pip install numpy Pillow              # 仅 GUI
pip install numpy opencv-python      # 仅 CLI

# 启动 GUI
python hb_video_gui.py

# 启动 CLI (多路网格显示)
python hb_video_cli.py <设备IP>

# CLI 指定通道 + 保存帧
python hb_video_cli.py 172.16.0.14 --pipe 0 --save --save-dir ./frames

# CLI 无头模式 (仅保存帧)
python hb_video_cli.py 172.16.0.14 --no-display --save

# 设备端需先运行 camera_sample (启用 hbplayer)
# 设备端: camera_sample -s 1 -S 0
```

## 架构

三层模块依赖，自底向上：

```
hb_protocol.py          # 纯协议层 — 常量、枚举、struct 打包/解包/验证
    ↑
hb_video_client.py      # 核心通信层 — TCP 连接、帧接收、NV12→BGR 转换、回调通知
    ↑
hb_video_gui.py         # GUI (tkinter + Pillow) — 多路切换、实时渲染、截图
hb_video_cli.py         # CLI (OpenCV) — 命令行参数、多路网格显示、帧保存
```

- **`hb_protocol.py`** — 无状态纯函数模块。定义 `cmd_header_new_t` (80 字节) 和 `tranfer_info_t` (24 字节) 的 struct 布局、DataType/RawBit/YuvType 等枚举、`pack_cmd_header`/`unpack_cmd_header`/`verify_header`/`make_net_send_cfg_packet`/`parse_frame_info` 等辅助函数。所有字段索引通过 `IDX_*` 常量访问。

- **`hb_video_client.py`** — `HBVideoClient` 类。连接流程：TCP connect → 发送 NET_SEND_CFG (104 字节) → 启动 daemon 接收线程 `_recv_loop()`。接收线程循环：读取 80B 帧头 → 魔数验证 → 读取数据体 → `_nv12_to_bgr()` 纯 numpy ITU-R BT.601 转换 → 回调通知。帧同步 `_sync_to_header()` 在魔数不匹配时逐字节滑动搜索 `0xCCDDEEFF`。

- **`hb_video_gui.py`** — `HBVideoGUI` 类。连接在后台线程执行，帧回调 `_on_frame_received` 按 `pipe_id` 分路存入 `_pipe_frames` 字典，主线程 `_update_display()` 每 30ms 定时刷新。BGR→RGB→PIL Image→ImageTk 渲染管线，不依赖 OpenCV。

- **`hb_video_cli.py`** — `CLIVideoClient` 类。支持 `--pipe` 单通道窗口或 2×3 网格多路显示。无头模式 `--no-display` 仅保存帧。

## 关键设计要点

- **多路视频**：5 路视频通过同一 TCP 连接交错传输，帧头 `pipe_id` 字段 (偏移 56) 区分通道。设备端 `send_data_load_balance` 在 5 通道间动态调度。
- **NV12 布局**：`stride × height` Y 平面 + `stride × height / 2` 交错 UV 平面。当 `stride > width` 时需裁剪到有效宽度。
- **连接限制**：设备端每次启动仅接受一次 TCP 连接，断开后需重启设备 (`ssh root@<IP> "reboot"`)。
- **Python ≥ 3.10**：代码使用了 `X | None` 联合类型语法。
- **帧回调线程安全**：`register_frame_callback` 注册的回调在**接收线程中同步调用**，回调内部必须尽快返回（只做深拷贝，不做耗时操作）。GUI/CLI 的上层渲染在主线程中异步执行。
- **调试日志**：`HBVideoClient` 使用 `logging.getLogger("HBVideoClient")`，设置 `logging.basicConfig(level=logging.DEBUG)` 可查看协议级详细日志。

## 参考文档

- **`DESIGN_DOC.md`** — 完整架构设计文档（1.2.0），含协议详解、线程模型图、NV12→BGR 转换流程、帧同步算法、GUI 状态机、FAQ 等。
- **`ref_docs/`** — 协议参考源文件（`hb_tool_server.h` 等 C 源码），用于协议逆向分析。