# VENC Stream — J6B 视频编码 + TCP 流式输出

CIM4 四路视频流 → VPU H.264 硬件编码 → TCP 发送到 PC 端。

## 文件结构

```
tools/viotool/venc_stream/
├── README.md            # 本文件
├── bin/
│   └── run.sh           # J6B 设备端一键启动脚本
└── src/
    ├── venc_stream.c    # 主程序 (~330 行)
    └── Makefile         # SDK 交叉编译
```

## 数据流

```
Camera ×4 → CIM4 (DDR output) → DDR → VPU Encoder ×4 → H.264 → TCP port 10086 → PC
```

## 编译 (在 SDK 开发机上)

```bash
# 1. 进入 SDK 目录并 source 编译环境
cd {sdk_dir}
source build/env.sh    # 按实际 SDK 环境脚本

# 2. 编译
cd tools/viotool/venc_stream/src
make

# 3. 部署到 bin
cp venc_stream ../bin/
```

## 部署到 J6B

```bash
# SSH 到设备
ssh root@<J6B_IP>

# 创建目录
mkdir -p /app/sample/S83_Sample/S83E04_Module/venc_stream/bin
mkdir -p /app/sample/S83_Sample/S83E04_Module/venc_stream/src

# 从 PC 上传 (scp)
scp bin/venc_stream root@<J6B_IP>:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
scp bin/run.sh        root@<J6B_IP>:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
```

## 运行

```bash
# 在 J6B 上
cd /app/sample/S83_Sample/S83E04_Module/venc_stream/bin
sh run.sh

# 或指定自定义 JSON 配置
sh run.sh /path/to/vpm_config.json /path/to/hb_j6dev.json
```

## TCP 协议

兼容现有 hb_tool_server 协议 (cmd_header_new_t 80B + H.264 数据)。

PC 端用现有 hb_video_client.py 连接，需在 `_recv_loop` 中新增 `DataType.VIDEO_DATA` (type=3) 分支:
- 用 PyAV / OpenCV 解码 H.264 AnnexB 码流
- 按 `pipe_id` 分路显示

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 通道数 | 4 | |
| 分辨率 | 1696×1168 | SC361AT 传感器 |
| 帧率 | 30fps | |
| 编码 | H.264 CBR 4Mbps/路 | 总带宽 ~16Mbps |
| TCP 端口 | 10086 | 与 camera_sample 一致 |
| Pipeline ID | 7, 8, 9, 10 | vpm_config.json pipeline7-10 |
| CAM Port | 7, 8, 9, 10 | hb_j6dev.json port_7-10 |
| 配置文件 | GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4 | case_matrix 目录 |
