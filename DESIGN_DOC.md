# J6B Video Player — 架构设计文档与使用说明

> **版本**: 1.6.0  
> **日期**: 2026-07-28  
> **适用平台**: Windows 10+ / Ubuntu 22.04+  
> **目标设备**: J6B (Horizon Robotics J6 芯片平台)  
> **已验证设备**: J6B_GAC_AY5-TM (IP: 192.168.0.140, 4 路 SC361AT 摄像头)  
> **协议参考**: `hb_tool_server.h` / `hb_tool_server.c` / `camera_sample.c` / `socket_manager.c` / `server_cmd.h`

---

## 变更履历

| 版本 | 日期 | 变更文件 | 变更说明 |
|------|------|----------|----------|
| 1.0.0 | 2025-06-25 | 全部 | 初始版本，基于 J6B SDK 协议逆向分析，实现单路视频接收与 GUI 显示 |
| 1.1.0 | 2025-06-26 | `hb_protocol.py` | 完善协议常量注释，`parse_frame_info` 新增 `type_name` 字段 |
| | | `hb_video_client.py` | 完善 `_recv_loop` 错误处理，`_sync_to_header` 增加滑动窗口防跨边界逻辑 |
| | | `hb_video_gui.py` | 字体适配跨平台 (`Microsoft YaHei` → `DejaVu Sans`)，GUI 仅依赖 Pillow 不依赖 OpenCV |
| | | `hb_video_cli.py` | 完善命令行参数解析，新增 `--no-display` 和 `--save-dir` 参数 |
| | | `DESIGN_DOC.md` | 全面重写，精确行数、完整 API 表、性能数据、FAQ 扩展 |
| **1.2.0** | **2025-06-28** | **`hb_video_gui.py`** | **重大更新**: 单路显示 → **多路视频支持**。新增通道下拉选择 (`pipe_combo`)、各通道概况面板 (`overview_text`)、`_pipe_frames` 多路帧缓冲字典、各路独立 FPS 统计、`_update_pipe_combo` 动态通道发现、`_on_pipe_selected` 通道切换事件 |
| | | **`hb_video_cli.py`** | **重大更新**: 单路显示 → **多路视频支持**。新增 `--pipe` 参数指定单通道、`_show_grid` 多路 2×3 网格显示、各路独立帧计数 `_pipe_count`、自动通道发现 |
| | | `hb_video_client.py` | 无变更 (核心通信层无需修改，协议层已支持多路) |
| | | `hb_protocol.py` | 无变更 |
| | | `DESIGN_DOC.md` | 新增多路视频架构、设备端已知限制、真机验证结果 (5 路)、GUI/CLI 多路使用说明 |
| **1.3.0** | **2025-06-29** | **`hb_video_gui.py`** | **重大更新**: 多路视频田字格同时显示。移除单路大画面切换模式，改为所有通道按田字格同时渲染。新增 `_calculate_grid()` 自适应行列数 (ceil(sqrt(N)))、`_pipe_cells` 网格单元字典、`_get_or_create_cell()` 动态创建显示单元、`_render_cell()` 各通道独立渲染 + 顶部信息条叠加、`_arrange_grid()` 自动网格布局。通道下拉框改为仅控制截图目标 + 右侧详情面板，不影响田字格全量显示。 |
| | | `hb_video_client.py` | 无变更 |
| | | `hb_protocol.py` | 无变更 |
| | | `DESIGN_DOC.md` | 更新 GUI 架构设计、组件树、渲染管线、数据流以反映田字格多路同时显示 |
| **1.4.0** | **2026-07-11** | **`hb_video_client.py`** | **重大更新**: 新增 H.264 解码支持。`_recv_loop` 自动识别 `VIDEO_DATA` (type=3) 帧, 调用 `_decode_h264()` 通过 PyAV 解码为 BGR。新增 `_get_h264_decoder()` 按 pipe_id 独立管理解码器实例。NV12/YUV 原有路径不改动。 |
| | | **`hb_protocol.py`** | `parse_frame_info` 返回值新增 `code_type` 字段 (H264=0, H265=1), 从帧头偏移 48 读取。 |
| | | **`requirements.txt`** | 新增 `av>=10.0.0` (PyAV) — H.264 解码可选依赖。连接 NV12 流时无需此依赖。 |
| | | **`tools/viotool/venc_stream/`** | **新增 J6B 设备端工具**: `venc_stream.c` (约 320 行) 实现 CIM4 四路 DDR → VPU 硬件 H.264 编码 → `hb_tool_send_video_pic()` TCP 输出。复用 `camera_sample` 的 VIO JSON + libhbplayer 协议栈。附带 `Makefile` 和 `run.sh` 一键启动脚本。 |
| | | **`CLAUDE.md`** | 更新项目概述、命令列表、架构图、设计要点、参考文档, 反映双解码模式和新工具链。 |
| | | `DESIGN_DOC.md` | 新增第 12 节「H.264 编解码链路」、第 13 节「设备端 venc_stream 工具」、更新目录结构、协议类型表、FAQ。 |
| **1.5.0** | **2026-07-25** | **`venc_stream.c / Makefile / run.sh`** | **4路SC361AT H.264编码全链路调通**: 修复 `bit_rate` 字段名(`h264_cbr_params`), `decoding_refresh_type` H264 兼容性, 码率控制参数补全(先 `hb_mm_mc_get_rate_control_config` 取FW默认值再覆盖17字段), 低延迟优化(`vbv_buffer_size` 3000→300ms, `frame_buf_count` 5→3)。新增 `CAM_PORTS` 与 `PIPE_IDS` 分离。`external_frame_buf=0` + NV12 逐行memcpy(处理stride对齐)。配置文件默认指向 `GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4`。编译工具链切换为 QNX `qcc`。 |
| | | **`hb_video_gui.py`** | 芯片版本显示修复 (J2→J6B, `CHIP_NAMES`映射), 配置文件持久化 `.j6b_player_config.json`(IP/端口/截图目录), 新增实时带宽显示(Mbps, 1秒采样), 去掉 `_update_display` 冗余图像拷贝(零拷贝引用传递)。 |
| | | **`hb_video_client.py`** | **低延迟解码修复**: `decoder.parse()` → `av.Packet(data)` 直送解码器, 消除 PyAV parse 内部缓冲累积(实验验证延迟从几秒降到~200ms)。`thread_count=1` 单线程解码。 |
| | | **`hb_protocol.py`** | 新增 `CHIP_NAMES = {0:'XJ3',1:'J5',2:'J6B'}` 显示映射字典。 |
| | | `DESIGN_DOC.md` | 新增第 14 节「问题排查实录」。更新 13.5-13.8 节编译部署参数。 |
| **1.6.0** | **2026-07-28** | **`hb_video_client.py`** | **重大重构**: 并行解码架构 + H.264 解码路径修复 + 带宽统计修正。**解码路径**: `av.Packet(data)` 直送 → `decoder.parse(data)` 逐个 NAL 单元解码 (修复 AVERROR_INVALIDDATA)。**线程模型**: 接收线程仅负责 socket read→分发, 每路独立解码线程 (`_pipe_decode_loop`) 通过 `queue.Queue(maxsize=2)` 并行处理。**解码器**: `thread_count` 1→0 (FFmpeg auto 多线程), `flags|=4` (OUTPUT_CORRUPT)。**带宽统计**: 从回调点移至 `_read_one_frame()` 数据读取点, 统计所有帧的实际接收字节。**移除**: 排空机制 (导致显示帧率从 25fps 降至 2fps)。**线程安全**: 回调列表加 `_callbacks_lock`。**稳定性验证**: 5 分钟/10 小时压力测试, 解码速率恒定 100fps, 零错误, 无延迟累积。 |
| | | **`hb_video_gui.py`** | 带宽统计改用 `client.get_stats()['total_bytes']` (实际接收字节数)。 |
| | | **`CLAUDE.md`** | 更新延迟优化说明、架构描述、H.264 解码路径、线程安全说明。 |
| | | **`DESIGN_DOC.md`** | 新增第 14.5 节「v1.6.0 调试实录」。更新第 5 节线程模型、第 12 节 H.264 编解码链路、第 14 节问题排查。新增第 9.6 节「生成 Windows 可执行文件 (exe)」— PyInstaller 打包命令与参数说明。 |

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [通信协议详解](#3-通信协议详解)
4. [模块设计](#4-模块设计)
5. [数据流与线程模型](#5-数据流与线程模型)
6. [NV12→BGR 色彩转换](#6-nv12bgr-色彩转换)
7. [帧同步机制](#7-帧同步机制)
8. [GUI 界面设计](#8-gui-界面设计)
9. [使用说明](#9-使用说明)
10. [错误处理与异常恢复](#10-错误处理与异常恢复)
11. [附录](#11-附录)
12. [H.264 编解码链路](#12-h264-编解码链路)
13. [设备端 venc_stream 工具](#13-设备端-venc_stream-工具)

---

## 1. 项目概述

### 1.1 背景

J6B 平台是地平线（Horizon Robotics）推出的智能驾驶芯片平台。其 SDK 内置了 `hb_tool_server` 组件，允许设备端通过 TCP 将视频流（NV12 YUV 或 RAW 格式）实时发送到 PC 端进行可视化调试。

本项目基于对 J6B SDK 中以下源文件的逆向分析，实现了一套完整的 PC 端视频流接收与显示工具：

| 参考源文件 | 作用 |
|-----------|------|
| `hb_tool_server.h` | 协议头定义、数据结构（`cmd_header_new_t`、`pic_info_t`）、枚举常量（`DataType`、`RawBit`、`YuvType`） |
| `hb_tool_server.c` | 服务端初始化（`hb_tool_start_transfer`）、发送接口（`hb_tool_send_yuv_pic` / `hb_tool_send_raw_pic`） |
| `camera_sample.c` | 发送端调用示例 — `vflow_show_init()` 启动传输、`vflow_show_img()` 逐帧发送 |
| `socket_manager.c` | TCP Socket 收发实现（`socket_data_write_bd`）、负载均衡（`send_data_load_balance`）、`send_data_to_pc_limit_bd` |
| `server_cmd.h` | 传输配置结构体 `tranfer_info_t`、内部状态管理结构体（`socket_rec_t`、`tool_base_t`） |

### 1.2 功能特性

| 功能 | 说明 |
|------|------|
| 远程视频流接收 | 通过以太网 TCP 连接 J6B 设备，实时接收 NV12 视频帧 |
| **多路视频支持** | **自动识别多路视频通道 (同一 TCP 连接交错传输)，田字格同时显示所有通道，自适应行列数** |
| 实时 GUI 显示 | 基于 tkinter + Pillow 的图形界面，支持画面缩放、FPS 叠加、通道概况面板 |
| 命令行模式 | 基于 OpenCV HighGUI 的命令行客户端，支持 `--pipe` 单通道 + `--no-display` 无头模式 |
| NV12→BGR 转换 | 纯 numpy 向量化实现 ITU-R BT.601 标准的色彩空间转换，支持 4K (3840×2160) |
| 帧同步 | 魔数搜索自动对齐帧边界，支持中途连接和断线恢复 |
| 截图保存 | GUI 和 CLI 均支持 JPG 格式截图，自动标注 pipe 编号 |
| 帧信息面板 | 实时显示帧类型、分辨率、帧序号、PIPE/CHN ID、数据长度等元数据 |
| FPS 统计 | 各路独立 1 秒滑动窗口帧率统计，GUI 顶部显示总 FPS |
| 连接状态管理 | 异步连接/断开，GUI 状态栏和日志面板双重反馈 |
| 跨平台支持 | Windows 10+ 和 Ubuntu 22.04+ 均可运行，字体自动适配 (DejaVu Sans / Consolas) |

### 1.3 依赖

| 依赖包 | 最低版本 | 用途 | 必需 |
|--------|---------|------|------|
| Python | 3.10 | 运行环境（使用了 `X \| None` 联合类型语法） | ✅ |
| numpy | 1.21.0 | NV12→BGR 向量化色彩转换 | ✅ |
| opencv-python | 4.5.0 | CLI 模式 OpenCV 窗口显示 + 帧保存 | CLI 必需 |
| Pillow | 9.0.0 | GUI 模式 BGR→RGB→ImageTk 渲染管线 | GUI 必需 |
| tkinter | — | GUI 窗口框架（Python 标准库自带） | GUI 必需 |

> **注意**: 
> - GUI 版本 (`hb_video_gui.py`) **仅依赖 Pillow**，不依赖 OpenCV
> - CLI 版本 (`hb_video_cli.py`) **仅依赖 OpenCV**，不依赖 Pillow
> - 核心通信层 (`hb_video_client.py`) 仅依赖 numpy，无 GUI 库依赖

安装命令：

```bash
# 最小安装 (仅核心通信层)
pip install numpy

# GUI 版本
pip install numpy Pillow

# CLI 版本
pip install numpy opencv-python

# 完整安装 (GUI + CLI)
pip install -r requirements.txt
```

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PC 端 (Windows/Linux)                        │
│                                                                      │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│  │  hb_video_gui.py │   │  hb_video_cli.py │   │  用户自定义程序  │  │
│  │  (tkinter+PIL)   │   │  (OpenCV HighGUI) │   │  (API 调用)     │  │
│  └────────┬─────────┘   └────────┬─────────┘   └───────┬────────┘  │
│           │                      │                      │           │
│           │    帧回调 callback(frame_info, bgr_image)   │           │
│           └──────────────────────┼──────────────────────┘           │
│                                  ▼                                   │
│           ┌──────────────────────────────────────────────┐          │
│           │         hb_video_client.py                   │          │
│           │  ┌──────────────┐  ┌──────────────────────┐ │          │
│           │  │ 连接管理      │  │ NV12 → BGR 转换      │ │          │
│           │  │ connect()    │  │ _nv12_to_bgr()       │ │          │
│           │  │ disconnect() │  │ (纯 numpy, BT.601)   │ │          │
│           │  │ start()/stop│  │                      │ │          │
│           │  ├──────────────┤  ├──────────────────────┤ │          │
│           │  │ 帧接收线程    │  │ 帧同步               │ │          │
│           │  │ _recv_loop() │  │ _sync_to_header()    │ │          │
│           │  │ (daemon)     │  │ (魔数搜索)            │ │          │
│           │  │              │  │                      │ │          │
│           │  │ 帧回调注册    │  │ 帧信息解析            │ │          │
│           │  │ register/    │  │ parse_frame_info()   │ │          │
│           │  │ remove/      │  │                      │ │          │
│           │  │ notify       │  │                      │ │          │
│           │  └──────────────┘  └──────────────────────┘ │          │
│           └──────────────────────┬───────────────────────┘          │
│                                  │                                   │
│           ┌──────────────────────┼───────────────────────┐          │
│           │        hb_protocol.py (协议层, 纯函数模块)     │          │
│           │  ┌────────────────┐  ┌────────────────────┐  │          │
│           │  │ 常量 & 枚举     │  │ 打包/解包/验证      │  │          │
│           │  │ TOOL_HEADER_*  │  │ pack_cmd_header()  │  │          │
│           │  │ DataType(21种) │  │ unpack_cmd_header()│  │          │
│           │  │ RawBit(8种)    │  │ verify_header()    │  │          │
│           │  │ YuvType(8种)   │  │ make_net_send_cfg_ │  │          │
│           │  │ VideoType(3种) │  │   packet()         │  │          │
│           │  │ SensorMode(4种)│  │ parse_frame_info() │  │          │
│           │  └────────────────┘  └────────────────────┘  │          │
│           └──────────────────────────────────────────────┘          │
│                                  │                                   │
│                          TCP Socket                                 │
│                                  │                                   │
└──────────────────────────────────┼───────────────────────────────────┘
                                   │
                     ═══════════════╪═══════════════
                        以太网 (Ethernet)
                     ═══════════════╪═══════════════
                                   │
┌──────────────────────────────────┼───────────────────────────────────┐
│                         J6B 设备端                                    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    hb_tool_server (C)                         │   │
│  │  ┌────────────────┐  ┌────────────────────────────────────┐  │   │
│  │  │ TCP Server     │  │ 负载均衡 send_data_load_balance     │  │   │
│  │  │ (libevent)     │  │ (多通道优先级调度, 48 槽位)          │  │   │
│  │  │ port: 10086    │  │ send_data_to_pc_limit_bd            │  │   │
│  │  └────────────────┘  └────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                  ▲                                   │
│  ┌───────────────────────────────┴──────────────────────────────┐   │
│  │  camera_sample / 用户应用程序                                  │   │
│  │  hb_tool_send_yuv_pic(event, &info, y, y_size, uv, uv_size)  │   │
│  │  hb_tool_send_raw_pic(event, &info, ptr, size, ext, ext_size) │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                  ▲                                   │
│  ┌───────────────────────────────┴──────────────────────────────┐   │
│  │  VIO (Video In/Out) / CAM 驱动层                               │   │
│  │  NV12 帧数据 (stride × height Y + stride × height/2 UV)       │   │
│  │  RAW 帧数据 (stride × height)                                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
hb_video_gui.py ──────┐
                      ├──▶ hb_video_client.py ──▶ hb_protocol.py
hb_video_cli.py ──────┘       │                      │
                         [socket, numpy,      [struct, enum]
                          threading, logging]
```

| 模块 | 依赖 | 职责 |
|------|------|------|
| `hb_protocol.py` | `struct`, `enum` | 纯协议层 — 常量、枚举、结构体布局、打包/解包/验证函数 |
| `hb_video_client.py` | `hb_protocol` + `socket` + `numpy` + `threading` + `logging` | 核心通信层 — TCP 连接、帧接收、NV12→BGR 转换、回调通知 |
| `hb_video_gui.py` | `hb_video_client` + `tkinter` + `PIL` | GUI 界面 — 窗口管理、视频渲染、截图、信息面板 |
| `hb_video_cli.py` | `hb_video_client` + `cv2` + `argparse` + `signal` | CLI 界面 — 命令行参数、OpenCV 显示、帧保存、键盘控制 |

---

## 3. 通信协议详解

### 3.1 通信流程

```
┌──────────┐                                          ┌──────────┐
│ PC Client │                                          │ J6B Server│
└─────┬─────┘                                          └─────┬─────┘
      │                                                      │
      │  ① TCP Connect (SYN → port 10086)                    │
      │─────────────────────────────────────────────────────▶│
      │  ② TCP Accept (SYN-ACK ←)                            │
      │◀─────────────────────────────────────────────────────│
      │                                                      │
      │  ③ NET_SEND_CFG 配置包 (104 bytes)                   │
      │     [ cmd_header_new_t(80B) + tranfer_info_t(24B) ]  │
      │─────────────────────────────────────────────────────▶│
      │     cmd_header_new_t.type   = NET_SEND_CFG (13)      │
      │     cmd_header_new_t.len    = 24                      │
      │     tranfer_info_t.tcp_open  = 1                     │
      │     tranfer_info_t.yuv_enable = 1                    │
      │                                                      │
      │  ④ 连续视频帧数据                                     │
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     cmd_header_new_t.type   = YUV_DATA (1)            │
      │     cmd_header_new_t.format = YUVNV12 (0)             │
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     ... (循环) ...                                    │
      │                                                      │
```

> **关键设计要点**: 设备端 (`hb_tool_server`) 仅在收到 PC 端发送的 `NET_SEND_CFG` 配置包（`tcp_open=1` 且启用对应数据类型）后，才会开始发送视频帧数据。这一握手逻辑在 `send_data_to_pc_limit_bd` 函数中实现：
> ```c
> // socket_manager.c:384
> if ((t_base->socket.socket_num) && (tranfer_ctrl->tcp_open) && (check_send_enable(t_base, header) != 0u)) {
>     ret = socket_data_write_bd(t_base, (void *)header, sizeof(cmd_header_new_t),
>         ptr, size, ptr1, size1, ptr2, size2, ptr3, size3);
> }
> ```
> **多路视频传输**: 5 路视频通过**同一个 TCP 连接**交错传输，通过帧头中的 `pipe_id` 字段区分通道。设备端的负载均衡机制 (`send_data_load_balance`) 在 5 个通道之间按优先级和输出计数动态调度，防止单个通道独占 TCP 发送缓冲区。
>
> **已知限制**: 设备端 `hb_tool_server` 在每次设备启动后**仅接受一次 TCP 连接**。连接断开后端口即关闭，需要重启设备才能再次连接。这是设备端 SDK 的限制，PC 端代码无法绕过。建议在 GUI 中避免频繁断开/重连，尽量一次性完成调试操作，断开后通过 SSH 重启设备 (`ssh root@<IP> "reboot"`)。

### 3.2 帧头结构体 `cmd_header_new_t`（80 字节）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     cmd_header_new_t (80 bytes)                      │
│                     小端序 (Little-Endian)                           │
├───────┬────────┬────────────────┬───────────────────────────────────┤
│ 偏移  │ 大小   │ 字段名          │ 说明                              │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x00  │ 4B     │ header_start   │ 魔数: 固定 0xCCDDEEFF              │
│ 0x04  │ 4B     │ header_check1  │ 魔数: 固定 0x6789ABCD              │
│ 0x08  │ 4B     │ header_check2  │ 保留: 固定 0x00000000              │
│ 0x0C  │ 4B     │ header_end     │ 魔数: 固定 0xFFEEDDCC              │
│ 0x10  │ 4B     │ header_crc     │ CRC 校验值 (当前未使用, 值为 0)     │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x14  │ 4B     │ len            │ 数据体总长度 (Y_size + UV_size)    │
│ 0x18  │ 4B     │ type           │ 数据类型 (1=YUV_DATA, 0=RAW_DATA)  │
│ 0x1C  │ 4B     │ format         │ 子格式 (0=YUVNV12, 2=RAW_12)      │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x20  │ 4B     │ width          │ 图像有效宽度 (像素)                  │
│ 0x24  │ 4B     │ height         │ 图像有效高度 (像素)                  │
│ 0x28  │ 4B     │ stride         │ 行步长 (可能 ≥ width, 硬件对齐)     │
│ 0x2C  │ 4B     │ frame_plane    │ Sensor 模式 (1=Normal, 2=DOL2, ...)│
│ 0x30  │ 4B     │ code_type      │ 编码类型 (0=H264, 1=H265, 2=PPS)  │
│ 0x34  │ 4B     │ pipe_info      │ Pipeline 附加信息                    │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x38  │ 4B     │ pipe_id        │ Pipeline 编号 (0~23)               │
│ 0x3C  │ 4B     │ chn_id         │ 通道编号 (YUV channel / RAW plane) │
│ 0x40  │ 4B     │ frame_id       │ 帧序号 (单调递增)                    │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x44  │ 4B     │ chip_version   │ 芯片版本 (0=XJ3, 1=J5, 2=J6)      │
│ 0x48  │ 4B     │ plugin_id      │ 插件 ID (0 = 未使用)                │
│ 0x4C  │ 4B     │ reserved2      │ 保留字段 (0 = 未使用)                │
└───────┴────────┴────────────────┴───────────────────────────────────┘
```

> **Python 打包格式**: `struct.pack("<" + "I" * 20, ...)` — 20 个 `uint32_t`，小端序，与 ARM 嵌入式平台一致。
> **Python 字段索引**: 代码中定义了 `IDX_HEADER_START` (0) 到 `IDX_RESERVED2` (19) 共 20 个常量，通过列表索引访问各字段。

### 3.3 传输配置结构体 `tranfer_info_t`（24 字节）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     tranfer_info_t (24 bytes)                        │
│                     小端序 (Little-Endian)                           │
├───────┬────────┬────────────────┬───────────────────────────────────┤
│ 偏移  │ 大小   │ 字段名          │ 说明                              │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x00  │ 1B     │ tcp_open       │ TCP 传输主开关 (1=开启)            │
│ 0x01  │ 1B     │ raw_enable     │ RAW 数据使能                      │
│ 0x02  │ 1B     │ raw_serial_num │ RAW 序列号                        │
│ 0x03  │ 1B     │ yuv_enable     │ YUV 数据使能 (1=开启)             │
│ 0x04  │ 1B     │ yuv_serial_num │ YUV 序列号                        │
│ 0x05  │ 1B     │ jepg_enable    │ JPEG 数据使能                     │
│ 0x06  │ 1B     │ video_enable   │ 编码视频使能 (H.264/H.265)        │
│ 0x07  │ 1B     │ video_code     │ 视频编码格式                      │
│ 0x08  │ 2B     │ bit_stream     │ 比特流参数                        │
│ 0x0A  │ 2B     │ fream_interval │ 帧间隔 *                          │
│ 0x0C  │ 2B     │ pipe_line      │ Pipeline 编号                     │
│ 0x0E  │ 2B     │ channel_id     │ 通道 ID                           │
│ 0x10  │ 4B     │ param_id       │ 视频配置参数 ID (param_buf_t)     │
│ 0x14  │ 4B     │ param_data     │ 视频配置参数数据 (param_buf_t)    │
└───────┴────────┴────────────────┴───────────────────────────────────┘
```

> \* `fream_interval` 为原始 C 代码中的拼写 (frame → fream)，此处保留原样以保持协议兼容性。
> **Python 打包格式**: `struct.pack("<8B4H2I", ...)` — 8 个 `uint8_t` + 4 个 `uint16_t` + 2 个 `uint32_t`。

### 3.4 数据类型枚举

`DataType` 枚举完整定义在 `hb_protocol.py` 中，共 21 种类型。本工具主要处理以下类型：

| 枚举值 | 名称 | 方向 | 说明 |
|--------|------|------|------|
| 0 | `RAW_DATA` | 设备→PC | RAW Bayer 数据 |
| 1 | `YUV_DATA` | 设备→PC | YUV 数据（NV12, 原始像素流） |
| 2 | `JPEG_DATA` | 设备→PC | JPEG 压缩数据 |
| 3 | `VIDEO_DATA` | 设备→PC | **H.264/H.265 编码码流 (v1.4.0 新增支持)** |
| 13 | `NET_SEND_CFG` | PC→设备 | **传输配置握手命令** |

其余类型（`STATS_AWB_DATA`、`STATS_AEfull_DATA`、`ISP_INFO_DATA`、`ACT_CTL_DATA` 等）用于 ISP 调试和寄存器控制，本工具在接收循环中自动跳过（`_recv_loop` 中 `if data_type not in (DataType.YUV_DATA, DataType.RAW_DATA, DataType.VIDEO_DATA):` 分支）。`VIDEO_DATA` 时调用 `_decode_h264()` 通过 PyAV 解码为 BGR 图像, 对上层透明。

### 3.5 NV12 数据布局

```
┌─────────────────────────────────────────────────────────────┐
│                      Y Plane (亮度)                          │
│              stride × height 字节                            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Y₀₀  Y₀₁  Y₀₂  ...  Y₀(width-1)  │  padding ...   │   │
│  │ Y₁₀  Y₁₁  Y₁₂  ...  Y₁(width-1)  │  padding ...   │   │
│  │ ...                                                  │   │
│  │ Y₍h₋₁₎₀ Y₍h₋₁₎₁ ... Y₍h₋₁₎₍w₋₁₎ │  padding ...   │   │
│  └──────────────────────────────────────────────────────┘   │
│          ↑── 有效宽度 = width ──↑  ↑── padding ──↑          │
│          ←────────── stride ──────────────→                 │
├─────────────────────────────────────────────────────────────┤
│                    UV Plane (交错色度)                        │
│           stride × height / 2 字节                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ U₀₀ V₀₀ U₀₁ V₀₁ U₀₂ V₀₂ ... │  padding ...        │   │
│  │ U₁₀ V₁₀ U₁₁ V₁₁ U₁₂ V₁₂ ... │  padding ...        │   │
│  │ ...                                                  │   │
│  └──────────────────────────────────────────────────────┘   │
│     每个 2×2 像素块共用一对 (U, V) 色度值                      │
│     UV 在字节流中交错存储: U₀V₀U₁V₁U₂V₂...                  │
└─────────────────────────────────────────────────────────────┘

总数据量: stride × height × 1.5 字节
示例: 1920×1080 stride=1920 → 1920×1080×1.5 = 3,110,400 字节
```

---

## 4. 模块设计

### 4.1 `hb_protocol.py` — 协议层（342 行）

**职责**: 定义所有协议常量、枚举、结构体布局、打包/解包/验证函数。无状态纯函数模块，所有函数无副作用。

**枚举类**:

| 类名 | 成员数 | 说明 |
|------|--------|------|
| `RawBit` | 8 | RAW 数据位宽 (8/10/12/14/16 + 3 种压缩格式) |
| `YuvType` | 8 | YUV 数据格式 (NV12/420/422/444/I420/RGB888/10bit/12bit) |
| `VideoType` | 3 | 视频编码类型 (H264/H265/PPS) |
| `DataType` | 21 | 完整数据类型枚举 |
| `SensorMode` | 4 | Sensor 工作模式 (Normal/DOL2/DOL3/DOL4) |

**核心常量**:

| 常量 | 值 | 说明 |
|------|------|------|
| `TOOL_HEADER_START_N` | `0xCCDDEEFF` | 帧起始魔数 |
| `TOOL_HEADER_CHECK1_N` | `0x6789ABCD` | 帧校验魔数 1 |
| `TOOL_HEADER_CHECK2_N` | `0x00000000` | 帧校验魔数 2 |
| `TOOL_HEADER_END_N` | `0xFFEEDDCC` | 帧结束魔数 |
| `TOOL_VERSION` | `2` | 芯片版本 (0=XJ3, 1=J5, 2=J6) |
| `DEFAULT_PORT` | `10086` | 默认 TCP 端口 |
| `CMD_HEADER_SIZE` | `80` | 帧头长度 (字节) |
| `TRANSFER_INFO_SIZE` | `24` | 传输配置长度 (字节) |
| `CMD_HEADER_FORMAT` | `"<" + "I" * 20` | struct 打包格式字符串 |
| `TRANSFER_INFO_FORMAT` | `"<8B4H2I"` | struct 打包格式字符串 |

**核心 API**:

| 函数 | 签名 | 说明 |
|------|------|------|
| `pack_cmd_header` | `(list[20]) → bytes` | 将 20 个 uint32 列表打包为 80 字节二进制 |
| `unpack_cmd_header` | `(bytes) → list[20]` | 将 80 字节二进制解包为 20 个 uint32 列表 |
| `verify_header` | `(list[20]) → bool` | 验证三个魔数 (start/check1/end) 是否正确 |
| `make_yuv_frame_header` | `(width, height, stride, pipe_id, chn_id, frame_id, y_size, uv_size) → bytes` | 构建 YUV 帧头 (供理解协议，PC 端不发送帧) |
| `make_net_send_cfg_packet` | `(enable_yuv, enable_raw, pipe_line, channel_id) → bytes` | 构建 104 字节 NET_SEND_CFG 握手包 (80B 帧头 + 24B 配置) |
| `parse_frame_info` | `(list[20]) → dict` | 从 header 字段提取帧信息字典 (10 个字段) |

**`parse_frame_info` 返回字典结构**:

```python
{
    'type':       1,           # DataType 枚举值
    'type_name':  'YUV_DATA',  # 类型名称字符串
    'format':     0,           # 子格式 (0=YUVNV12, 2=RAW_12)
    'width':      1920,        # 有效宽度
    'height':     1080,        # 有效高度
    'stride':     1920,        # 行步长
    'pipe_id':    0,           # Pipeline 编号
    'chn_id':     0,           # 通道编号
    'frame_id':   12345,       # 帧序号
    'data_len':   3110400,     # 数据体长度
    'chip_ver':   2,           # 芯片版本
}
```

### 4.2 `hb_video_client.py` — 网络通信与解码层（v1.4.0 更新: H.264 解码支持）

**职责**: TCP 连接管理、帧接收、**自动识别 NV12/H.264 双格式**、解码、帧回调通知。这是整个项目的核心引擎。

**解码模式自动选择**:

| 帧头 type | 设备端来源 | 解码器 | 依赖 |
|-----------|-----------|--------|------|
| 1 (YUV_DATA) | camera_sample (NV12 原始流) | `_nv12_to_bgr()` 纯 numpy BT.601 | numpy |
| 3 (VIDEO_DATA) | venc_stream (H.264 压缩流) | `_decode_h264()` PyAV | `pip install av` |

**核心类**: `HBVideoClient`

**构造参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | `str` | — | 设备 IP 地址 |
| `port` | `int` | `10086` | TCP 端口 |
| `enable_yuv` | `bool` | `True` | 启用 YUV 数据接收 |
| `enable_raw` | `bool` | `False` | 启用 RAW 数据接收 |
| `pipe_line` | `int` | `0` | Pipeline 编号 |
| `channel_id` | `int` | `0` | 通道编号 |

**公有方法**:

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `connect()` | `bool` | 建立 TCP 连接 + 发送 NET_SEND_CFG 握手包 |
| `disconnect()` | `None` | 关闭 TCP 连接 (先 shutdown 再 close) |
| `start()` | `bool` | 调用 `connect()` 后创建 daemon 接收线程 |
| `stop()` | `None` | 设置 `_running=False`，join 接收线程 (3s 超时)，调用 `disconnect()` |
| `register_frame_callback(cb)` | `None` | 注册帧回调 `cb(frame_info: dict, bgr_image: np.ndarray)` |
| `remove_frame_callback(cb)` | `None` | 移除已注册的帧回调 |
| `get_stats()` | `dict` | 返回 `{'frame_count': int, 'error_count': int}` |
| `is_connected` | `bool` | **属性**: 返回 `self._sock is not None` |

**内部方法**:

| 方法 | 签名 | 说明 |
|------|------|------|
| `_recv_loop()` | `() → None` | 接收线程主循环: 读头(80B)→验证魔数→读体(len)→根据 type 选择解码器→通知回调 |
| `_recv_exact(size)` | `(int) → bytes \| None` | 精确接收指定字节数，超时或断开返回 `None` |
| `_sync_to_header(partial_data)` | `(bytes) → bool` | 魔数搜索帧同步，最多扫描 1MB |
| `_nv12_to_bgr(data, w, h, stride)` | `(bytes, int, int, int) → np.ndarray` | **静态方法**: NV12→BGR 色彩转换 (ITU-R BT.601) |
| `_decode_h264(data, pipe_id, info)` | `(bytes, int, dict) → np.ndarray \| None` | **v1.4.0 新增**: H.264 AnnexB→PyAV 解码为 BGR, 返回 None 表示需要更多数据 |
| `_get_h264_decoder(pipe_id)` | `(int) → av.CodecContext` | **v1.4.0 新增**: 获取/创建指定 pipe 的 H.264 解码器实例, 按 pipe_id 独立管理 |
| `_notify_frame(info, img)` | `(dict, np.ndarray) → None` | 遍历回调列表，逐个调用，异常不中断 |

**`_recv_loop` 接收循环详细流程 (v1.4.0 更新)**:

```
while self._running:
    ┌─ 1. _recv_exact(80) → header_data
    │     失败 → 检查 _running, 继续或退出
    │
    ├─ 2. unpack_cmd_header(header_data) → header_fields (20 个 uint32)
    │     失败 → error_count++, continue
    │
    ├─ 3. verify_header(header_fields) → bool
    │     失败 → _sync_to_header(header_data)
    │
    ├─ 4. 检查 data_type ∈ {YUV_DATA, RAW_DATA, VIDEO_DATA}
    │     否 → 丢弃, continue
    │
    ├─ 5. data_len == 0 → continue
    │
    ├─ 6. _recv_exact(data_len) → body_data
    │
    ├─ 7. parse_frame_info(header_fields) → frame_info
    │
    ├─ 8. 根据 data_type 选择解码器:
    │     YUV_DATA(1)  → _nv12_to_bgr()  numpy 转换
    │     VIDEO_DATA(3) → _decode_h264()  PyAV 解码
    │     RAW_DATA(0)  → _nv12_to_bgr()  (与 YUV 同路径)
    │
    ├─ 9. _lock: frame_count++
    │
    └─ 10. _notify_frame(frame_info, bgr_image)
```

### 4.3 `hb_video_gui.py` — GUI 界面层（v1.3.0 更新: 田字格多路同时显示）

**职责**: 提供 tkinter 图形界面，包含连接管理、**多路视频田字格同时显示**、视频渲染、信息显示、截图功能。**仅依赖 Pillow (PIL) 进行图像处理，不依赖 OpenCV**。

**核心类**: `HBVideoGUI`

**多路视频数据结构**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `_pipe_frames` | `dict[int, tuple[np.ndarray, dict]]` | **多路帧缓冲**: pipe_id → (bgr_image, frame_info) |
| `_pipe_fps` | `dict[int, float]` | 各路独立 FPS 值 |
| `_pipe_fps_count` | `dict[int, int]` | 各路 FPS 帧计数 |
| `_available_pipes` | `list[int]` | 已发现的 pipe 列表 |
| `_selected_pipe` | `int \| None` | 当前选中的 pipe (None = 全部模式，仅影响截图目标 + 详情面板) |
| `_pipe_cells` | `dict[int, dict]` | **田字格显示单元**: pipe_id → `{"frame": tk.Frame, "canvas": tk.Canvas, "photo": ImageTk.PhotoImage}` |

**田字格布局算法**:

| 通道数 | 行列 | 网格 |
|--------|------|------|
| 1 | 1×1 | 单路全屏 |
| 2 | 1×2 | 横向并排 |
| 3~4 | 2×2 | 田字格 |
| 5~6 | 2×3 | 两行三列 |
| 7~9 | 3×3 | 三行三列 |

> 计算公式: `cols = ceil(sqrt(N))`, `rows = ceil(N / cols)`。`_calculate_grid(count)` 静态方法实现。

**关键方法**:

| 方法 | 说明 |
|------|------|
| `_build_ui()` | 构建完整 UI 布局 (控制面板 → 视频田字格容器 + 信息面板 → 状态栏) |
| `_build_control_panel(parent)` | 控制面板: IP 输入框、端口输入框、连接按钮、**通道下拉选择 (截图目标 + 详情面板)**、截图按钮、目录选择、FPS 标签 |
| `_build_video_panel(parent)` | 视频面板: `grid_container` 容器 (动态行列)，无信号时显示占位 Label |
| `_build_info_panel(parent)` | 信息面板: **各通道概况面板** + 当前帧详情 + 日志 (深色终端风格) + 滚动条 |
| `_build_status_bar(parent)` | 状态栏: 显示当前状态文字 |
| `_calculate_grid(count)` | **静态方法**: 根据通道数计算最佳田字格行列数 (ceil(sqrt) 策略) |
| `_arrange_grid()` | **动态重排网格**: 按活跃通道数配置 `grid_rowconfigure`/`grid_columnconfigure` 权重，等比例伸缩 |
| `_get_or_create_cell(pipe_id)` | **获取或创建显示单元**: 首次出现时创建 `Frame + Canvas`，自动调用 `_arrange_grid()` |
| `_destroy_all_cells()` | 断开时销毁所有网格单元，恢复无信号提示 |
| `_toggle_connection()` | 连接/断开切换入口 |
| `_connect()` | 在后台线程中创建 `HBVideoClient` 并调用 `start()`，通过 `root.after()` 切回主线程 |
| `_on_connected(host, port)` | 连接成功回调: 更新按钮状态、启用截图 |
| `_on_connect_failed()` | 连接失败回调: 恢复按钮状态、弹窗提示 |
| `_disconnect()` | 停止客户端、更新按钮状态、禁用截图、**清空 pipe 帧缓冲和下拉列表、销毁所有网格单元** |
| `_on_pipe_selected(event)` | **通道选择事件** (仅影响截图目标 + 右侧详情面板，不影响田字格全量显示) |
| `_update_pipe_combo()` | **动态更新通道下拉列表**: 自动发现新 pipe 并添加到 Combobox |
| `_on_frame_received(info, img)` | **帧回调 (接收线程)**: 按 pipe_id 分路存储到 `_pipe_frames`，各路独立 FPS 统计 |
| `_update_display()` | **30ms 定时器 (主线程)**: 更新下拉列表 → 批量获取所有通道帧快照 → 为每个通道创建/获取显示单元 → 逐个渲染 |
| `_render_cell(pipe_id, img, info)` | **单路渲染**: 计算缩放比例 → BGR→RGB→PIL.Image→`resize(LANCZOS)`→`ImageTk.PhotoImage`→Canvas 居中绘制 + 顶部 24px 黑色信息条叠加 (Pipe ID / 分辨率 / FPS / 帧序号) |
| `_update_info_panel_for_selected(frames_snapshot)` | 更新右侧详情面板 (显示选中通道或最后活跃通道) |
| `_update_info_panel(info, pipe_id)` | 更新当前帧详情 Text 组件 (10 行信息，含通道号和 FPS) |
| `_update_overview_panel()` | **更新各通道概况面板**: 显示所有 pipe 的分辨率、FPS、帧序号 |
| `_save_snapshot()` | 当前帧保存为 JPG (通过 PIL)，**自动标注 pipe 编号** |
| `_select_snapshot_dir()` | 打开目录选择对话框 |
| `_log(message)` | 日志面板追加带时间戳的消息 |
| `_on_close()` | 窗口关闭处理: 连接中则弹窗确认 |

### 4.4 `hb_video_cli.py` — 命令行界面（179 行）

**职责**: 无 GUI 框架依赖的命令行客户端，支持 OpenCV HighGUI 窗口显示、帧保存、键盘控制。**仅依赖 OpenCV (cv2)**。

**核心类**: `CLIVideoClient`

**构造参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | `str` | — | 设备 IP 地址 |
| `port` | `int` | `10086` | TCP 端口 |
| `save_frames` | `bool` | `False` | 是否保存每一帧到文件 |
| `save_dir` | `str` | `"./frames"` | 帧保存目录 |
| `enable_display` | `bool` | `True` | 是否显示 OpenCV 窗口 |

**命令行参数** (argparse):

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `host` | 设备 IP 地址（位置参数，必填） | — |
| `port` | TCP 端口（位置参数，可选） | `10086` |
| `--save` | 启用帧保存到文件 | `False` |
| `--save-dir` | 帧保存目录 | `./frames` |
| `--no-display` | 禁用 OpenCV 显示窗口（仅保存帧） | `False` |

**键盘快捷键** (OpenCV 窗口):

| 按键 | 功能 |
|------|------|
| `q` / `ESC` (27) | 退出程序 |
| `s` | 截图保存到 `./snapshots/snap_YYYYMMDD_HHMMSS.jpg` |
| `Ctrl+C` | 终端中断退出 (SIGINT 信号处理) |

**`on_frame` 回调流程**:

```
1. frame_count++, fps_frame_count++
2. 每秒输出一行统计: "帧: NNNNNN | FPS: NN.N | 分辨率: W×H | ID: #NNN"
3. 如果 --save: cv2.imwrite("frame_NNNNNN_p0_fNNNNN.jpg", bgr_image)
4. 如果 --no-display 为 False:
   a. 复制帧 → cv2.putText(FPS + Frame ID) → cv2.imshow()
   b. cv2.waitKey(1) 检测按键 (q/ESC/s)
```

---

## 5. 数据流与线程模型

### 5.1 线程架构 (GUI 模式, v1.6.0)

```
┌─────────────────────────────────────────────────────────────────────┐
│                      线程模型 (GUI 模式, v1.6.0)                     │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Main Thread (主线程 / GUI 线程)                               │   │
│  │  - tkinter 事件循环 (root.mainloop)                            │   │
│  │  - 30ms 定时器 _update_display()                              │   │
│  │  - 从 _pipe_frames 批量获取所有通道帧快照 (_frame_lock 保护)      │   │
│  │  - 为每个通道创建/获取网格显示单元 (_get_or_create_cell)          │   │
│  │  - 遍历 _pipe_cells 逐个渲染 (_render_cell)                      │   │
│  │  - BGR→RGB→PIL.Image→ImageTk.PhotoImage→Canvas 渲染           │   │
│  │  - 所有 tkinter 组件更新必须在此线程执行                         │   │
│  │  - 带宽刷新: 从 client.get_stats()['total_bytes'] 每秒计算       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 帧回调 _on_frame_received()            │
│                              │ (在各解码线程中并发调用, 受 _callbacks_lock 保护)│
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Recv Thread (接收线程, daemon=True)                           │   │
│  │  - _recv_loop() 循环                                          │   │
│  │  - socket.recv() → _read_one_frame()                          │   │
│  │  - 仅负责: 读帧头→验证→读数据体→统计带宽→分发到解码队列          │   │
│  │  - queue.Queue(maxsize=2).put(body_data, frame_info)           │   │
│  │  - 线程名: "HB-Recv"                                          │   │
│  └──────────────┬───────────────────────────────────────────────┘   │
│                 │ queue.Queue(maxsize=2) × N                         │
│     ┌───────────┼───────────┬───────────┐                           │
│     ▼           ▼           ▼           ▼                           │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐                          │
│  │Decode│  │Decode│  │Decode│  │Decode│  每路独立解码线程            │
│  │Pipe7 │  │Pipe8 │  │Pipe9 │  │Pipe10│  (惰性创建, daemon=True)    │
│  │      │  │      │  │      │  │      │                          │
│  │ parse│  │ parse│  │ parse│  │ parse│  decoder.parse(data)       │
│  │decode│  │decode│  │decode│  │decode│  decoder.decode(packet)     │
│  │ →BGR │  │ →BGR │  │ →BGR │  │ →BGR │  to_ndarray(bgr24)         │
│  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘                          │
│     └─────────┴─────────┴─────────┘  _notify_frame() 回调           │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Connect Thread (临时线程, 连接时创建, daemon=True)             │   │
│  │  - 创建 HBVideoClient 实例                                     │   │
│  │  - 注册帧回调 _on_frame_received                               │   │
│  │  - 调用 client.start() → connect() + 创建 Recv Thread          │   │
│  │  - 完成后通过 root.after(0, callback) 切回主线程                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 线程架构 (CLI 模式)

```
同 GUI 模式的线程模型 (接收线程 + 每路独立解码线程)。
帧回调在解码线程中调用, 执行 cv2.imwrite / cv2.imshow 等操作。
```

### 5.3 帧数据流 (完整管道, v1.6.0)

```
TCP Socket (另一端: J6B 设备)
    │
    ▼
socket.recv() ──────────── TCP 流式数据
    │
    ▼
_recv_exact(80) ─────────── 帧头 (80 bytes)
    │
    ▼
unpack_cmd_header() ─────── struct.unpack("<20I", data) → 20 个 uint32_t
    │
    ▼
verify_header() ─────────── 检查 header_start==0xCCDDEEFF
    │                       AND header_check1==0x6789ABCD
    │                       AND header_end==0xFFEEDDCC
    │
    ├── 失败 → _sync_to_header() ── 逐字节搜索 0xCCDDEEFF
    │           │                   找到后验证完整帧头
    │           │                   读取并丢弃 data_len 字节
    │           │                   返回 True → 下一轮 recv 从新帧头开始
    │           └── 超时 → error_count++, continue
    │
    ▼ 成功
检查 data_type ∈ {YUV_DATA(1), RAW_DATA(0), VIDEO_DATA(3)}
    │
    ├── 否 → _recv_exact(data_len) 丢弃数据体, continue
    │
    ▼ 是
_recv_exact(data_len) ────── 数据体
    │
    ▼
parse_frame_info() ──────── 提取 width/height/stride/pipe_id 等
    │
    ▼
total_bytes += 80 + data_len ── 带宽统计 (所有帧, 非仅回调帧)
    │
    ▼
queue.Queue(maxsize=2).put((body_data, frame_info))
    │ 分发到对应 pipe_id 的解码队列
    │ (接收线程仅做 I/O, 立即返回继续读下一帧)
    │
    ▼
【解码线程】queue.get()
    │
    ├── data_type == VIDEO_DATA(3)
    │   └── decoder.parse(data) → packets
    │       └── for each packet: decoder.decode(packet) → frames
    │           └── for each frame: to_ndarray(bgr24) → BGR numpy array
    │
    └── data_type == YUV_DATA(1) / RAW_DATA(0)
        └── _nv12_to_bgr(body, w, h, stride) → BGR numpy array
    │
    ▼
frame_count += 1 (受 _lock 保护)
    │
    ▼
_notify_frame(frame_info, bgr_image)
    │ 线程安全回调 (受 _callbacks_lock 保护)
    │
    ▼
【GUI/CLI 回调】_on_frame_received / on_frame
    │ bgr_image.copy() 深拷贝 → _pipe_frames[pipe_id] = (...)
    │
    ▼
【主线程 30ms】_update_display()
    │ 取 _pipe_frames 引用 → _render_cell() → 绘制
```

### 5.4 线程安全策略 (v1.6.0 更新)

| 保护对象 | 锁 | 策略 |
|----------|------|------|
| `_pipe_frames` / `_available_pipes` | `_frame_lock` (GUI) | 解码线程写入时深拷贝 (`np.copy()`)，GUI 线程读取引用，`_frame_lock` 保护字典操作 |
| `frame_count` / `error_count` / `total_bytes` | `_lock` (HBVideoClient) | 统计计数器，在接收线程和解码线程中访问, `_lock` 保护 |
| `_frame_callbacks` 列表 | `_callbacks_lock` (HBVideoClient) | 多个解码线程并发调用 `_notify_frame`, 先快照列表再遍历 |
| Socket 操作 | 无锁 | 仅接收线程访问 socket，主线程通过 `_running` 标志和 `stop()` 间接控制 |
| `_pipe_queues` / `_pipe_threads` | 无锁 | 仅在 `_get_or_start_pipe_worker` (接收线程) 创建, 解码线程 daemon 运行 |

> **关键设计**: 接收线程仅做 socket I/O + 分发, 不做解码。帧回调在各解码线程中**并发**调用 (`_callbacks_lock` 保护), 回调内部必须尽快返回（只做深拷贝，不做耗时操作）。GUI 渲染在主线程中通过 30ms 定时器**异步**执行。

---

## 6. NV12→BGR 色彩转换

### 6.1 转换流程

```
NV12 数据 (bytes, 总长度 = stride × height × 1.5)
    │
    ├─▶ Y Plane: 前 stride × height 字节
    │       │
    │       ▼
    │   np.frombuffer(dtype=uint8).reshape(height, stride)
    │       │
    │       ├── stride > width ? → y = y[:, :width] (裁剪右侧 padding)
    │       └── stride == width ? → 保持
    │
    └─▶ UV Plane: 后 stride × height/2 字节
            │
            ▼
        np.frombuffer(dtype=uint8).reshape(height//2, stride)
            │
            ├── stride > width ? → uv = uv[:, :width] (裁剪右侧 padding)
            └── stride == width ? → 保持
            │
            ├──▶ U = uv[:, 0::2]  (偶数列提取)
            │        │
            │        ▼
            │    np.repeat(np.repeat(U, 2, axis=0), 2, axis=1)
            │    最近邻上采样 2× → 全分辨率 U 矩阵
            │
            └──▶ V = uv[:, 1::2]  (奇数列提取)
                     │
                     ▼
                 np.repeat(np.repeat(V, 2, axis=0), 2, axis=1)
                 最近邻上采样 2× → 全分辨率 V 矩阵
            │
            └──▶ 尺寸修正: u_upsampled[:h, :w], v_upsampled[:h, :w]
                      (处理奇数高度/宽度)
    │
    ▼
ITU-R BT.601 矩阵变换 (YUV → RGB, TV Range: Y∈[16,235], UV∈[16,240])
    │
    ├── R = 1.164 × (Y - 16) + 0.000 × (U - 128) + 1.596 × (V - 128)
    ├── G = 1.164 × (Y - 16) - 0.392 × (U - 128) - 0.813 × (V - 128)
    ├── B = 1.164 × (Y - 16) + 2.017 × (U - 128) + 0.000 × (V - 128)
    │
    ▼
np.clip([R, G, B], 0, 255).astype(uint8)
    │
    ▼
np.stack([B, G, R], axis=-1) → BGR 图像 (OpenCV 格式)
    shape: (height, width, 3), dtype: uint8
```

### 6.2 为什么不用 OpenCV 的 `cvtColor`？

| 原因 | 说明 |
|------|------|
| **减少依赖** | `hb_video_client.py` 作为核心通信层，不依赖 OpenCV，可在纯 numpy 环境运行 |
| **stride 处理** | 设备端 NV12 的 stride 可能大于 width（硬件对齐要求，如 1920 对齐到 2048），OpenCV 的 `cvtColor` 不直接支持 stride≠width 的情况 |
| **可控性** | 自定义实现可精确控制上采样算法（当前使用最近邻，可替换为双线性插值） |
| **精度** | 使用 `np.float32` 中间类型保证精度，对标 BT.601 标准 |

### 6.3 性能数据

| 分辨率 | NV12 数据量 | BGR 输出 | 转换耗时 (估算) |
|--------|------------|----------|----------------|
| 640×480 | 460 KB | 900 KB | ~2 ms |
| 1280×720 | 1.38 MB | 2.7 MB | ~5 ms |
| 1920×1080 | 3.1 MB | 6.2 MB | ~12 ms |
| 3840×2160 | 12.4 MB | 24.9 MB | ~45 ms |

> 纯 numpy 向量化实现，无 Python 循环。性能瓶颈在 `np.repeat` 上采样（最近邻，内存带宽密集型）。

---

## 7. 帧同步机制

### 7.1 问题背景

TCP 是**流式协议**，没有消息边界。当网络抖动导致丢包、PC 端启动时恰好处于帧数据中间位置、或协议栈缓冲区中存在残留数据时，可能无法从正确的字节偏移开始解析帧头。

### 7.2 同步算法 `_sync_to_header()`

```
输入: partial_data — 已读取的 80 字节 (可能无效)
输出: True — 同步成功, False — 超时 (1MB 扫描上限)

算法伪代码:

  sync_buffer = bytearray(partial_data)          # 初始化搜索缓冲区
  start_magic = b'\xff\xee\xdd\xcc'              # 0xCCDDEEFF 小端序

  loop max_scan = 1MB / 4096 次:

    pos = sync_buffer.find(start_magic)           # 搜索起始魔数

    if pos == -1:                                 # 未找到
        chunk = sock.recv(4096)                   # 读取更多数据
        if not chunk: return False                # 连接断开
        sync_buffer.extend(chunk)
        sync_buffer = sync_buffer[-4:]            # 保留最后 4 字节 (防跨边界)
        continue

    # 找到起始魔数
    if len(sync_buffer) >= pos + 80:              # 有完整帧头
        candidate = sync_buffer[pos:pos+80]
        fields = unpack_cmd_header(candidate)     # 解包
        if verify_header(fields):                 # 验证三个魔数
            data_len = fields[IDX_LEN]
            if data_len > 0:
                body = _recv_exact(data_len)      # 读取并丢弃数据体
                if body is not None:
                    log("同步成功, 跳过 N 字节")
                    return True                   # ★ 下一轮 recv 从新帧头开始
                return False
            return True
        else:
            sync_buffer = sync_buffer[pos+1:]     # 假阳性, 继续搜索
    else:
        chunk = sock.recv(4096)                   # 数据不足, 读取更多
        sync_buffer.extend(chunk)

  return False  # 超时
```

### 7.3 适用场景

| 场景 | 触发原因 | 行为 |
|------|----------|------|
| 正常帧流 | — | `verify_header()` 通过，直接解析帧 |
| 网络抖动丢包 | 部分字节丢失导致帧头偏移 | 自动搜索下一帧头，丢弃损坏帧 |
| 中途连接 | 连接时恰好在帧数据中间 | 跳过当前半帧，对齐到下一帧起始 |
| 协议不匹配 | 设备端版本不兼容 | 扫描 1MB 后超时，返回 `False`，`error_count++` |
| 缓冲区残留 | 上次断开时有未消费数据 | 通过魔数搜索跳过残留数据 |

---

## 8. GUI 界面设计

### 8.1 组件树

```
tk.Tk (root)  — 标题 "J6B Video Player - 多路视频客户端"
│              默认大小 1400×900, 最小 1024×700
└── ttk.Frame (main_frame, padding=4)
    │
    ├── ttk.LabelFrame "控制面板" (padding=6)
    │   └── ttk.Frame (row1)
    │       ├── ttk.Label "设备 IP:"
    │       ├── ttk.Entry (ip_entry, width=16, default="172.16.0.14")
    │       ├── ttk.Label "端口:"
    │       ├── ttk.Entry (port_entry, width=8, default="10086")
    │       ├── ttk.Button "连接" (connect_btn) → _toggle_connection()
    │       ├── ttk.Separator (VERTICAL)
    │       ├── ttk.Label "通道:"
    │       ├── ttk.Combobox (pipe_combo, readonly, 截图目标 + 详情面板选择)
    │       ├── ttk.Separator (VERTICAL)
    │       ├── ttk.Button "截图保存" (snapshot_btn, 初始 DISABLED) → _save_snapshot()
    │       ├── ttk.Button "选择保存目录" → _select_snapshot_dir()
    │       └── ttk.Label "总FPS: --" (fps_label, RIGHT 对齐)
    │
    ├── ttk.Frame (content_frame)
    │   ├── ttk.LabelFrame "视频画面" (padding=2, LEFT, expand=True)
    │   │   └── tk.Frame (grid_container, bg="#1a1a1a")
    │   │       ├── 无信号时: tk.Label "等待连接...\n请输入设备 IP 并点击「连接」"
    │   │       │             字体: "DejaVu Sans" 14, 灰色, 居中
    │   │       └── 有信号时: 动态田字格 (行列由 _calculate_grid 计算)
    │   │           ├── tk.Frame (cell_frame, bg="#2a2a2a", highlightborder="#444")
    │   │           │   └── tk.Canvas (bg="black", highlightthickness=0)
    │   │           │       渲染: 视频画面居中 + 顶部 24px 黑色信息条
    │   │           │       信息条: "Pipe N | W×H | FPS NN.N | #NNNNNN" (lime, Consolas 9)
    │   │           ├── tk.Frame ... (通道 2)
    │   │           └── tk.Frame ... (通道 N)
    │   │
    │   └── ttk.LabelFrame "通道信息" (padding=6, width=280, RIGHT, fill=Y)
    │       ├── ttk.LabelFrame "各通道概况" (padding=4)
    │       │   └── tk.Text (overview_text, DISABLED, "Consolas" 9, 浅灰背景)
    │       │       └── 每行: "Pipe N: W×H | FPS NN.N | Frame #NNNNNN"
    │       ├── ttk.LabelFrame "当前帧详情" (padding=4)
    │       │   └── tk.Text (info_text, DISABLED, "Consolas" 10, 浅灰背景)
    │       │       └── 10 行帧信息: 通道/FPS/帧类型/格式/分辨率/步长/帧序号/CHN/数据长度/版本
    │       └── ttk.LabelFrame "日志" (padding=4)
    │           └── tk.Text (log_text, DISABLED, "Consolas" 9, 深色终端风格)
    │               └── ttk.Scrollbar (垂直滚动条)
    │
    └── ttk.Label (status_bar, SUNKEN, anchor=W)
        └── textvariable=self.status_var (初始 "就绪")
```

### 8.2 交互状态机

```
                              ┌──────────────┐
                              │   程序启动     │
                              └──────┬───────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ 状态: "就绪"          │
                          │ 画布: "等待连接..."    │
                          │ 连接按钮: [连接] (启用)│
                          │ 截图按钮: 禁用         │
                          │ FPS: "--"             │
                          └──────────┬──────────┘
                                     │ 用户点击 [连接]
                                     ▼
                          ┌─────────────────────┐
                          │ 连接按钮: [连接中...] │
                          │ (禁用)               │
                          │ 状态: "正在连接 ..."  │
                          │ 后台线程: do_connect()│
                          │   → HBVideoClient()  │
                          │   → client.start()   │
                          │     → TCP connect    │
                          │     → NET_SEND_CFG   │
                          │     → 创建 Recv Thread│
                          └──────────┬──────────┘
                                     │
                      ┌──────────────┴──────────────┐
                      ▼                             ▼
              ┌──────────────┐              ┌──────────────┐
              │  连接成功      │              │  连接失败      │
              └──────┬───────┘              └──────┬───────┘
                     │                             │
                     ▼                             ▼
          ┌─────────────────────┐      ┌─────────────────────┐
          │ 连接按钮: [断开] (启用)│      │ 连接按钮: [连接] (启用)│
          │ 截图按钮: 启用        │      │ 弹窗: 连接失败原因     │
          │ 状态: "已连接 IP:PORT"│      │ 状态: "连接失败"      │
          │ 网格: 自动创建田字格   │      │ 日志: "✗ 连接失败..." │
          │ 日志: "✓ 已连接"      │      └─────────────────────┘
          │ 所有通道同时渲染      │
          └──────────┬──────────┘
                     │ 用户点击 [断开] 或 关闭窗口
                     ▼
          ┌─────────────────────┐
          │ client.stop()        │
          │ → _running = False   │
          │ → join Recv Thread   │
          │ → disconnect()       │
          │ 连接按钮: [连接] (启用)│
          │ 截图按钮: 禁用        │
          │ 状态: "已断开"        │
          │ 网格: 销毁所有单元    │
          │ FPS: "--"            │
          └─────────────────────┘
```

### 8.3 画面渲染管线 (田字格多路模式)

```
接收线程 (Recv Thread):
    _pipe_frames[pipe_id] = (bgr_image.copy(), frame_info)  ← 深拷贝, _frame_lock 保护
    各路 FPS 统计更新

    ═══════════ 线程边界 ═══════════

主线程 (Main Thread, 30ms 定时器):
    _update_display()
        │
        ├── 1. _update_pipe_combo()  ← 动态更新下拉列表
        │
        ├── 2. _frame_lock.acquire()
        │   frames_snapshot = {pid: (frame.copy(), dict(info)) for pid in _pipe_frames}
        │   _frame_lock.release()
        │
        ├── 3. 为每个活跃通道创建/获取网格单元:
        │   for pid in frames_snapshot:
        │       self._get_or_create_cell(pid)  ← 首次出现时创建 Frame + Canvas + 自动排布网格
        │
        ├── 4. 逐个渲染每个通道:
        │   for pid, (frame, info) in frames_snapshot:
        │       self._render_cell(pid, frame, info)
        │           │
        │           ├── 获取 cell = _pipe_cells[pid]
        │           ├── 计算缩放比例:
        │           │   info_h = 24  (顶部信息条高度)
        │           │   scale = min((canvas_w - 4) / w, (canvas_h - info_h - 4) / h)
        │           │   new_w, new_h = int(w * scale), int(h * scale)
        │           │
        │           ├── 色彩空间转换:
        │           │   rgb = frame[..., ::-1]  ← BGR → RGB (NumPy slice, O(1))
        │           │
        │           ├── 转换为 PIL 图像 + 缩放:
        │           │   pil_img = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
        │           │
        │           ├── 转换为 tkinter 可用格式:
        │           │   cell["photo"] = ImageTk.PhotoImage(pil_img)
        │           │
        │           ├── Canvas 绘制:
        │           │   canvas.delete("all")
        │           │   canvas.create_rectangle(0, 0, canvas_w, info_h, fill="black")  ← 顶部信息条背景
        │           │   canvas.create_image(x, y, anchor=NW, image=cell["photo"])       ← 居中绘制视频
        │           │   canvas.create_text(4, 2, text=info_text, anchor=NW, fill="lime", font=("Consolas", 9))
        │           │   ↑ 顶部信息条: "Pipe N | 1920×1080 | FPS 30.0 | #12345"
        │           │
        │           └── 更新标签:
        │               fps_label.config(text="总FPS: NN.N")
        │
        ├── 5. 更新右侧面板:
        │   _update_overview_panel()           ← 各通道概况
        │   _update_info_panel_for_selected()  ← 选中通道或最后活跃通道的详情
        │
        └── 6. root.after(30, _update_display)  ← 下次调度
```

> **关键设计**: 通道下拉框在 v1.3.0 中改为仅控制截图目标 + 右侧详情面板选择，不影响田字格全量显示。所有活跃通道始终同时渲染。网格行列数随通道数自动变化 (1→1×1, 2→1×2, 3~4→2×2, 5~6→2×3, 7~9→3×3)。

---

## 9. 使用说明

### 9.1 环境准备

**Windows 10+**:

```bash
# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "import numpy; import cv2; from PIL import Image; print('OK')"
```

**Ubuntu 22.04+**:

```bash
# 安装 tkinter (GUI 版本需要, 系统级包)
sudo apt update
sudo apt install python3-tk

# 安装 Python 依赖
pip install -r requirements.txt

# 验证安装
python3 -c "import numpy; import cv2; from PIL import Image; import tkinter; print('OK')"
```

**J6B 设备端**:

确保设备端应用程序已集成 `hb_tool_server` 并启动传输。典型方式：

```bash
# 在 J6B 设备上运行 camera_sample (启用 hbplayer 显示传输)
camera_sample -s 1 -S 0

# 或指定端口
camera_sample -s 1 -S 10086
```

关键参数说明：
- `-s 1`: 启用 hbplayer 显示传输 (`vflow_show = 1`)
- `-S <port>`: 指定监听端口，0 表示使用默认端口 10086，非 0 时自动启用 `-s 1`

### 9.2 启动 GUI 版本

```bash
python hb_video_gui.py
```

操作步骤：

1. 在「设备 IP」输入框中填入 J6B 设备的 IP 地址
2. 端口保持默认 `10086`（如设备端使用了自定义端口，相应修改）
3. 点击 **「连接」** 按钮
4. 等待视频画面出现（通常 1-2 秒）
5. 点击 **「截图保存」** 将当前帧保存为 JPG 文件
6. 点击 **「选择保存目录」** 更改截图保存路径
7. 点击 **「断开」** 停止接收

### 9.3 启动命令行版本

```bash
# 仅显示画面
python hb_video_cli.py 192.168.1.100

# 指定端口
python hb_video_cli.py 192.168.1.100 10086

# 显示 + 保存每一帧
python hb_video_cli.py 192.168.1.100 --save

# 仅保存帧，不显示窗口 (适合服务器/无 GUI 环境)
python hb_video_cli.py 192.168.1.100 --no-display --save --save-dir ./captured_frames

# 查看帮助
python hb_video_cli.py --help
```

**键盘控制** (CLI 模式, OpenCV 窗口):

| 按键 | 功能 |
|------|------|
| `q` 或 `ESC` (27) | 退出程序 |
| `s` | 截图保存到 `./snapshots/snap_YYYYMMDD_HHMMSS.jpg` |
| `Ctrl+C` | 终端中断退出 |

### 9.4 作为库使用

```python
from hb_video_client import HBVideoClient
import cv2

def my_callback(frame_info, bgr_image):
    """自定义帧处理 — 在接收线程中调用, 请尽快返回"""
    print(f"收到帧 #{frame_info['frame_id']}: "
          f"{frame_info['width']}×{frame_info['height']} "
          f"({frame_info['type_name']})")

    # 自定义处理: AI 推理、图像分析、录制等
    # 注意: 此函数在接收线程中同步调用, 不要做耗时操作
    # 如需耗时处理, 请将帧放入队列, 由工作线程异步消费

    cv2.imshow("Video", bgr_image)
    cv2.waitKey(1)

# 创建客户端
client = HBVideoClient(
    host="192.168.1.100",
    port=10086,
    enable_yuv=True,
    enable_raw=False,
    pipe_line=0,
    channel_id=0,
)

# 注册回调
client.register_frame_callback(my_callback)

# 启动 (阻塞直到连接成功或失败)
if client.start():
    print("连接成功, 开始接收视频流")

    # 保持主线程运行
    try:
        import time
        while client.is_connected:
            time.sleep(1)
            stats = client.get_stats()
            print(f"已接收 {stats['frame_count']} 帧, "
                  f"错误 {stats['error_count']} 帧")
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()
        print("已停止")
else:
    print("连接失败")
```

### 9.5 高级配置

`HBVideoClient` 构造函数完整参数：

```python
HBVideoClient(
    host="192.168.1.100",  # 设备 IP 地址
    port=10086,            # TCP 端口 (默认 10086)
    enable_yuv=True,       # 启用 YUV 数据接收 (NV12)
    enable_raw=False,      # 启用 RAW 数据接收 (Bayer, 调试用)
    pipe_line=0,           # Pipeline 编号 (0~23)
    channel_id=0,          # 通道编号
)
```

### 9.6 生成 Windows 可执行文件 (exe)

使用 PyInstaller 将 Python 脚本打包为独立 exe（无需安装 Python 即可运行）。

**环境准备**:
```bash
pip install pyinstaller
```

> **注意**: 如果系统同时安装了 Windows Store 版 Python 和官网版 Python，`pyinstaller` 命令可能指向 Store 版环境（缺少 numpy/av 等依赖）。务必使用 `py.exe -m PyInstaller` 确保使用正确的 Python 环境。

**GUI 版本** (无控制台窗口, v1.6.0):
```bash
# 先清理旧构建产物 (重要: 避免缓存导致 --hidden-import 不生效)
rmdir /s /q build dist 2>nul
del *.spec 2>nul

# 重新构建 (必须用 py.exe -m PyInstaller, 不能用裸 pyinstaller)
py.exe -m PyInstaller --onefile --windowed --clean \
  --name J6B_Video_GUI \
  --collect-all numpy \
  --collect-all PIL \
  --collect-binaries av \
  --collect-submodules av \
  --hidden-import av \
  --hidden-import av.codec \
  --hidden-import av.packet \
  --hidden-import av.frame \
  hb_video_gui.py
```

**CLI 版本** (保留控制台):
```bash
py.exe -m PyInstaller --onefile \
  --name J6B_Vide_CLI \
  --collect-all numpy \
  --collect-all PIL \
  --collect-binaries av \
  --collect-submodules av \
  --hidden-import av \
  --hidden-import av.codec \
  --hidden-import av.packet \
  --hidden-import av.frame \
  hb_video_cli.py
```

**关键参数说明**:

| 参数 | 作用 |
|------|------|
| `--onefile` | 打包为单个 exe 文件，方便分发 |
| `--windowed` | GUI 模式隐藏控制台窗口（CLI 版本不加） |
| `--clean` | 清理 PyInstaller 缓存，避免旧构建产物干扰 |
| `--collect-all numpy` | **关键**: 收集 numpy 全部内容（含 `.pyd` C 扩展 + 子模块 + 数据文件）。`--hidden-import numpy` 不够——numpy 有数十个 C 扩展子模块需一并打包 |
| `--collect-all PIL` | 同上，收集 Pillow 全部内容（含图像编解码 C 扩展） |
| `--collect-binaries av` | **关键**: 收集 PyAV 的 FFmpeg 共享库 (`.dll`)，PyInstaller 默认检测不到 |
| `--collect-submodules av` | 收集 `av.codec` / `av.packet` / `av.frame` 等 Cython 子模块 |
| `--hidden-import av*` | 强制声明导入，防止 tree-shaking 误删 |

### 9.7 一键构建脚本

项目提供了两个批处理文件，双击即可生成 exe：

| 脚本 | 目标 | 输出 |
|------|------|------|
| `PyToExe_gui.bat` | GUI 版本 (无控制台窗口) | `dist\J6B_Video_GUI.exe` |
| `PyToExe_cli.bat` | CLI 版本 (保留控制台) | `dist\J6B_Vide_CLI.exe` |

脚本自动完成：清理旧缓存 → PyInstaller 构建 → 显示结果。

### 9.8 PyInstaller 踩坑实录

以下为实际打包过程中遇到的问题和解决方案，供后续参考。

| # | 错误现象 | 根因 | 解决方案 |
|---|---------|------|---------|
| 1 | `ModuleNotFoundError: No module named 'numpy'` | `--hidden-import numpy` 只声明顶层导入，numpy 内部有数十个 `.pyd` C 扩展子模块（`numpy.core`, `numpy.lib`, `numpy.linalg` 等）未被收集 | 改用 `--collect-all numpy`（= `--collect-binaries` + `--collect-submodules` + `--collect-datas`） |
| 2 | 修复后仍报同样错误 | PyInstaller 首次运行生成 `.spec` 文件，后续构建复用缓存的旧 `.spec`，忽略命令行新增的 `--collect-all` 参数 | **每次重新构建前必须删除** `build\`、`dist\`、`*.spec` 三个目录/文件 |
| 3 | `ERROR: Hidden import 'av.codec' not found` | 系统同时安装了 Windows Store 版 Python 和官网版 Python。PATH 中 `pyinstaller` 命令指向 Store 版环境——该环境下 numpy/Pillow/PyAV 都未安装 | 使用 `py.exe -m PyInstaller` 替代裸 `pyinstaller`，确保使用正确的 Python 环境 |
| 4 | 批处理文件执行报 `'xxxx' 不是内部或外部命令` | (a) 文件行尾符为 LF (`\n`) 而非 Windows 要求的 CRLF (`\r\n`)，导致 cmd.exe 无法正确解析；(b) 中文 `!` 字符被错误转义为 `^^^!`（未启用 `enabledelayedexpansion` 时不需要转义）；(c) `>/dev/null` 是 Linux 语法，Windows 应使用 `>nul` | 以 UTF-8 BOM + CRLF 编码保存；`!` 直接使用不转义；`>/dev/null` → `>nul` |
| 5 | 生成的 exe 大小仅 10MB（正常应 ~65MB） | PyInstaller 未正确收集 numpy 和 PyAV 的 DLL 文件（问题 #3 的次生现象） | 修复 #3 后自动解决 |
| 6 | `--onefile` 打包的 exe 启动慢（1-3 秒） | exe 启动时需将内嵌的 PyAV FFmpeg DLL（约 20MB）解压到临时目录 | 可改用 `--onedir` 生成独立文件夹（分发需整个目录），或接受首次启动延迟 |

**构建环境差异对照**：

| 命令 | Python 版本 | 路径 | 包管理 |
|------|------------|------|--------|
| `pyinstaller` (PATH) | 3.13.14 (Win Store) | `C:\Program Files\WindowsApps\...` | 缺少 numpy/av/PIL |
| `py.exe -m PyInstaller` | 3.14 (官网安装) | `C:\Python314\` | 完整依赖 |

> **总结**: 标准构建流程 = `py.exe -m PyInstaller` + `--collect-all numpy/PIL` + `--collect-binaries av` + 删缓存。参照 `PyToExe_gui.bat` 执行即可避免上述所有坑。

---

## 10. 错误处理与异常恢复

### 10.1 错误分类与处理策略

| 错误类型 | 触发位置 | 处理策略 |
|----------|----------|----------|
| TCP 连接超时 (5s) | `connect()` → `socket.timeout` | 返回 `False`，GUI 弹窗提示检查 IP/端口 |
| TCP 连接被拒绝 | `connect()` → `ConnectionRefusedError` | 返回 `False`，提示设备端服务未启动 |
| TCP 连接失败 (其他) | `connect()` → `OSError` | 返回 `False`，显示具体错误信息 |
| 帧头魔数不匹配 | `_recv_loop` → `verify_header()` | 触发 `_sync_to_header()` 自动同步 |
| 帧头解包失败 | `_recv_loop` → `struct.error` | `error_count++`，继续下一帧 |
| 数据体接收不完整 | `_recv_loop` → `_recv_exact()` 返回 `None` | `error_count++`，继续下一帧 |
| NV12→BGR 转换失败 | `_recv_loop` → `_nv12_to_bgr()` 异常 | `error_count++`，记录日志，继续 |
| 帧回调异常 | `_notify_frame()` → 回调抛出异常 | 捕获异常，记录日志，继续通知其他回调 |
| Socket 被动断开 | `_recv_exact()` → `recv()` 返回空 | 返回 `None`，`_recv_loop` 退出 |
| 接收线程退出 | `_recv_loop` 结束 | `_sock` 仍非 `None`，`is_connected` 仍为 `True` * |

> \* **注意**: 当 Socket 被动断开时，`_recv_loop` 退出但 `_sock` 并未被设为 `None`，`is_connected` 属性仍返回 `True`。CLI 模式通过 `client.is_connected` 检测连接状态，此时会检测到连接断开并退出主循环。GUI 模式则依赖用户手动点击「断开」或关闭窗口。建议在扩展开发中监听 `is_connected` 状态变化。

### 10.2 统计监控

通过 `get_stats()` 可获取实时统计信息，用于监控链路质量：

```python
stats = client.get_stats()
# 返回: {'frame_count': 12345, 'error_count': 3}
# 错误率 = error_count / (frame_count + error_count)
```

### 10.3 日志配置

`HBVideoClient` 使用 Python 标准 `logging` 模块，logger 名称为 `"HBVideoClient"`：

```python
import logging

# 查看详细协议日志 (DEBUG 级别)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)

# 仅查看关键信息 (INFO 级别)
logging.basicConfig(level=logging.INFO)

# 仅查看错误 (WARNING 级别)
logging.basicConfig(level=logging.WARNING)
```

---

## 11. 附录

### 11.1 文件清单

| 文件 | 行数 | 类型 | 说明 |
|------|------|------|------|
| `hb_protocol.py` | 343 | 纯协议层 | 常量、枚举 (5 个类)、结构体布局、打包/解包/验证函数 (6 个), `parse_frame_info` 含 `code_type` 字段 |
| `hb_video_client.py` | ~490 | 核心引擎层 | `HBVideoClient` 类: TCP 连接、自动识别 NV12/H.264、双解码器 (`_nv12_to_bgr` + `_decode_h264`)、回调管理 |
| `hb_video_gui.py` | ~570 | GUI 界面层 | `HBVideoGUI` 类: tkinter 窗口、田字格多路同时渲染、PIL 缩放、截图、信息面板 |
| `hb_video_cli.py` | ~265 | CLI 界面层 | `CLIVideoClient` 类: argparse 参数、多路网格显示、OpenCV 显示、帧保存 |
| `requirements.txt` | 4 | 依赖声明 | `numpy`, `opencv-python`, `Pillow`, `av` (PyAV, H.264 解码可选) |
| `tools/viotool/venc_stream/src/venc_stream.c` | ~320 | J6B 设备端 C | CIM4 四路 DDR→VPU H.264→TCP (MediaCodec + libhbplayer) |
| `CLAUDE.md` | — | AI 辅助 | 项目规范、命令、架构速查 |
| `README.md` | — | 简要说明 | 项目简介、快速开始、协议概述 |
| `DESIGN_DOC.md` | — | 架构文档 | 本文档 (v1.4.0) |

### 11.2 项目目录建议

```
J6B_Video_Player/
├── hb_protocol.py              # 协议定义
├── hb_video_client.py          # 核心通信引擎 (支持 NV12 + H.264)
├── hb_video_gui.py             # GUI 界面入口
├── hb_video_cli.py             # 命令行入口
├── requirements.txt            # Python 依赖 (含 PyAV)
├── CLAUDE.md                   # AI 辅助规范
├── README.md                   # 简要说明
├── DESIGN_DOC.md               # 架构设计文档 (本文档)
├── tools/viotool/
│   ├── libhbplayer/            # J6B TCP Server 库 (hb_tool_server 源码)
│   └── venc_stream/            # [新增] J6B H.264 编码+流式输出工具
│       ├── src/venc_stream.c   #   主程序
│       ├── src/Makefile        #   交叉编译
│       ├── bin/run.sh          #   一键启动脚本
│       └── README.md           #   编译部署说明
├── ref_docs/
│   ├── document/               # J6B SDK 手册 (HTML)
│   ├── S83E04_Module/          # J6B Sample 源码 (camera/ codec/ vio)
│   └── tools/                  # J6B 工具参考 (libhbplayer, tuning_tool)
├── snapshots/                  # 截图保存目录 (自动创建)
├── frames/                     # 帧保存目录 (CLI --save 自动创建)
└── .gitignore                  # 建议添加
```

```gitignore
# Python 字节码缓存
__pycache__/
*.pyc
*.pyo

# 运行时生成目录
snapshots/
frames/
captured_frames/

# 虚拟环境
venv/
.venv/

# IDE
.vscode/
.idea/

# 空目录占位
Camera_player/
```

> `__pycache__/` 是 Python 解释器自动生成的字节码缓存目录，用于加速后续模块导入，不应纳入版本管理。
> `Camera_player/` 是工作区中预先存在的空目录，与本项目无关。

### 11.4 协议参考源文件清单

| 源文件 | 相对路径 (基于 SDK 根目录) |
|--------|---------------------------|
| `hb_tool_server.h` | `codebase/tools/viotool/libhbplayer/include/hb_tool_server.h` |
| `hb_tool_server.c` | `codebase/tools/viotool/libhbplayer/src/server/src/hb_tool_server.c` |
| `camera_sample.c` | `codebase/test/samples/platform_samples/source/S83_Sample/S83E04_Module/camera_sample/src/camera_sample.c` |
| `socket_manager.c` | `codebase/tools/viotool/libhbplayer/src/server/src/socket/socket_manager.c` |
| `socket_manager.h` | `codebase/tools/viotool/libhbplayer/src/server/inc/socket/socket_manager.h` |
| `server_cmd.h` | `codebase/tools/viotool/libhbplayer/src/server/inc/common/server_cmd.h` |

### 11.5 常见问题排查

**Q: 连接失败，提示 "Connection refused"**

- 确认 J6B 设备端已运行 `camera_sample -s 1` 或等效程序
- 确认 PC 与设备在同一网络，可 ping 通
- 确认防火墙未阻止端口 10086
- 确认设备端 `hb_tool_server` 版本为 `TOOL_VERSION=2` (J6)

**Q: 连接成功但无画面**

- 检查 `NET_SEND_CFG` 包中 `tcp_open` 和 `yuv_enable` 是否均为 1
- 查看日志中是否有帧头魔数错误 (启用 DEBUG 级别日志)
- 确认设备端摄像头已正确初始化并开始采集

**Q: 画面花屏或颜色异常**

- 检查 stride 是否等于 width（stride > width 时需要裁剪，代码已处理）
- 确认 NV12 格式正确（Y 平面在前，UV 交错平面在后）
- 如果是 RAW 数据，需要使用不同的解码路径（`enable_raw=True`）
- 检查色彩是否偏绿/偏紫 → 可能是 UV 平面顺序错误

**Q: FPS 很低 / 画面卡顿**

- (H.264 模式) 确认使用 v1.6.0+ 代码: 早期版本 `av.Packet(data)` 直送导致 AVERROR_INVALIDDATA, 大量帧跳过解码
- (H.264 模式) 确认 PyAV 已安装: `pip install av`
- 检查网络带宽: NV12 原始流带宽极高 (~356 MB/s 4路), 建议使用 H.264 模式
- (v1.6.0) 当前解码速率约 100fps (4路各 25fps), 匹配 J6B 实际输出, 硬件要求低 (i3/Ryzen 3 级别足够)
- 检查是否在帧回调中执行了耗时操作

**Q: Ubuntu 上 GUI 无法启动**

- 确认已安装 `python3-tk`: `sudo apt install python3-tk`
- 确认 Python 版本 ≥ 3.10: `python3 --version`
- 确认 Pillow 已安装: `python3 -c "from PIL import Image"`

### 11.6 扩展开发建议

1. **支持 H.264/H.265 解码**: ✅ **已实现 (v1.4.0, v1.6.0 完善)**。每路独立解码线程 + `decoder.parse()` NAL 单元解析 + FFmpeg auto 多线程。详见 [第 12 节](#12-h264-编解码链路)。
2. **多路视频同时显示**: ✅ 已实现。田字格自动布局，所有活跃通道通过同一 TCP 连接交错接收后同时渲染，每路视频顶部叠加信息条。
3. **录制功能**: 在帧回调中使用 `cv2.VideoWriter` 保存为 MP4 文件
4. **AI 推理集成**: 在帧回调中将帧放入队列，由独立工作线程调用 ONNX Runtime / OpenCV DNN 进行目标检测
5. **Web 远程监控**: 将 `HBVideoClient` 封装为 FastAPI 服务，通过 WebSocket 或 MJPEG 流推送到浏览器
6. **RAW 数据支持**: 实现 Bayer→RGB 去马赛克算法，支持 `RAW_DATA` 类型的可视化
7. **ISP 调试面板**: 解析 `STATS_AWB_DATA`、`STATS_AEfull_DATA` 等 ISP 统计数据类型，在 GUI 中展示调试信息
8. **J6B 设备端 H.264 压缩**: ✅ **已实现 (v1.4.0)**。`tools/viotool/venc_stream/` 实现 CIM4 四路 VPU 硬件编码 + TCP 输出, 带宽降低 95%+。详见 [第 13 节](#13-设备端-venc_stream-工具)。
---

## 12. H.264 编解码链路 (v1.4.0 新增)

### 12.1 概览

v1.4.0 在 PC 端 `hb_video_client.py` 新增 H.264 解码能力，与 J6B 设备端 `venc_stream` 工具（见第 13 节）配合使用，形成完整的 H.264 编解码链路。

### 12.2 数据流对比

```
【NV12 路径 (camera_sample)】
J6B: CIM → DDR → hb_tool_send_yuv_pic → TCP (NV12 原始像素)
PC:  _recv_loop → YUV_DATA(1) → _nv12_to_bgr() numpy → BGR
带宽: 1696×1168×1.5×30fps×4路 ≈ 356 MB/s (远超千兆网)

【H.264 路径 (venc_stream)】
J6B: CIM → DDR → VPU Encoder → hb_tool_send_video_pic → TCP (H.264 码流)
PC:  _recv_loop → VIDEO_DATA(3) → _decode_h264() PyAV → BGR
带宽: 4 Mbps × 4 路 = 16 Mbps (千兆网充裕)
```

### 12.3 PC 端解码实现

**自动类型识别** (`_decode_one_frame` in `_pipe_decode_loop`):

```python
if data_type == DataType.VIDEO_DATA:
    bgr_image = self._decode_h264(body_data, pipe_id, frame_info)
    if bgr_image is None:
        continue  # 解码器缓冲中, 等待更多数据
else:
    bgr_image = self._nv12_to_bgr(body_data,
        frame_info['width'], frame_info['height'], frame_info['stride'])
```

**PyAV 解码器管理** (`_get_h264_decoder` / `_decode_h264`, v1.6.0 修正):

- 每个 `pipe_id` 维护独立的 `av.CodecContext` 实例 (在专属解码线程中运行)
- `decoder.parse(data)` 将 Annex B 字节流拆分为 NAL 单元对齐的 Packet 列表 (内部 `av_parser_parse2()`)
- `decoder.decode(packet)` 逐 packet 输出 VideoFrame → `to_ndarray(format='bgr24')`
- 解码器配置: `thread_count=0` (FFmpeg auto 多线程), `flags|=4` (AV_CODEC_FLAG_OUTPUT_CORRUPT)
- **重要**: 不能使用 `av.Packet(data)` 直送解码器 — 当解码器尚无 SPS/PPS 上下文时, `avcodec_send_packet()` 对所有帧 (包括后续含 SPS/PPS 的 IDR 帧) 一律返回 AVERROR_INVALIDDATA, 导致解码器永久无法初始化

**依赖**:

```bash
pip install av  # PyAV, 仅连接 venc_stream 时需要
```

NV12 流 (camera_sample) 不需要 PyAV，纯 numpy 即可工作。

### 12.4 带宽对比

| 场景 | 分辨率 | 格式 | 带宽 (4路 @30fps) | 千兆网可行性 |
|------|--------|------|-------------------|-------------|
| camera_sample | 1696×1168 | NV12 原始 | ~356 MB/s | ❌ 超带宽 |
| venc_stream | 1696×1168 | H.264 4Mbps | ~16 Mbps | ✅ 仅占 1.6% |
| venc_stream | 1920×1080 | H.264 4Mbps | ~16 Mbps | ✅ |

### 12.5 帧头新增字段

`parse_frame_info` 返回值新增 `code_type` 字段:

| 字段 | 帧头偏移 | 说明 |
|------|---------|------|
| `code_type` | 48 (IDX_CODE_TYPE) | 编码类型: 0=H264, 1=H265, 2=PPS |

---

## 13. 设备端 venc_stream 工具 (v1.4.0 新增)

### 13.1 功能概述

`tools/viotool/venc_stream/` 是 J6B 设备端新增的 C 程序，实现以下功能:

1. **CIM4 四路 DDR 视频采集** — 复用 camera_sample 的 VIO JSON 配置
2. **VPU 硬件 H.264 编码** — 4 个 MediaCodec encoder 实例并发
3. **TCP 码流输出** — 通过 `hb_tool_send_video_pic()` 发送到 PC 端

### 13.2 文件结构

```
tools/viotool/venc_stream/
├── README.md              # 编译、部署、运行说明
├── bin/
│   └── run.sh             # J6B 设备端一键启动脚本 (3 行)
└── src/
    ├── venc_stream.c      # 主程序 (~320 行)
    └── Makefile           # SDK 交叉编译配置
```

### 13.3 数据流

```
Camera ×4 (MIPI RX4)
    │
    ▼
CIM4 (4×IPI, ddr_enable=1, cim_isp_flyby=0)   ← 不经过 ISP/PYM
    │  hb_cam_get_data(pipe_id, HB_CAM_YUV_DATA)
    ▼
DDR ion buffer (零拷贝)
    │  hb_mm_mc_dequeue_input_buffer + phys_addr 填入
    ▼
VPU Encoder ×4 (MediaCodec, poll 模式)
    │  hb_mm_mc_dequeue_output_buffer
    ▼
H.264 AnnexB 码流
    │  hb_tool_send_video_pic(g_ev, &pic_info, ptr, size)
    ▼
TCP port 10086 → PC 端 hb_video_client
```

### 13.4 核心代码结构

```c
main():
  ├── hb_vio_init(vpm_cfg)            // 复用 camera_sample 的 VIO JSON
  ├── hb_cam_init(cam_cfg)            // 复用 camera_sample 的 Camera JSON
  ├── for i=0..3: hb_vio_start_pipeline(i)
  ├── g_tool_ev = hb_tool_start_transfer(10086)  // TCP Server
  │
  ├── for i=0..3:
  │     init_encoder(&g_ch[i])         // H.264 CBR 4Mbps, GOP I-P-P-P…
  │     pthread_create → feed_thread   // hb_cam_get_data → queue input
  │     pthread_create → output_thread // select poll_fd → send TCP
  │
  └── while(!quit): sleep(5); print_stats()
```

### 13.5 编码参数（实测生效）

| 参数 | 值 | 说明 |
|------|-----|------|
| 传感器 | SC361AT ×4 | GAC_BYPASS bypass 模式 |
| Pipeline ID | 7, 8, 9, 10 | vpm_config.json pipeline7-10 |
| CAM Port | 7, 8, 9, 10 | hb_j6dev.json port_7-10 |
| 分辨率 | 1696×1168 | extra_mode=10 有效像素 |
| 帧率 | 30fps | 4 路合计 ~120fps |
| 编码格式 | H.264 CBR | `MC_AV_RC_MODE_H264CBR` |
| 码率 | 4000 kbps/路 | 总带宽 ~16 Mbps (100M 占 ~20%) |
| GOP | I-P-P-P… | `gop_preset_idx = 9`, `decoding_refresh_type = 2` |
| 输入格式 | NV12 | CIM DDR 输出已为 NV12 (hb_mipi sc361at_nv12) |
| Buffer 模式 | internal | `external_frame_buf = 0`, memcpy 逐行拷贝 (处理 stride 对齐) |
| VBV 缓冲 | 300ms | 低延迟配置 (I帧~120KB, VBV~150KB 安全) |
| 帧缓冲数 | 3 | `frame_buf_count = bitstream_buf_count = 3` |
| TCP 端口 | 10086 | `hb_tool_start_transfer(DEFAULT_PORT)` |
| 配置文件 | `case_matrix/GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4` | |
| 编译器 | QNX `qcc -Vgcc_ntoaarch64le` | aarch64-unknown-nto-qnx8.0.0-gcc |

### 13.6 编译与部署

```bash
# 1. 在 SDK 开发机上，先执行完整构建 (产生所需 .so)
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
docker run -it --rm -v $(pwd):$(pwd) -w $(pwd) \
    docker.hobot.cc/systemsoft/devenv/debian-12:latest /bin/bash
# 容器内:
source build_tools/Compiler/qnx800/qnxsdp-env.sh
source envsetup.sh
bdall BAIC

# 2. bdall 完成后，在 host 环境编译 venc_stream (需先 source qnxsdp-env.sh + envsetup.sh)
cd tools/viotool/venc_stream/src
make clean && make && cp venc_stream ../bin/

# 3. 部署到 J6B
scp bin/venc_stream bin/run.sh root@192.168.0.140:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
```

### 13.7 运行

```bash
# J6B 设备端（需先 kill camera_sample 释放 VIO 资源）
killall camera_sample
cd /app/sample/S83_Sample/S83E04_Module/venc_stream/bin
./run.sh

# PC 端（等 J6B TCP server ready 后再连接）
python3 hb_video_gui.py
```

### 13.8 注意事项

1. **与 camera_sample 互斥**: venc_stream 独立初始化 VIO/Cam, 不能与 camera_sample 同时运行。
2. **先 PC 连接再启动编码器**: 编码器产帧后立即 TCP 发送, PC 未连时可能丢帧(不影响后续)。
3. **debug 开关**: `VENC_DEBUG 0/1` 宏控制 stderr 调试日志(首帧 stride 对比, 每 100 帧计数, STAT 各路详情)。
4. **切换传感器配置**: 修改 `PIPE_IDS[]` / `CAM_PORTS[]` / `run.sh` 的 `CFG_BASE` 路径即可适配不同配置。
5. **低延迟参数**: `vbv_buffer_size=300ms` + `frame_buf_count=3` 为核心低延迟配置; 若画面花屏, 改回 500/5。
6. **PC 低延迟解码**: `av.Packet(data)` 直送(非 `decoder.parse`), 消除 PyAV 缓冲累积; `thread_count=1` 单线程。

---

## 14. 问题排查实录 (v1.5.0 调试过程)

> **参考对话**: "J6B H.264 视频流输出" (2026-07-25), 约 120 轮交互。
> **涉及的库/头文件**: `hb_media_codec.h`, `hb_vpm_data_info.h`, `hb_tool_server.h`, `hb_vio_interface.h`, `hb_media_error.h`
> **参考代码**: `camera_sample.c`, `codec_sample/sample.c`, `codec_sample/sample_venc.c`, `codec_sample/sample_common.c`

### 14.1 问题总览

| # | 阶段 | 错误现象 | 根因 | 修复 |
|---|------|---------|------|------|
| 1 | 编译 | `has no member named 'h264_cbr'` | 字段名错误: SDK头文件中联合体成员为 `h264_cbr_params` (完整后缀) | `h264_cbr` → `h264_cbr_params` |
| 2 | 编译 | 链接时 `libepoll.so.1 not found` 等 QNX 系统库缺失 | 使用了 Linux `aarch64-none-linux-gnu-gcc` 而非 QNX 编译器 | 切换为 QNX `qcc -Vgcc_ntoaarch64le` |
| 3 | 编译 | `cannot find -lpthread, -ldl` | QNX 的 pthread/dl 功能已合并进 libc, 无需独立链接 | 删除 `-lpthread -ldl` |
| 4 | 编译 | `cc: unknown option: '-w1'` | QNX qcc 底层 gcc 不认识该选项 | `-w1` → `-Wall` |
| 5 | 运行 | `hb_mm_mc_configure fail(0xF0000009)` INVALID_PARAMS | 码率值 `4*1024*1024` 被注入 `bit_rate` 字段(单位 kbps), 实际值 4G kbps 超限 | `ENC_BITRATE` → `4000` (kbps) |
| 6 | 运行 | 同上 INVALID_PARAMS | `decoding_refresh_type=2` 仅 H265 有效, H264 需清零 | 删除该字段(H264 使用默认值) |
| 7 | 运行 | 同上 INVALID_PARAMS | `vbv_buffer_size=0` (memset后未赋值), 不在有效范围 [10,3000] | 先 `hb_mm_mc_get_rate_control_config` 取FW默认值, 再覆盖全部 17 个码率控制字段 |
| 8 | 运行 | 编码器初始化OK, 输出 1-2 帧后 `HB_MEDIA_ERR_UNKNOWN` | `external_frame_buf=1` 零拷贝模式给编码器填了 NV12 buffer, 但 CIM DDR 实际输出 YUV422→编码器按 NV12 读导致数据错位 | 改为 `external_frame_buf=0` + memcpy NV12 数据到编码器内部 buffer |
| 9 | 运行 | 同上 UNKNOWN | 连续 memcpy 未处理 stride 对齐差异 (CIM stride=1696 vs Encoder stride 可能对齐到 32/64) | 逐行 memcpy, 每行只拷贝 `width` 字节, 跳过 padding |
| 10 | 延迟 | PC 端播放有数秒延迟 | ~~PyAV `decoder.parse()` 内部流式缓冲~~ **(v1.6.0 修正: 此结论有误, 真正原因是 #14)** | ~~`decoder.parse()` → `av.Packet(data)` 直送~~ |
| 11 | 延迟 | 编码器端 ~3 秒缓冲 | `vbv_buffer_size=3000ms` 预留大缓冲平滑码率 | 逐步压缩至 300ms (`vfv=300ms, I帧 120KB 安全`) |
| 12 | PC | GUI 显示「芯片版本: J2」(应为 J6B) | `TOOL_VERSION=2` 直接拼接到 `J{chip_ver}` | 新增 `CHIP_NAMES` 映射字典 |
| 13 | PC | `SyntaxError: f-string expr不能包含反斜杠` | Python 3.11-: f-string 内不能有 `\"` | 提取 chip_name 为独立变量 |
| 14 | PC | `AVERROR_INVALIDDATA` 满屏错误, 所有帧解码失败 (v1.6.0 发现) | `av.Packet(data)` 直送 → `avcodec_send_packet()` 在解码器无 SPS/PPS 上下文时拒绝所有帧, 含后续 SPS/PPS 的 IDR 帧也被拒绝 → 解码器永久无法初始化 | 回归 `decoder.parse(data)` → NAL 单元逐个 `decoder.decode(packet)`, SPS/PPS 能正确初始化解码器 |
| 15 | PC | 显示帧率仅 ~2fps (v1.6.0 发现) | 排空机制每周期解码 N 帧但只推送最后 1 帧到回调 | 移除排空, 逐帧解码推送, 解码速率匹配输入速率 (TCP 背压自然限流) |
| 16 | PC | 带宽显示 ~1.4Mbps, 实际 ~13Mbps (v1.6.0 发现) | 带宽计数器在回调中, 排空丢弃的帧不计数 | 移至 `_read_one_frame()` 数据读取点, 统计所有帧 |
| 17 | PC | disconnect 时 `NoneType` crash (v1.6.0 发现) | 线程竞态: `_sock=None` 后接收线程仍访问 | 加 `_running` 和 `_sock is not None` 检查 |

### 14.2 关键发现: 延迟瓶颈根因修正 (v1.6.0)

> **v1.5.0 的结论 (14.2) 有误**。当时的分析认为延迟来自 `decoder.parse()` 的流式缓冲, 因此改用 `av.Packet(data)` 直送。但 v1.6.0 调试发现 `av.Packet(data)` 直送会导致更严重的问题 — 解码器在无 SPS/PPS 上下文时对所有帧永久返回 AVERROR_INVALIDDATA。

**v1.6.0 正确根因**:
- 真正导致画面延迟的是两个叠加 bug:
  1. `av.Packet(data)` 直送 → AVERROR_INVALIDDATA → 解码器无法初始化
  2. 排空机制过度丢弃帧 → 显示帧率从 25fps 降至 2fps (画面卡顿被感知为"延时")
- `decoder.parse(data)` 本身 **不会** 导致渐进式延迟 — v1.5.0 观察到的数秒延迟是 AVERROR_INVALIDDATA 导致大多数帧解码失败, 只能等 IDR 帧侥幸通过

**最终方案 (v1.6.0)**:
- `decoder.parse(data)` → 逐个 NAL 单元 `decoder.decode(packet)` — SPS/PPS 正确初始化解码器
- 移除排空机制 — 解码速率 (100fps) 匹配输入速率 (100fps), TCP 背压自然限流
- 10 小时压力测试: 解码速率恒定 100fps, 零错误, 无延迟累积

### 14.3 PC 端数据流 (v1.6.0 并行解码版)

```
TCP recv(80B 帧头 + H.264 码流)
  → _read_one_frame()                   // 仅读取不解码, 统计 total_bytes
  → queue.Queue(maxsize=2).put()        // 分发到对应 pipe 的解码线程
  → (解码线程) decoder.parse(data)      // av_parser_parse2 拆分 NAL 单元
  → (解码线程) decoder.decode(packet)   // FFmpeg 软件解码 (thread_count=auto)
  → (解码线程) frame.to_ndarray(bgr24)  // ①唯一的图像拷贝 (PyAV 内部 buffer 复用)
  → (解码线程) _notify_frame()          // 线程安全回调 (_callbacks_lock)
  → self._pipe_frames[pipe_id] = (...)  // 引用传递, 覆盖旧帧 (受 _frame_lock 保护)
  → _update_display() (主线程 30ms)     // 取引用 (不加锁拷贝)
  → BGR[::-1] view → PIL → ImageTk     // ②渲染拷贝
```

### 14.4 长时稳定性保障 (v1.6.0 更新)

| 层面 | 措施 |
|------|------|
| 内存 | `_on_frame_received` 只保留最新帧(覆盖旧帧, GC自动回收), `_update_display` 零拷贝引用传递 |
| 解码 | 每路独立 `av.CodecContext` + 独立线程, 单路异常不影响其他; `except→continue`, 下帧自动恢复; Queue maxsize=2 提供背压防止内存膨胀 |
| TCP | `_sync_to_header` 魔数扫描+滑动窗口, 断流自动重同步; `settimeout(1.0)` 防止阻塞; disconnect 检查 `_running` 和 `_sock is not None` 防止竞态崩溃 |
| 编码器 | `VENC_DEBUG` 宏开关, 各路 feed/output/error 独立计数, STAT 每 5 秒汇报 |
| 线程安全 | `_callbacks_lock` 保护回调列表; `_lock` 保护 `frame_count/error_count/total_bytes`; `_frame_lock` (GUI 侧) 保护 `_pipe_frames` |

### 14.5 v1.6.0 性能验证

| 测试 | 时长 | 解码速率 | 每路帧率 | 错误 | 结论 |
|------|------|---------|---------|------|------|
| 稳定性测试 | 60s | 100.0 fps | 24.8 fps ×4 | 0 | 帧率无衰减 |
| 压力测试 | 5min | 100.0 fps | 25.0 fps ×4 | 0 | 每30s采样均恒定 |
| 长期验证 | 10h | 100.0 fps | 25.0 fps ×4 | 0 | 视频保持同步 |

CPU 占用: i9-13900H 仅用 ~6% (1.2 核/20 核), 任何入门级 CPU 均可满足。内存: <100 MB。
