# J6B Video Player - PC 端视频流客户端

基于 J6B 平台 `hb_tool_server` 协议的 PC 端视频流接收与显示工具。

## 功能

- 通过以太网 (TCP) 连接 J6B 设备，接收实时视频流
- 支持 NV12 (YUV420) 格式视频解码显示
- GUI 界面实时预览 (基于 tkinter + OpenCV)
- FPS 实时统计
- 帧信息面板 (分辨率、帧序号、数据类型等)
- 截图保存功能
- 自动帧同步 (断线重连后自动对齐帧头)

## 协议说明

### 通信流程

```
PC (Client)                          J6B 设备 (Server)
    |                                       |
    |-------- TCP Connect (port 10086) ---->|
    |                                       |
    |--- NET_SEND_CFG (104 bytes) -------->|  启用 YUV 传输
    |                                       |
    |<--- cmd_header(80B) + NV12 data ----|  连续帧数据
    |<--- cmd_header(80B) + NV12 data ----|
    |<--- cmd_header(80B) + NV12 data ----|
    |                 ...                   |
```

### 帧格式

每帧数据 = **80 字节帧头** + **NV12 图像数据**

| 字段 | 偏移 | 大小 | 说明 |
|------|------|------|------|
| header_start | 0 | 4 | 魔数 `0xCCDDEEFF` |
| header_check1 | 4 | 4 | 魔数 `0x6789ABCD` |
| header_check2 | 8 | 4 | 保留 |
| header_end | 12 | 4 | 魔数 `0xFFEEDDCC` |
| header_crc | 16 | 4 | CRC |
| len | 20 | 4 | 数据体长度 |
| type | 24 | 4 | 数据类型 (1=YUV) |
| format | 28 | 4 | 格式 (0=NV12) |
| width | 32 | 4 | 图像宽度 |
| height | 36 | 4 | 图像高度 |
| stride | 40 | 4 | 行步长 |
| ... | ... | ... | ... |
| pipe_id | 56 | 4 | Pipeline ID |
| frame_id | 64 | 4 | 帧序号 |

### NV12 数据布局

- Y 平面: `stride × height` 字节 (亮度)
- UV 平面: `stride × height / 2` 字节 (交错色度, UVUV...)

## 依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 设备端准备

确保 J6B 设备端已运行带 `hbplayer` 支持的 camera sample:

```bash
# 设备端运行 (启用 hbplayer 显示)
camera_sample -s 1 -S 0
```

或任何集成了 `hb_tool_start_transfer` 的应用程序。

### 2. PC 端启动

```bash
python hb_video_gui.py
```

### 3. 操作

1. 在「设备 IP」输入框中填写 J6B 设备的 IP 地址
2. 端口默认为 `10086`，一般无需修改
3. 点击「连接」按钮
4. 连接成功后即可看到实时视频画面
5. 点击「截图保存」将当前帧保存为 JPG 文件

## 文件结构

```
J6B_Video_Player/
├── hb_protocol.py      # 协议定义 (结构体、常量、辅助函数)
├── hb_video_client.py  # 网络通信 + NV12 解码
├── hb_video_gui.py     # GUI 界面 (tkinter)
├── requirements.txt    # Python 依赖
└── README.md           # 本文件
```

## 自定义参数

在 `hb_video_gui.py` 的 `_connect()` 方法中可修改:

```python
client = HBVideoClient(
    host=host,
    port=port,
    enable_yuv=True,   # 启用 YUV 接收
    enable_raw=False,  # 是否启用 RAW 接收
    pipe_line=0,       # pipeline 编号
    channel_id=0,      # 通道编号
)
```

## 参考源文件

- `hb_tool_server.h` — 协议头定义
- `hb_tool_server.c` — 服务端发送逻辑
- `camera_sample.c` — 发送端调用示例
- `socket_manager.c` — Socket 收发实现
- `server_cmd.h` — 传输配置结构体