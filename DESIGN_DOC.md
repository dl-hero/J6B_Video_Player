# J6B Video Player — 架构设计文档与使用说明

> **版本**: 1.0.0  
> **日期**: 2025-06-25  
> **适用平台**: J6B (Horizon Robotics J6 芯片平台)  
> **协议参考**: `hb_tool_server.h` / `hb_tool_server.c` / `camera_sample.c` / `socket_manager.c`

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
| `hb_tool_server.h` | 协议头定义、数据结构、枚举常量 |
| `hb_tool_server.c` | 服务端初始化、`hb_tool_start_transfer` / `hb_tool_send_yuv_pic` 等发送接口 |
| `camera_sample.c` | 发送端调用示例 — `vflow_show_init` / `vflow_show_img` |
| `socket_manager.c` | TCP Socket 收发实现、负载均衡、`send_data_to_pc_limit_bd` |
| `server_cmd.h` | 传输配置结构体 `tranfer_info_t`、内部状态管理 |

### 1.2 功能特性

| 功能 | 说明 |
|------|------|
| 远程视频流接收 | 通过以太网 TCP 连接 J6B 设备，实时接收 NV12 视频帧 |
| 实时 GUI 显示 | 基于 tkinter 的图形界面，支持画面缩放、FPS 叠加 |
| 命令行模式 | 支持无 GUI 环境运行（`--no-display`），可搭配 SSH 使用 |
| NV12→BGR 转换 | 纯 numpy 实现 ITU-R BT.601 标准的色彩空间转换，无需 OpenCV `cvtColor` |
| 帧同步 | 魔数搜索自动对齐帧边界，抗网络抖动 |
| 截图保存 | 支持 JPG 格式截图，可自定义保存目录 |
| 帧信息面板 | 实时显示帧类型、分辨率、帧序号、PIPE/CHN ID 等元数据 |
| FPS 统计 | 1 秒滑动窗口实时帧率统计 |
| 连接状态管理 | 异步连接/断开，状态栏和日志双重反馈 |

### 1.3 依赖

```
Python >= 3.10
numpy >= 1.21.0
opencv-python >= 4.5.0   (CLI 模式需要，GUI 模式可选)
Pillow >= 9.0.0           (GUI 模式需要)
```

安装命令：

```bash
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
│  │  (tkinter GUI)   │   │  (OpenCV 显示)    │   │  (API 调用)     │  │
│  └────────┬─────────┘   └────────┬─────────┘   └───────┬────────┘  │
│           │                      │                      │           │
│           │    帧回调 callback(frame_info, bgr_image)   │           │
│           └──────────────────────┼──────────────────────┘           │
│                                  ▼                                   │
│           ┌──────────────────────────────────────────────┐          │
│           │         hb_video_client.py                   │          │
│           │  ┌──────────────┐  ┌──────────────────────┐ │          │
│           │  │ 连接管理      │  │ NV12 → BGR 转换      │ │          │
│           │  │ (connect/    │  │ (_nv12_to_bgr)       │ │          │
│           │  │  disconnect) │  │ ITU-R BT.601         │ │          │
│           │  ├──────────────┤  ├──────────────────────┤ │          │
│           │  │ 帧接收线程    │  │ 帧同步               │ │          │
│           │  │ (_recv_loop) │  │ (_sync_to_header)    │ │          │
│           │  └──────────────┘  └──────────────────────┘ │          │
│           └──────────────────────┬───────────────────────┘          │
│                                  │                                   │
│           ┌──────────────────────┼───────────────────────┐          │
│           │        hb_protocol.py (协议层)                │          │
│           │  ┌────────────────┐  ┌────────────────────┐  │          │
│           │  │ 结构体定义      │  │ 打包/解包/验证      │  │          │
│           │  │ cmd_header_new │  │ pack/unpack/verify  │  │          │
│           │  │ tranfer_info   │  │ make_net_send_cfg   │  │          │
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
│  │                    hb_tool_server                             │   │
│  │  ┌────────────────┐  ┌────────────────────────────────────┐  │   │
│  │  │ TCP Server     │  │ 负载均衡 send_data_load_balance     │  │   │
│  │  │ (libevent)     │  │ (多通道优先级调度)                   │  │   │
│  │  └────────────────┘  └────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                  ▲                                   │
│  ┌───────────────────────────────┴──────────────────────────────┐   │
│  │  camera_sample / 用户应用程序                                  │   │
│  │  hb_tool_send_yuv_pic(event, &info, y, y_size, uv, uv_size)  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                  ▲                                   │
│  ┌───────────────────────────────┴──────────────────────────────┐   │
│  │  VIO (Video In/Out) / CAM 驱动层                               │   │
│  │  NV12 帧数据 (stride × height Y + stride × height/2 UV)       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
hb_video_gui.py ──────┐
                      ├──▶ hb_video_client.py ──▶ hb_protocol.py
hb_video_cli.py ──────┘
```

- **`hb_protocol.py`**: 纯协议层，无外部依赖（仅 `struct` + `enum`）
- **`hb_video_client.py`**: 依赖 `hb_protocol` + `socket` + `numpy` + `threading`
- **`hb_video_gui.py`**: 依赖 `hb_video_client` + `tkinter` + `PIL`
- **`hb_video_cli.py`**: 依赖 `hb_video_client` + `opencv-python`

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
      │     tranfer_info_t.tcp_open  = 1                     │
      │     tranfer_info_t.yuv_enable = 1                    │
      │                                                      │
      │  ④ 连续视频帧数据                                     │
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     [ cmd_header_new_t(80B) + NV12 Data ]            │
      │◀─────────────────────────────────────────────────────│
      │     ... (循环) ...                                    │
      │                                                      │
```

> **关键设计要点**: 设备端 (`hb_tool_server`) 仅在收到 PC 端发送的 `NET_SEND_CFG` 配置包（`tcp_open=1` 且 `yuv_enable=1`）后，才会开始发送视频帧数据。这一握手逻辑在 `send_data_to_pc_limit_bd` 函数中实现：
> ```c
> // socket_manager.c:384
> if ((t_base->socket.socket_num) && (tranfer_ctrl->tcp_open) && ...)
>     ret = socket_data_write_bd(...);
> ```

### 3.2 帧头结构体 `cmd_header_new_t`（80 字节）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     cmd_header_new_t (80 bytes)                      │
├───────┬────────┬──────────┬─────────────────────────────────────────┤
│ 偏移  │ 大小   │ 字段名    │ 说明                                    │
├───────┼────────┼──────────┼─────────────────────────────────────────┤
│ 0x00  │ 4B     │ header_start  │ 魔数: 固定 0xCCDDEEFF              │
│ 0x04  │ 4B     │ header_check1 │ 魔数: 固定 0x6789ABCD              │
│ 0x08  │ 4B     │ header_check2 │ 保留: 固定 0x00000000              │
│ 0x0C  │ 4B     │ header_end    │ 魔数: 固定 0xFFEEDDCC              │
│ 0x10  │ 4B     │ header_crc    │ CRC 校验值 (当前未使用)             │
├───────┼────────┼──────────┼─────────────────────────────────────────┤
│ 0x14  │ 4B     │ len           │ 数据体总长度 (Y_size + UV_size)    │
│ 0x18  │ 4B     │ type          │ 数据类型 (1=YUV_DATA, 0=RAW_DATA)  │
│ 0x1C  │ 4B     │ format        │ 子格式 (0=YUVNV12, 2=RAW_12)      │
├───────┼────────┼──────────┼─────────────────────────────────────────┤
│ 0x20  │ 4B     │ width         │ 图像有效宽度 (像素)                  │
│ 0x24  │ 4B     │ height        │ 图像有效高度 (像素)                  │
│ 0x28  │ 4B     │ stride        │ 行步长 (可能 ≥ width, 字节对齐)     │
│ 0x2C  │ 4B     │ frame_plane   │ Sensor 模式 (1=Normal, 2=DOL2, ...)│
│ 0x30  │ 4B     │ code_type     │ 编码类型 (0=H264, 1=H265)          │
│ 0x34  │ 4B     │ pipe_info     │ Pipeline 附加信息                    │
├───────┼────────┼──────────┼─────────────────────────────────────────┤
│ 0x38  │ 4B     │ pipe_id       │ Pipeline 编号                        │
│ 0x3C  │ 4B     │ chn_id        │ 通道编号 (YUV channel / RAW plane)  │
│ 0x40  │ 4B     │ frame_id      │ 帧序号 (单调递增)                    │
├───────┼────────┼──────────┼─────────────────────────────────────────┤
│ 0x44  │ 4B     │ chip_version  │ 芯片版本 (2=J6)                     │
│ 0x48  │ 4B     │ plugin_id     │ 插件 ID                             │
│ 0x4C  │ 4B     │ reserved2     │ 保留字段                             │
└───────┴────────┴──────────┴─────────────────────────────────────────┘
```

> **struct 格式**: 所有字段均为小端序（Little-Endian），与 ARM 嵌入式平台一致。Python 打包格式: `"<" + "I" * 20`（20 个 `uint32_t`）。

### 3.3 传输配置结构体 `tranfer_info_t`（24 字节）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     tranfer_info_t (24 bytes)                        │
├───────┬────────┬────────────────┬───────────────────────────────────┤
│ 偏移  │ 大小   │ 字段名          │ 说明                              │
├───────┼────────┼────────────────┼───────────────────────────────────┤
│ 0x00  │ 1B     │ tcp_open       │ TCP 传输开关 (1=开启)             │
│ 0x01  │ 1B     │ raw_enable     │ RAW 数据使能                      │
│ 0x02  │ 1B     │ raw_serial_num │ RAW 序列号                        │
│ 0x03  │ 1B     │ yuv_enable     │ YUV 数据使能 (1=开启)             │
│ 0x04  │ 1B     │ yuv_serial_num │ YUV 序列号                        │
│ 0x05  │ 1B     │ jepg_enable    │ JPEG 数据使能                     │
│ 0x06  │ 1B     │ video_enable   │ 编码视频使能                      │
│ 0x07  │ 1B     │ video_code     │ 视频编码格式                      │
│ 0x08  │ 2B     │ bit_stream     │ 比特流参数                        │
│ 0x0A  │ 2B     │ fream_interval │ 帧间隔                            │
│ 0x0C  │ 2B     │ pipe_line      │ Pipeline 编号                     │
│ 0x0E  │ 2B     │ channel_id     │ 通道 ID                           │
│ 0x10  │ 4B     │ param_id       │ 视频配置参数 ID                   │
│ 0x14  │ 4B     │ param_data     │ 视频配置参数数据                   │
└───────┴────────┴────────────────┴───────────────────────────────────┘
```

Python 打包格式: `"<8B4H2I"` (8 个 `uint8_t` + 4 个 `uint16_t` + 2 个 `uint32_t`)

### 3.4 数据类型枚举

| 枚举值 | 名称 | 说明 |
|--------|------|------|
| 0 | `RAW_DATA` | RAW Bayer 数据 |
| 1 | `YUV_DATA` | YUV 数据 (本工具主要处理) |
| 2 | `JPEG_DATA` | JPEG 压缩数据 |
| 3 | `VIDEO_DATA` | H.264/H.265 编码视频 |
| 13 | `NET_SEND_CFG` | PC→设备: 传输配置命令 |

### 3.5 NV12 数据布局

```
┌─────────────────────────────────────┐
│          Y Plane (亮度)              │
│  stride × height 字节                │
│  ┌─────────────────────────────┐    │
│  │ Y₀₀ Y₀₁ Y₀₂ ... Y₀(w-1)  │    │  ← 有效宽度 = width
│  │ Y₁₀ Y₁₁ Y₁₂ ... Y₁(w-1)  │    │
│  │ ...                        │    │
│  │ Y₍h₋₁₎₀ ... Y₍h₋₁₎₍w₋₁₎  │    │
│  └─────────────────────────────┘    │
│  (stride - width) 列填充 (padding)   │
├─────────────────────────────────────┤
│        UV Plane (交错色度)           │
│  stride × height / 2 字节            │
│  ┌─────────────────────────────┐    │
│  │ U₀₀ V₀₀ U₀₁ V₀₁ ...      │    │  ← UV 交错排列
│  │ U₁₀ V₁₀ U₁₁ V₁₁ ...      │    │
│  │ ...                        │    │
│  └─────────────────────────────┘    │
│  每个 2×2 像素块共用一对 UV          │
└─────────────────────────────────────┘

总数据量: stride × height × 1.5 字节
```

---

## 4. 模块设计

### 4.1 `hb_protocol.py` — 协议层

**职责**: 定义所有协议常量、枚举、结构体布局、打包/解包/验证函数。

**核心 API**:

| 函数 | 说明 |
|------|------|
| `pack_cmd_header(fields)` | 将 20 个 uint32 列表打包为 80 字节二进制 |
| `unpack_cmd_header(data)` | 将 80 字节二进制解包为 20 个 uint32 列表 |
| `verify_header(fields)` | 验证帧头三个魔数是否正确 |
| `make_net_send_cfg_packet(...)` | 构建 104 字节的 NET_SEND_CFG 握手包 |
| `make_yuv_frame_header(...)` | 构建 YUV 帧头（供理解协议，PC 端不发送） |
| `parse_frame_info(fields)` | 从 header 字段提取帧信息字典 |

**设计模式**: 无状态的纯函数模块，所有函数无副作用。

### 4.2 `hb_video_client.py` — 网络通信与解码层

**职责**: TCP 连接管理、帧接收、NV12→BGR 转换、帧回调通知。

**核心类**: `HBVideoClient`

| 方法 | 说明 |
|------|------|
| `__init__(host, port, ...)` | 初始化客户端参数 |
| `connect()` | 建立 TCP 连接 + 发送 NET_SEND_CFG 握手包 |
| `disconnect()` | 关闭 TCP 连接 |
| `start()` | 启动后台接收线程 |
| `stop()` | 停止接收线程并断开连接 |
| `register_frame_callback(cb)` | 注册帧回调 `cb(frame_info, bgr_image)` |
| `remove_frame_callback(cb)` | 移除帧回调 |
| `get_stats()` | 获取帧计数/错误计数统计 |

**内部方法**:

| 方法 | 说明 |
|------|------|
| `_recv_loop()` | 接收线程主循环: 读头→验证→读体→转换→通知 |
| `_recv_exact(size)` | 精确接收指定字节数 |
| `_sync_to_header(data)` | 魔数搜索帧同步 |
| `_nv12_to_bgr(data, w, h, stride)` | 静态方法: NV12→BGR 色彩转换 |
| `_notify_frame(info, img)` | 通知所有注册的回调函数 |

**`is_connected` 属性**: 返回当前 TCP 连接状态。

### 4.3 `hb_video_gui.py` — GUI 界面层

**职责**: 提供 tkinter 图形界面，包含连接管理、视频渲染、信息显示、截图功能。

**核心类**: `HBVideoGUI`

**UI 布局**:

```
┌─────────────────────────────────────────────────────────────────────┐
│  J6B Video Player - PC 客户端                          [_][□][×]   │
├─────────────────────────────────────────────────────────────────────┤
│ ┌ 控制面板 ──────────────────────────────────────────────────────┐ │
│ │ 设备IP: [192.168.1.100]  端口: [10086]  [连接]  │ [截图] [目录] │ │
│ │                                                      FPS: 30.0 │ │
│ └────────────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────┬─────────────────────────────┤
│ ┌ 视频画面 ──────────────────────────┐│ ┌ 帧信息 ──────────────────┐│
│ │                                    ││ │ 帧类型:   YUV_DATA       ││
│ │                                    ││ │ 图像格式: 0              ││
│ │         FPS: 30.0                  ││ │ 分辨率:   1920 × 1080    ││
│ │                                    ││ │ 行步长:   1920           ││
│ │                                    ││ │ 帧序号:   #12345         ││
│ │                                    ││ │ PIPE ID:  0              ││
│ │                                    ││ │ CHN ID:   0              ││
│ │                                    ││ │ 数据长度: 3110400 bytes  ││
│ │                                    ││ │ 芯片版本: J2             ││
│ │                                    ││ ├──────────────────────────┤│
│ │                                    ││ │ ┌ 日志 ───────────────┐ ││
│ │                                    ││ │ │ [21:30:01] ✓ 已连接  │ ││
│ │                                    ││ │ │ [21:30:02] 等待视频流│ ││
│ └────────────────────────────────────┘│ │ └──────────────────────┘ ││
│                                       │ └──────────────────────────┘│
├───────────────────────────────────────┴─────────────────────────────┤
│ [就绪]                                                  状态栏      │
└─────────────────────────────────────────────────────────────────────┘
```

**关键方法**:

| 方法 | 说明 |
|------|------|
| `_build_ui()` | 构建完整 UI（控制面板+视频+信息+状态栏） |
| `_toggle_connection()` | 连接/断开切换 |
| `_on_frame_received(info, img)` | 帧回调（接收线程）: 深拷贝帧 + FPS 统计 |
| `_update_display()` | 定时器（30ms）: 从共享缓冲区取帧渲染 |
| `_render_frame(img, info)` | BGR→RGB→PIL→ImageTk 渲染管线 |
| `_save_snapshot()` | 当前帧保存为 JPG |

### 4.4 `hb_video_cli.py` — 命令行界面

**职责**: 无 GUI 依赖的命令行客户端，支持 OpenCV 窗口显示、帧保存、键盘控制。

**核心类**: `CLIVideoClient`

**命令行参数**:

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `host` | 设备 IP 地址（必填） | — |
| `port` | TCP 端口 | `10086` |
| `--save` | 启用帧保存 | `False` |
| `--save-dir` | 帧保存目录 | `./frames` |
| `--no-display` | 禁用 OpenCV 显示窗口 | `False` |

**键盘快捷键**:

| 按键 | 功能 |
|------|------|
| `q` / `ESC` | 退出程序 |
| `s` | 截图保存到 `./snapshots/` |

---

## 5. 数据流与线程模型

### 5.1 线程架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           线程模型                                   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Main Thread (主线程 / GUI 线程)                               │   │
│  │  - tkinter 事件循环 (mainloop)                                 │   │
│  │  - 30ms 定时器 _update_display()                              │   │
│  │  - 从 _current_frame / _current_info 读取 (加锁)               │   │
│  │  - BGR→RGB→PIL→ImageTk 渲染                                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              ▲                                       │
│                              │ 帧回调 (在接收线程中调用)               │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Recv Thread (接收线程, daemon)                                │   │
│  │  - _recv_loop() 循环                                          │   │
│  │  - socket.recv() → 解包帧头 → 验证魔数 → 读取数据体            │   │
│  │  - NV12→BGR 转换 (_nv12_to_bgr)                               │   │
│  │  - 深拷贝到 _current_frame / _current_info (加锁)              │   │
│  │  - 调用所有已注册的帧回调                                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Connect Thread (临时线程, 连接时创建)                          │   │
│  │  - 执行 TCP connect + NET_SEND_CFG 发送                        │   │
│  │  - 完成后通过 root.after() 切回主线程                           │   │
│  │  - 连接成功后创建 Recv Thread                                  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 帧数据流

```
TCP Socket
    │
    ▼
_recv_exact(80) ────── 帧头 (80 bytes)
    │
    ▼
unpack_cmd_header() ── 20 个 uint32_t 字段
    │
    ▼
verify_header() ────── 魔数验证 (0xCCDDEEFF / 0x6789ABCD / 0xFFEEDDCC)
    │
    ├── 失败 → _sync_to_header() ── 魔数搜索同步 → 重试
    │
    ▼ 成功
_recv_exact(data_len) ─ 数据体 (NV12 原始数据)
    │
    ▼
_nv12_to_bgr() ──────── Y/UV 分离 → 上采样 → YUV→RGB (BT.601)
    │
    ▼
frame_info + bgr_image (np.ndarray)
    │
    ├──▶ _frame_lock.acquire()
    │    _current_frame = bgr_image.copy()  (深拷贝)
    │    _current_info = frame_info
    │    _frame_lock.release()
    │
    ├──▶ _notify_frame() → 所有回调函数
    │
    ▼
GUI 定时器 (30ms)
    │
    _frame_lock.acquire()
    frame = _current_frame.copy()
    _frame_lock.release()
    │
    ▼
_render_frame()
    BGR → RGB → PIL.Image → ImageTk.PhotoImage → Canvas.create_image()
```

### 5.3 线程安全

- 使用 `threading.Lock()` 保护 `_current_frame` / `_current_info` 共享缓冲区
- 接收线程写入时深拷贝（`np.copy()`），避免 buffer 被覆盖
- GUI 渲染线程读取时再次深拷贝，确保渲染期间数据不变
- 帧回调在接收线程中同步调用，回调内部应尽快返回

---

## 6. NV12→BGR 色彩转换

### 6.1 转换流程

```
NV12 数据 (bytes)
    │
    ├─▶ Y  plane: stride × height 字节 ──▶ np.reshape(height, stride)
    │                                                        │
    │                                               stride > width ?
    │                                                  ├─ 是 → crop[:, :width]
    │                                                  └─ 否 → 保持
    │
    └─▶ UV plane: stride × height/2 字节 ──▶ np.reshape(height/2, stride)
                                                         │
                                               stride > width ?
                                                  ├─ 是 → crop[:, :width]
                                                  └─ 否 → 保持
                                                         │
                                            ┌────────────┴────────────┐
                                            ▼                         ▼
                                      U = uv[:, 0::2]           V = uv[:, 1::2]
                                      (偶数列)                   (奇数列)
                                            │                         │
                                            ▼                         ▼
                                      np.repeat(2, axis=0)      np.repeat(2, axis=0)
                                      np.repeat(2, axis=1)      np.repeat(2, axis=1)
                                      (最近邻上采样 2×)           (最近邻上采样 2×)
                                            │                         │
                                            └────────────┬────────────┘
                                                         │
                                                         ▼
                                            ITU-R BT.601 矩阵变换
                                            ┌──────────────────────────────┐
                                            │ R = 1.164×(Y-16) + 1.596×(V-128) │
                                            │ G = 1.164×(Y-16) - 0.392×(U-128) │
                                            │                         - 0.813×(V-128) │
                                            │ B = 1.164×(Y-16) + 2.017×(U-128) │
                                            └──────────────────────────────┘
                                                         │
                                                         ▼
                                            np.clip(0, 255) → uint8
                                                         │
                                                         ▼
                                            np.stack([B, G, R], axis=-1)
                                            BGR 图像 (height, width, 3)
```

### 6.2 为什么不用 OpenCV 的 `cvtColor`？

1. **减少依赖**: `hb_video_client.py` 作为核心通信层，不依赖 OpenCV，可在纯 numpy 环境运行
2. **stride 处理**: 设备端 NV12 的 stride 可能大于 width（硬件对齐要求），OpenCV 的 `cvtColor` 不直接支持 stride≠width 的情况
3. **可控性**: 自定义实现可精确控制上采样算法（当前使用最近邻，可替换为双线性）

### 6.3 性能考量

- 对于 1920×1080 分辨率，每帧 NV12 数据约 3.1MB，BGR 输出约 6.2MB
- 纯 numpy 向量化实现，无 Python 循环，转换耗时约 10-20ms (取决于 CPU)
- 通过 `np.float32` 中间类型保证精度，最终 `clip` 到 `uint8`

---

## 7. 帧同步机制

### 7.1 问题背景

TCP 是流式协议，没有消息边界。当网络抖动或 PC 端启动时恰好处于帧数据中间位置，可能无法正确解析帧头。

### 7.2 同步算法 `_sync_to_header()`

```
输入: 已读取的 80 字节 (可能无效)
输出: True=同步成功, False=超时

算法:
  1. 初始化搜索缓冲区 sync_buffer = 已读数据
  2. 循环:
     a. 在 sync_buffer 中搜索 4 字节魔数 0xCCDDEEFF
     b. 如果找不到:
        - 从 socket 读取 4096 字节追加到缓冲区
        - 保留最后 4 字节 (防止魔数跨 recv 边界)
        - 继续搜索
     c. 找到后:
        - 检查缓冲区是否包含完整 80 字节帧头
        - 解包并验证三个魔数 (start/check1/end)
        - 如果有效:
          - 读取 data_len 字节数据体 (丢弃，因为当前帧已不完整)
          - 返回 True (下一轮 recv 将从下一帧头开始)
        - 如果无效:
          - 从 pos+1 位置继续搜索
  3. 最多扫描 1MB 数据，超时返回 False
```

### 7.3 适用场景

| 场景 | 行为 |
|------|------|
| 正常帧流 | 魔数验证通过，直接解析 |
| 网络抖动丢包 | 自动搜索下一帧头，丢弃损坏帧 |
| 中途连接 | 跳过当前半帧，对齐到下一帧 |
| 协议不匹配 | 扫描 1MB 后超时，报告错误 |

---

## 8. GUI 界面设计

### 8.1 组件树

```
tk.Tk (root)
└── ttk.Frame (main_frame)
    ├── ttk.LabelFrame "控制面板"
    │   └── ttk.Frame (row1)
    │       ├── ttk.Label "设备 IP:"
    │       ├── ttk.Entry (ip_entry)
    │       ├── ttk.Label "端口:"
    │       ├── ttk.Entry (port_entry)
    │       ├── ttk.Button "连接" (connect_btn)
    │       ├── ttk.Separator
    │       ├── ttk.Button "截图保存" (snapshot_btn)
    │       ├── ttk.Button "选择保存目录"
    │       └── ttk.Label "FPS: --" (fps_label)
    ├── ttk.Frame (content_frame)
    │   ├── ttk.LabelFrame "视频画面"
    │   │   └── tk.Canvas (video_canvas)
    │   └── ttk.LabelFrame "帧信息"
    │       ├── tk.Text (info_text)
    │       └── ttk.LabelFrame "日志"
    │           └── tk.Text (log_text)
    └── ttk.Label 状态栏 (status_bar)
```

### 8.2 交互流程

```
                            ┌──────────────┐
                            │   程序启动     │
                            └──────┬───────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │ 显示 "等待连接..."    │
                        │ 连接按钮: [连接]      │
                        │ 截图按钮: 禁用        │
                        └──────────┬──────────┘
                                   │ 用户点击 [连接]
                                   ▼
                        ┌─────────────────────┐
                        │ 连接按钮: [连接中...] │
                        │ 后台线程: TCP connect │
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
        │ 连接按钮: [断开]      │      │ 连接按钮: [连接]      │
        │ 截图按钮: 启用        │      │ 弹窗: 连接失败        │
        │ 状态: "已连接 x.x.x.x"│      │ 状态: "连接失败"      │
        │ 开始接收视频流        │      └─────────────────────┘
        └──────────┬──────────┘
                   │ 用户点击 [断开] 或 关闭窗口
                   ▼
        ┌─────────────────────┐
        │ 停止接收线程          │
        │ 断开 TCP 连接         │
        │ 显示 "已断开"         │
        │ 截图按钮: 禁用        │
        └─────────────────────┘
```

### 8.3 画面渲染管线

```
接收线程: _current_frame (BGR np.ndarray)
    │
    ▼ (30ms 定时器)
主线程: _update_display()
    │
    ▼
frame = _current_frame.copy()    # 深拷贝, 线程安全
    │
    ▼
_render_frame(frame, info)
    │
    ├── 计算缩放比例: scale = min(canvas_w/w, canvas_h/h)
    │
    ├── BGR → RGB: frame[..., ::-1]
    │
    ├── RGB array → PIL.Image
    │
    ├── PIL.Image.resize(new_w, new_h, LANCZOS)   # 高质量缩放
    │
    ├── PIL.Image → ImageTk.PhotoImage
    │
    ├── Canvas.delete("all")
    ├── Canvas.create_image(x, y, image=photo)     # 居中显示
    └── Canvas.create_text(10, 10, "FPS: 30.0")    # 叠加 FPS
```

---

## 9. 使用说明

### 9.1 环境准备

**PC 端**:

```bash
# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "import numpy; import cv2; from PIL import Image; print('OK')"
```

**J6B 设备端**:

确保设备端应用程序已集成 `hb_tool_server` 并启动传输。典型方式：

```bash
# 在 J6B 设备上运行 camera_sample (启用 hbplayer 显示)
camera_sample -s 1 -S 0

# 或指定端口
camera_sample -s 1 -S 10086
```

关键参数说明：
- `-s 1`: 启用 hbplayer 显示传输
- `-S <port>`: 指定监听端口，0 表示使用默认端口 10086

### 9.2 启动 GUI 版本

```bash
python hb_video_gui.py
```

操作步骤：

1. 在「设备 IP」输入框中填入 J6B 设备的 IP 地址
2. 端口保持默认 `10086`（如设备端使用了自定义端口，相应修改）
3. 点击 **「连接」** 按钮
4. 等待 1-2 秒，视频画面即可显示
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

# 仅保存帧，不显示窗口 (适合服务器环境)
python hb_video_cli.py 192.168.1.100 --no-display --save --save-dir ./captured_frames

# 查看帮助
python hb_video_cli.py --help
```

**键盘控制** (CLI 模式):

| 按键 | 功能 |
|------|------|
| `q` 或 `ESC` | 退出程序 |
| `s` | 截图保存到 `./snapshots/` |
| `Ctrl+C` | 终端中断退出 |

### 9.4 作为库使用

```python
from hb_video_client import HBVideoClient
import cv2

def my_callback(frame_info, bgr_image):
    """自定义帧处理"""
    print(f"收到帧 #{frame_info['frame_id']}: "
          f"{frame_info['width']}×{frame_info['height']}")
    # 在此处进行自定义处理 (AI 推理、图像分析等)
    cv2.imshow("Video", bgr_image)
    cv2.waitKey(1)

client = HBVideoClient(host="192.168.1.100", port=10086, enable_yuv=True)
client.register_frame_callback(my_callback)
client.start()

# 阻塞主线程
try:
    while client.is_connected:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.stop()
```

### 9.5 高级配置

在 `HBVideoClient` 构造函数中可配置：

```python
client = HBVideoClient(
    host="192.168.1.100",  # 设备 IP
    port=10086,            # TCP 端口
    enable_yuv=True,       # 启用 YUV 数据接收
    enable_raw=False,      # 启用 RAW 数据接收 (调试用)
    pipe_line=0,           # Pipeline 编号
    channel_id=0,          # 通道编号
)
```

---

## 10. 错误处理与异常恢复

### 10.1 错误分类

| 错误类型 | 处理策略 |
|----------|----------|
| TCP 连接超时 | 返回 `False`，GUI 弹窗提示用户检查 IP/端口 |
| TCP 连接被拒绝 | 返回 `False`，提示设备端服务未启动 |
| 帧头魔数不匹配 | 触发 `_sync_to_header()` 自动同步 |
| 帧头解包失败 | 跳过当前帧，`error_count++` |
| 数据体接收不完整 | 跳过当前帧，`error_count++` |
| NV12→BGR 转换失败 | 跳过当前帧，记录错误日志 |
| 接收线程异常退出 | `is_connected` 变为 `False`，GUI 可检测并提示重连 |
| Socket 被动断开 | `_recv_exact` 返回 `None`，接收循环退出 |

### 10.2 自动恢复

- **帧同步恢复**: 魔数不匹配时自动搜索下一帧头，丢弃损坏数据
- **统计监控**: `get_stats()` 返回 `frame_count` 和 `error_count`，可监控链路质量
- **优雅关闭**: `stop()` 先设置 `_running=False`，等待接收线程退出（最多 3 秒），然后关闭 socket

### 10.3 日志级别

```python
import logging
logging.basicConfig(level=logging.DEBUG)  # 查看详细协议日志
```

---

## 11. 附录

### 11.1 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `hb_protocol.py` | ~343 | 协议定义: 常量、枚举、结构体、打包/解包 |
| `hb_video_client.py` | ~441 | 网络通信: TCP 连接、帧接收、NV12→BGR |
| `hb_video_gui.py` | ~462 | GUI 界面: tkinter 窗口、渲染、截图 |
| `hb_video_cli.py` | ~180 | CLI 界面: 命令行参数、OpenCV 显示 |
| `requirements.txt` | 3 | Python 依赖声明 |
| `README.md` | — | 简要说明 |
| `DESIGN_DOC.md` | — | 本文档 |

### 11.2 协议参考源文件清单

| 源文件 | 路径 |
|--------|------|
| `hb_tool_server.h` | `codebase/tools/viotool/libhbplayer/include/hb_tool_server.h` |
| `hb_tool_server.c` | `codebase/tools/viotool/libhbplayer/src/server/src/hb_tool_server.c` |
| `camera_sample.c` | `codebase/test/samples/platform_samples/source/S83_Sample/S83E04_Module/camera_sample/src/camera_sample.c` |
| `socket_manager.c` | `codebase/tools/viotool/libhbplayer/src/server/src/socket/socket_manager.c` |
| `socket_manager.h` | `codebase/tools/viotool/libhbplayer/src/server/inc/socket/socket_manager.h` |
| `server_cmd.h` | `codebase/tools/viotool/libhbplayer/src/server/inc/common/server_cmd.h` |

### 11.3 常见问题排查

**Q: 连接失败，提示 "Connection refused"**

- 确认 J6B 设备端已运行 `camera_sample -s 1`
- 确认 PC 与设备在同一网络，可 ping 通
- 确认防火墙未阻止端口 10086

**Q: 连接成功但无画面**

- 确认设备端 `hb_tool_server` 版本为 TOOL_VERSION=2 (J6)
- 检查 `NET_SEND_CFG` 包中 `tcp_open` 和 `yuv_enable` 是否均为 1
- 查看日志中是否有帧头魔数错误

**Q: 画面花屏或颜色异常**

- 检查 stride 是否等于 width（stride > width 时需要裁剪）
- 确认 NV12 格式正确（Y 平面在前，UV 交错平面在后）
- 如果是 RAW 数据，需要使用不同的解码路径

**Q: FPS 很低**

- 检查网络带宽（1920×1080 NV12 30fps ≈ 95MB/s）
- 确认 PC 性能足够（NV12→BGR 转换需要 CPU 资源）
- 可尝试降低设备端输出分辨率

### 11.4 扩展开发建议

1. **支持 H.264/H.265 解码**: 在 `_recv_loop` 中识别 `VIDEO_DATA` 类型，使用 FFmpeg/PyAV 解码
2. **多路视频**: 注册多个 `HBVideoClient` 实例连接不同 pipeline
3. **录制功能**: 在帧回调中使用 `cv2.VideoWriter` 保存为 MP4
4. **AI 推理集成**: 在帧回调中调用 OpenCV DNN / ONNX Runtime 进行目标检测
5. **Web 前端**: 将 `HBVideoClient` 封装为 Flask/FastAPI 服务，通过 WebSocket 推送 MJPEG 流