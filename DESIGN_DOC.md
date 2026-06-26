# J6B Video Player — 架构设计文档与使用说明

> **版本**: 1.1.0  
> **日期**: 2025-06-26  
> **适用平台**: Windows 10+ / Ubuntu 22.04+  
> **目标设备**: J6B (Horizon Robotics J6 芯片平台)  
> **协议参考**: `hb_tool_server.h` / `hb_tool_server.c` / `camera_sample.c` / `socket_manager.c` / `server_cmd.h`

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
| 实时 GUI 显示 | 基于 tkinter + Pillow 的图形界面，支持画面缩放、FPS 叠加 |
| 命令行模式 | 基于 OpenCV HighGUI 的命令行客户端，支持 `--no-display` 无头模式 |
| NV12→BGR 转换 | 纯 numpy 向量化实现 ITU-R BT.601 标准的色彩空间转换，无需 OpenCV `cvtColor` |
| 帧同步 | 魔数搜索自动对齐帧边界，支持中途连接和断线恢复 |
| 截图保存 | GUI 和 CLI 均支持 JPG 格式截图，可自定义保存目录 |
| 帧信息面板 | 实时显示帧类型、分辨率、帧序号、PIPE/CHN ID、数据长度等元数据 |
| FPS 统计 | 1 秒滑动窗口实时帧率统计，在视频画布和标签栏双重显示 |
| 连接状态管理 | 异步连接/断开，GUI 状态栏和日志面板双重反馈 |
| 跨平台支持 | Windows 10+ 和 Ubuntu 22.04+ 均可运行，字体自动适配 |

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
> 设备端还实现了负载均衡机制（`check_send_enable` → `send_data_load_balance`），在多个数据通道之间按优先级和输出计数动态调度，防止单个通道独占 TCP 发送缓冲区。

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
| 1 | `YUV_DATA` | 设备→PC | YUV 数据（**本工具主要处理**） |
| 2 | `JPEG_DATA` | 设备→PC | JPEG 压缩数据 |
| 3 | `VIDEO_DATA` | 设备→PC | H.264/H.265 编码视频 |
| 13 | `NET_SEND_CFG` | PC→设备 | **传输配置握手命令** |

其余类型（`STATS_AWB_DATA`、`STATS_AEfull_DATA`、`ISP_INFO_DATA`、`ACT_CTL_DATA` 等）用于 ISP 调试和寄存器控制，本工具在接收循环中自动跳过（`_recv_loop` 中 `if data_type not in (DataType.YUV_DATA, DataType.RAW_DATA):` 分支）。

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

### 4.2 `hb_video_client.py` — 网络通信与解码层（440 行）

**职责**: TCP 连接管理、帧接收、NV12→BGR 转换、帧回调通知。这是整个项目的核心引擎。

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
| `_recv_loop()` | `() → None` | 接收线程主循环: 读头(80B)→验证魔数→读体(len)→NV12→BGR→通知回调 |
| `_recv_exact(size)` | `(int) → bytes \| None` | 精确接收指定字节数，超时或断开返回 `None` |
| `_sync_to_header(partial_data)` | `(bytes) → bool` | 魔数搜索帧同步，最多扫描 1MB |
| `_nv12_to_bgr(data, w, h, stride)` | `(bytes, int, int, int) → np.ndarray` | **静态方法**: NV12→BGR 色彩转换 |
| `_notify_frame(info, img)` | `(dict, np.ndarray) → None` | 遍历回调列表，逐个调用，异常不中断 |

**`_recv_loop` 接收循环详细流程**:

```
while self._running:
    ┌─ 1. _recv_exact(80) → header_data
    │     失败 → 检查 _running, 继续或退出
    │
    ├─ 2. unpack_cmd_header(header_data) → header_fields (20 个 uint32)
    │     失败 → error_count++, continue
    │
    ├─ 3. verify_header(header_fields) → bool
    │     失败 → _sync_to_header(header_data) → 成功则 continue, 失败则 error_count++
    │
    ├─ 4. 检查 data_type ∈ {YUV_DATA, RAW_DATA}
    │     否 → _recv_exact(data_len) 丢弃, continue
    │
    ├─ 5. data_len == 0 → continue
    │
    ├─ 6. _recv_exact(data_len) → body_data
    │     失败 → error_count++, continue
    │
    ├─ 7. parse_frame_info(header_fields) → frame_info
    │
    ├─ 8. _nv12_to_bgr(body_data, width, height, stride) → bgr_image
    │     失败 → error_count++, continue
    │
    ├─ 9. _lock: frame_count++
    │
    └─ 10. _notify_frame(frame_info, bgr_image)
```

### 4.3 `hb_video_gui.py` — GUI 界面层（461 行）

**职责**: 提供 tkinter 图形界面，包含连接管理、视频渲染、信息显示、截图功能。**仅依赖 Pillow (PIL) 进行图像处理，不依赖 OpenCV**。

**核心类**: `HBVideoGUI`

**内部状态**:

| 属性 | 类型 | 说明 |
|------|------|------|
| `client` | `HBVideoClient \| None` | 客户端实例 |
| `_current_frame` | `np.ndarray \| None` | 当前帧 BGR 图像 (接收线程写入, GUI 线程读取, 有锁保护) |
| `_current_info` | `dict \| None` | 当前帧信息字典 |
| `_frame_lock` | `threading.Lock` | 帧缓冲区互斥锁 |
| `_fps_value` | `float` | 平滑后的 FPS 值 |
| `_snapshot_count` | `int` | 截图计数 (用于文件命名) |
| `_snapshot_dir` | `str` | 截图保存目录 (默认 `./snapshots`) |

**关键方法**:

| 方法 | 说明 |
|------|------|
| `_build_ui()` | 构建完整 UI 布局 (控制面板 → 视频画布 + 信息面板 → 状态栏) |
| `_build_control_panel(parent)` | 控制面板: IP 输入框、端口输入框、连接按钮、截图按钮、目录选择、FPS 标签 |
| `_build_video_panel(parent)` | 视频画布: 黑色背景 Canvas，显示 "等待连接..." 占位文字 |
| `_build_info_panel(parent)` | 信息面板: 帧信息 Text (浅色背景) + 日志 Text (深色终端风格) + 滚动条 |
| `_build_status_bar(parent)` | 状态栏: 显示当前状态文字 |
| `_toggle_connection()` | 连接/断开切换入口 |
| `_connect()` | 在后台线程中创建 `HBVideoClient` 并调用 `start()`，通过 `root.after()` 切回主线程 |
| `_on_connected(host, port)` | 连接成功回调: 更新按钮状态、启用截图、清除占位文字 |
| `_on_connect_failed()` | 连接失败回调: 恢复按钮状态、弹窗提示 |
| `_disconnect()` | 停止客户端、更新按钮状态、禁用截图、清除画面 |
| `_on_frame_received(info, img)` | **帧回调 (接收线程)**: 深拷贝帧到 `_current_frame`/`_current_info`，累计 FPS |
| `_update_display()` | **30ms 定时器 (主线程)**: 从共享缓冲区取帧，调用 `_render_frame()` |
| `_render_frame(img, info)` | **渲染管线**: BGR→RGB→PIL.Image→`resize(LANCZOS)`→`ImageTk.PhotoImage`→Canvas 居中显示 + FPS 叠加 |
| `_update_info_panel(info)` | 更新帧信息 Text 组件 (9 行信息) |
| `_save_snapshot()` | 当前帧保存为 JPG (通过 PIL)，命名格式 `snapshot_YYYYMMDD_HHMMSS_序号.jpg` |
| `_select_snapshot_dir()` | 打开目录选择对话框 |
| `_log(message)` | 日志面板追加带时间戳的消息 |
| `_on_close()` | 窗口关闭处理: 连接中则弹窗确认 |

**字体适配**: 代码使用 `"DejaVu Sans"`（Ubuntu 默认安装）和 `"Consolas"`（跨平台等宽字体），在 Windows 和 Linux 上均可正常显示。

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

### 5.1 线程架构 (GUI 模式)

```
┌─────────────────────────────────────────────────────────────────────┐
│                           线程模型 (GUI 模式)                        │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Main Thread (主线程 / GUI 线程)                               │   │
│  │  - tkinter 事件循环 (root.mainloop)                            │   │
│  │  - 30ms 定时器 _update_display()                              │   │
│  │  - 从 _current_frame / _current_info 读取 (_frame_lock 保护)   │   │
│  │  - BGR→RGB→PIL.Image→ImageTk.PhotoImage→Canvas 渲染           │   │
│  │  - 所有 tkinter 组件更新必须在此线程执行                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 帧回调 _on_frame_received()            │
│                              │ (在接收线程中调用, 快速深拷贝后返回)     │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Recv Thread (接收线程, daemon=True)                           │   │
│  │  - _recv_loop() 循环                                          │   │
│  │  - socket.recv() → unpack_cmd_header → verify_header          │   │
│  │  - _recv_exact(data_len) → _nv12_to_bgr → parse_frame_info    │   │
│  │  - _frame_lock: _current_frame = bgr_image.copy() (深拷贝)     │   │
│  │  - 调用所有已注册的帧回调 (_notify_frame)                       │   │
│  │  - 线程名: "HB-Recv"                                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Connect Thread (临时线程, 连接时创建, daemon=True)             │   │
│  │  - 创建 HBVideoClient 实例                                     │   │
│  │  - 注册帧回调 _on_frame_received                               │   │
│  │  - 调用 client.start() → connect() + 创建 Recv Thread          │   │
│  │  - 完成后通过 root.after(0, callback) 切回主线程                 │   │
│  │  - 线程生命周期: 连接成功/失败后自动结束                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 线程架构 (CLI 模式)

```
┌─────────────────────────────────────────────────────────────────────┐
│                           线程模型 (CLI 模式)                        │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Main Thread (主线程)                                          │   │
│  │  - 创建 CLIVideoClient 实例                                    │   │
│  │  - 调用 client.start() → connect() + 创建 Recv Thread          │   │
│  │  - while self.running: time.sleep(0.1) + 检查 is_connected    │   │
│  │  - SIGINT 信号处理 (Ctrl+C)                                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 帧回调 on_frame()                      │
│                              │ (在接收线程中调用)                      │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Recv Thread (接收线程, daemon=True)                           │   │
│  │  - 同 GUI 模式的 Recv Thread                                   │   │
│  │  - 帧回调: 打印统计 + cv2.imwrite (可选) + cv2.imshow (可选)    │   │
│  │  - cv2.waitKey(1) 返回的按键用于控制退出/截图                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.3 帧数据流 (完整管道)

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
检查 data_type ∈ {YUV_DATA(1), RAW_DATA(0)}
    │
    ├── 否 → _recv_exact(data_len) 丢弃数据体, continue
    │
    ▼ 是
data_len == 0 ?
    │
    ├── 是 → continue (空帧)
    │
    ▼ 否
_recv_exact(data_len) ───── 数据体 (NV12 原始字节)
    │
    ▼
parse_frame_info() ───────── 提取 frame_info 字典
    │
    ▼
_nv12_to_bgr() ───────────── Y/UV 分离 → stride 裁剪 → 上采样 → YUV→RGB (BT.601)
    │                         返回: np.ndarray (height, width, 3), dtype=uint8, BGR 顺序
    ▼
frame_info + bgr_image
    │
    ├──▶ 更新统计: _lock → frame_count++
    │
    ├──▶ _notify_frame() → 遍历回调列表
    │         │
    │         ├──▶ GUI 回调: _on_frame_received()
    │         │         _frame_lock → _current_frame = copy() + _current_info = info
    │         │
    │         └──▶ CLI 回调: on_frame()
    │                   FPS 统计 → 终端打印 → cv2.imwrite (可选) → cv2.imshow (可选)
    │
    ▼
下一帧 (回到 _recv_exact(80))
```

### 5.4 线程安全策略

| 保护对象 | 锁 | 策略 |
|----------|------|------|
| `_current_frame` / `_current_info` | `_frame_lock` (GUI) | 接收线程写入时深拷贝 (`np.copy()`)，GUI 线程读取时再次深拷贝，双重隔离 |
| `frame_count` / `error_count` | `_lock` (HBVideoClient) | 统计计数器，仅在 `_recv_loop` 和 `get_stats` 中访问 |
| `_frame_callbacks` 列表 | 无锁 | 仅在连接前/断开后修改，接收期间只读遍历 |
| Socket 操作 | 无锁 | 仅接收线程访问 socket，主线程通过 `_running` 标志和 `stop()` 间接控制 |

> **关键设计**: 帧回调函数在接收线程中**同步**调用，回调内部必须尽快返回（只做深拷贝，不做耗时操作）。GUI 渲染在主线程中通过 30ms 定时器**异步**执行。

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
tk.Tk (root)  — 标题 "J6B Video Player - PC 客户端"
│              默认大小 1280×800, 最小 960×600
└── ttk.Frame (main_frame, padding=4)
    │
    ├── ttk.LabelFrame "控制面板" (padding=6)
    │   └── ttk.Frame (row1)
    │       ├── ttk.Label "设备 IP:"
    │       ├── ttk.Entry (ip_entry, width=16, default="192.168.1.100")
    │       ├── ttk.Label "端口:"
    │       ├── ttk.Entry (port_entry, width=8, default="10086")
    │       ├── ttk.Button "连接" (connect_btn) → _toggle_connection()
    │       ├── ttk.Separator (VERTICAL)
    │       ├── ttk.Button "截图保存" (snapshot_btn, 初始 DISABLED) → _save_snapshot()
    │       ├── ttk.Button "选择保存目录" → _select_snapshot_dir()
    │       └── ttk.Label "FPS: --" (fps_label, RIGHT 对齐)
    │
    ├── ttk.Frame (content_frame)
    │   ├── ttk.LabelFrame "视频画面" (padding=2, LEFT, expand=True)
    │   │   └── tk.Canvas (video_canvas, bg="black")
    │   │       └── 初始: "等待连接...\n请输入设备 IP 并点击「连接」"
    │   │          字体: "DejaVu Sans" 14, 灰色, 居中
    │   │
    │   └── ttk.LabelFrame "帧信息" (padding=6, width=260, RIGHT, fill=Y)
    │       ├── tk.Text (info_text, DISABLED, 等宽 "Consolas" 10, 浅灰背景)
    │       │   └── 9 行帧信息: 帧类型/格式/分辨率/步长/帧序号/PIPE/CHN/数据长度/版本
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
          │ 画布: 清除占位文字     │      │ 日志: "✗ 连接失败..." │
          │ 日志: "✓ 已连接"      │      └─────────────────────┘
          │ 开始接收视频帧        │
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
          │ 画布: "已断开\n点击...│
          │ FPS: "--"            │
          └─────────────────────┘
```

### 8.3 画面渲染管线

```
接收线程 (Recv Thread):
    _current_frame = bgr_image.copy()    ← 深拷贝, _frame_lock 保护
    _current_info = frame_info

    ═══════════ 线程边界 ═══════════

主线程 (Main Thread, 30ms 定时器):
    _update_display()
        │
        _frame_lock.acquire()
        frame = _current_frame.copy()    ← 再次深拷贝, 双重隔离
        info = dict(_current_info)
        _frame_lock.release()
        │
        ▼
    _render_frame(frame, info)
        │
        ├── 计算缩放比例:
        │   scale = min(canvas_width / frame_width, canvas_height / frame_height)
        │   new_w, new_h = int(w * scale), int(h * scale)
        │
        ├── 色彩空间转换:
        │   rgb = frame[..., ::-1]       ← BGR → RGB (NumPy slice, O(1))
        │
        ├── 转换为 PIL 图像:
        │   pil_img = Image.fromarray(rgb)
        │
        ├── 高质量缩放:
        │   pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
        │
        ├── 转换为 tkinter 可用格式:
        │   self._photo_image = ImageTk.PhotoImage(pil_img)
        │
        ├── Canvas 绘制:
        │   canvas.delete("all")
        │   canvas.create_image(x, y, anchor=NW, image=photo_image)  ← 居中
        │   canvas.create_text(10, 10, "FPS: 30.0", fill="lime")     ← 叠加
        │
        └── 更新标签:
            fps_label.config(text="FPS: 30.0")
            _update_info_panel(info)     ← 更新右侧帧信息面板
```

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
| `hb_protocol.py` | 342 | 纯协议层 | 常量、枚举 (5 个类)、结构体布局、打包/解包/验证函数 (6 个) |
| `hb_video_client.py` | 440 | 核心引擎层 | `HBVideoClient` 类: TCP 连接、帧接收、NV12→BGR、回调管理 |
| `hb_video_gui.py` | 461 | GUI 界面层 | `HBVideoGUI` 类: tkinter 窗口、PIL 渲染、截图、信息面板 |
| `hb_video_cli.py` | 179 | CLI 界面层 | `CLIVideoClient` 类: argparse 参数、OpenCV 显示、帧保存 |
| `requirements.txt` | 2 | 依赖声明 | `numpy>=1.21.0`, `opencv-python>=4.5.0`, `Pillow>=9.0.0` |
| `README.md` | — | 简要说明 | 项目简介、快速开始、协议概述 |
| `DESIGN_DOC.md` | — | 架构文档 | 本文档 |

### 11.2 项目目录建议

```
J6B_Video_Player/
├── hb_protocol.py          # 协议定义
├── hb_video_client.py      # 核心通信引擎
├── hb_video_gui.py         # GUI 界面入口
├── hb_video_cli.py         # 命令行入口
├── requirements.txt        # Python 依赖
├── README.md               # 简要说明
├── DESIGN_DOC.md           # 架构设计文档
├── snapshots/              # 截图保存目录 (自动创建)
├── frames/                 # 帧保存目录 (CLI --save 自动创建)
└── .gitignore              # 建议添加 (见 11.3)
```

### 11.3 建议的 `.gitignore`

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

**Q: FPS 很低**

- 检查网络带宽（1920×1080 NV12 @ 30fps ≈ 95 MB/s）
- 确认 PC 端 CPU 性能足够（NV12→BGR 转换需要 CPU 资源）
- 可尝试降低设备端输出分辨率或使用 stride=width
- 检查是否在帧回调中执行了耗时操作

**Q: Ubuntu 上 GUI 无法启动**

- 确认已安装 `python3-tk`: `sudo apt install python3-tk`
- 确认 Python 版本 ≥ 3.10: `python3 --version`
- 确认 Pillow 已安装: `python3 -c "from PIL import Image"`

### 11.6 扩展开发建议

1. **支持 H.264/H.265 解码**: 在 `_recv_loop` 中识别 `VIDEO_DATA` (3) 类型，使用 PyAV/FFmpeg 进行硬件解码
2. **多路视频同时显示**: 创建多个 `HBVideoClient` 实例，分别连接不同 pipeline 或设备
3. **录制功能**: 在帧回调中使用 `cv2.VideoWriter` 保存为 MP4 文件
4. **AI 推理集成**: 在帧回调中将帧放入队列，由独立工作线程调用 ONNX Runtime / OpenCV DNN 进行目标检测
5. **Web 远程监控**: 将 `HBVideoClient` 封装为 FastAPI 服务，通过 WebSocket 或 MJPEG 流推送到浏览器
6. **RAW 数据支持**: 实现 Bayer→RGB 去马赛克算法，支持 `RAW_DATA` 类型的可视化
7. **ISP 调试面板**: 解析 `STATS_AWB_DATA`、`STATS_AEfull_DATA` 等 ISP 统计数据类型，在 GUI 中展示调试信息