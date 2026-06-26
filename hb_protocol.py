# -*- coding: utf-8 -*-
"""
hb_protocol.py - J6B HBPlayer 通信协议定义

基于 J6B 平台 hb_tool_server 协议分析:
  - 设备端作为 TCP Server (默认端口 10086)
  - PC 端作为 TCP Client 连接后发送 NET_SEND_CFG 启用视频流传输
  - 每帧数据: cmd_header_new_t (80字节) + 图像数据

协议参考文件:
  - hb_tool_server.h  : 协议头定义
  - server_cmd.h      : 传输配置结构体
  - socket_manager.c  : socket 收发逻辑
  - camera_sample.c   : 发送端调用示例
"""

import struct
from enum import IntEnum

# ============================================================================
# 协议常量
# ============================================================================

# 帧头/帧尾魔数
TOOL_HEADER_START_N  = 0xCCDDEEFF
TOOL_HEADER_CHECK1_N = 0x6789ABCD
TOOL_HEADER_CHECK2_N = 0x00000000
TOOL_HEADER_END_N    = 0xFFEEDDCC

# 芯片版本
TOOL_VERSION = 2  # 0-XJ3, 1-J5, 2-J6

# 默认端口
DEFAULT_PORT = 10086

# 命令类型
COMMAND_SET = 0x00000000
COMMAND_GET = 0x00000001


class RawBit(IntEnum):
    """RAW 数据位宽"""
    RAW_8       = 0
    RAW_10      = 1
    RAW_12      = 2
    RAW_14      = 3
    RAW_16      = 4
    RAW_COMP_10 = 5
    RAW_COMP_12 = 6
    RAW_COMP_14 = 7


class YuvType(IntEnum):
    """YUV 数据格式"""
    YUVNV12        = 0
    YUV420         = 1
    YUV422         = 2
    YUV444         = 3
    YUVI420        = 4
    RGB888         = 5
    YUV_NV12_Y_10BIT = 6
    YUV_NV12_Y_12BIT = 7


class VideoType(IntEnum):
    """视频编码类型"""
    H264 = 0
    H265 = 1
    PPS  = 2


class DataType(IntEnum):
    """数据类型枚举"""
    RAW_DATA               = 0
    YUV_DATA               = 1
    JPEG_DATA              = 2
    VIDEO_DATA             = 3
    VIDEO_CFG              = 4
    STATS_AWB_DATA         = 5
    STATS_AEfull_DATA      = 6
    STATS_AE5bin_DATA      = 7
    STATS_LUMVAR_DATA      = 8
    STATS_AF_DATA          = 9
    RGB888_DATA            = 10
    NEW_CMD_HEADER         = 11
    ISP_INFO_DATA          = 12
    NET_SEND_CFG           = 13
    ACT_CTL_DATA           = 14
    ACT_CTL_ACK            = 15
    MESSAGE_CTL_DEFINE_BY_USE = 16
    MESSAGE_CTL_ARC        = 17
    METADATA_INFO          = 18
    MESSAGE_PLUGIN         = 19
    RECEIVE_UNSERVED       = 20


class SensorMode(IntEnum):
    """Sensor 模式"""
    NORMAL = 1
    DOL2   = 2
    DOL3   = 3
    DOL4   = 4


# ============================================================================
# C 结构体对应的 Python 结构 (struct 格式)
# ============================================================================

# cmd_header_new_t 结构体布局 (80 字节):
#   uint32_t header_start     (4)  偏移 0
#   uint32_t header_check1    (4)  偏移 4
#   uint32_t header_check2    (4)  偏移 8
#   uint32_t header_end       (4)  偏移 12
#   uint32_t header_crc       (4)  偏移 16
#   uint32_t len              (4)  偏移 20  -- 数据体长度
#   uint32_t type             (4)  偏移 24  -- DataType
#   uint32_t format           (4)  偏移 28  -- RawBit / YuvType
#   union metadata (24 bytes)      偏移 32
#     struct pic_i:
#       uint32_t width        (4)  偏移 32
#       uint32_t height       (4)  偏移 36
#       uint32_t stride       (4)  偏移 40
#       uint32_t frame_plane  (4)  偏移 44  -- sensor_mode
#       uint32_t code_type    (4)  偏移 48  -- VideoType
#       uint32_t pipe_info    (4)  偏移 52
#   union packinfo (12 bytes)      偏移 56
#     struct r_i:
#       uint32_t pipe_id      (4)  偏移 56
#       uint32_t chn_id       (4)  偏移 60
#       uint32_t frame_id     (4)  偏移 64
#   uint32_t chip_version     (4)  偏移 68
#   uint32_t plugin_id        (4)  偏移 72
#   uint32_t reserved2        (4)  偏移 76
# 总计: 80 字节

CMD_HEADER_SIZE = 80

# struct 格式字符串 (小端序, 与嵌入式平台一致)
CMD_HEADER_FORMAT = "<" + "I" * 20  # 80 字节 = 20 个 uint32_t

# 字段索引
IDX_HEADER_START  = 0
IDX_HEADER_CHECK1 = 1
IDX_HEADER_CHECK2 = 2
IDX_HEADER_END    = 3
IDX_HEADER_CRC    = 4
IDX_LEN           = 5
IDX_TYPE          = 6
IDX_FORMAT        = 7
IDX_WIDTH         = 8
IDX_HEIGHT        = 9
IDX_STRIDE        = 10
IDX_FRAME_PLANE   = 11
IDX_CODE_TYPE     = 12
IDX_PIPE_INFO     = 13
IDX_PIPE_ID       = 14
IDX_CHN_ID        = 15
IDX_FRAME_ID      = 16
IDX_CHIP_VERSION  = 17
IDX_PLUGIN_ID     = 18
IDX_RESERVED2     = 19

# tranfer_info_t 结构体布局 (24 字节):
#   uint8_t  tcp_open         (1)  偏移 0
#   uint8_t  raw_enable       (1)  偏移 1
#   uint8_t  raw_serial_num   (1)  偏移 2
#   uint8_t  yuv_enable       (1)  偏移 3
#   uint8_t  yuv_serial_num   (1)  偏移 4
#   uint8_t  jepg_enable      (1)  偏移 5
#   uint8_t  video_enable     (1)  偏移 6
#   uint8_t  video_code       (1)  偏移 7
#   uint16_t bit_stream       (2)  偏移 8
#   uint16_t fream_interval   (2)  偏移 10
#   uint16_t pipe_line        (2)  偏移 12
#   uint16_t channel_id       (2)  偏移 14
#   param_buf_t video_cfg:    (8)  偏移 16
#     uint32_t param_id       (4)  偏移 16
#     uint32_t param_data     (4)  偏移 20
# 总计: 24 字节

TRANSFER_INFO_SIZE = 24
TRANSFER_INFO_FORMAT = "<8B4H2I"


# ============================================================================
# 辅助函数
# ============================================================================

def pack_cmd_header(header_fields: list) -> bytes:
    """
    将 20 个 uint32_t 字段列表打包为 80 字节的 cmd_header_new_t.

    Args:
        header_fields: 长度为 20 的 uint32_t 列表

    Returns:
        80 字节的二进制数据
    """
    assert len(header_fields) == 20, f"需要 20 个字段, 实际 {len(header_fields)}"
    return struct.pack(CMD_HEADER_FORMAT, *header_fields)


def unpack_cmd_header(data: bytes) -> list:
    """
    将 80 字节的二进制数据解包为 20 个 uint32_t 字段列表.

    Args:
        data: 80 字节二进制数据

    Returns:
        长度为 20 的 uint32_t 列表
    """
    assert len(data) >= CMD_HEADER_SIZE, f"数据不足, 需要 {CMD_HEADER_SIZE} 字节"
    return list(struct.unpack(CMD_HEADER_FORMAT, data[:CMD_HEADER_SIZE]))


def verify_header(header_fields: list) -> bool:
    """
    验证帧头魔数是否正确.

    Args:
        header_fields: 解包后的 header 字段列表

    Returns:
        True 表示有效
    """
    return (
        header_fields[IDX_HEADER_START] == TOOL_HEADER_START_N and
        header_fields[IDX_HEADER_CHECK1] == TOOL_HEADER_CHECK1_N and
        header_fields[IDX_HEADER_END] == TOOL_HEADER_END_N
    )


def make_yuv_frame_header(width: int, height: int, stride: int,
                          pipe_id: int = 0, chn_id: int = 0,
                          frame_id: int = 0, y_size: int = 0,
                          uv_size: int = 0) -> bytes:
    """
    构建 YUV 数据帧头 (用于发送端, 此处主要用于理解协议).

    Returns:
        80 字节的帧头
    """
    fields = [0] * 20
    fields[IDX_HEADER_START]  = TOOL_HEADER_START_N
    fields[IDX_HEADER_CHECK1] = TOOL_HEADER_CHECK1_N
    fields[IDX_HEADER_CHECK2] = TOOL_HEADER_CHECK2_N
    fields[IDX_HEADER_END]    = TOOL_HEADER_END_N
    fields[IDX_HEADER_CRC]    = 0
    fields[IDX_LEN]           = y_size + uv_size
    fields[IDX_TYPE]          = DataType.YUV_DATA
    fields[IDX_FORMAT]        = YuvType.YUVNV12
    fields[IDX_WIDTH]         = width
    fields[IDX_HEIGHT]        = height
    fields[IDX_STRIDE]        = stride
    fields[IDX_FRAME_PLANE]   = 0
    fields[IDX_CODE_TYPE]     = 0
    fields[IDX_PIPE_INFO]     = 0
    fields[IDX_PIPE_ID]       = pipe_id
    fields[IDX_CHN_ID]        = chn_id
    fields[IDX_FRAME_ID]      = frame_id
    fields[IDX_CHIP_VERSION]  = TOOL_VERSION
    fields[IDX_PLUGIN_ID]     = 0
    fields[IDX_RESERVED2]     = 0
    return pack_cmd_header(fields)


def make_net_send_cfg_packet(enable_yuv: bool = True,
                              enable_raw: bool = False,
                              pipe_line: int = 0,
                              channel_id: int = 0) -> bytes:
    """
    构建 NET_SEND_CFG 配置包，用于 PC 端发送给设备以启用视频流传输.

    该包由 80 字节帧头 + 24 字节 tranfer_info_t 组成。

    Args:
        enable_yuv: 是否启用 YUV 数据传输
        enable_raw: 是否启用 RAW 数据传输
        pipe_line:  pipeline 编号
        channel_id: 通道编号

    Returns:
        104 字节的完整配置包
    """
    # 1. 构建 cmd_header_new_t
    header_fields = [0] * 20
    header_fields[IDX_HEADER_START]  = TOOL_HEADER_START_N
    header_fields[IDX_HEADER_CHECK1] = TOOL_HEADER_CHECK1_N
    header_fields[IDX_HEADER_CHECK2] = TOOL_HEADER_CHECK2_N
    header_fields[IDX_HEADER_END]    = TOOL_HEADER_END_N
    header_fields[IDX_HEADER_CRC]    = 0
    header_fields[IDX_LEN]           = TRANSFER_INFO_SIZE  # 数据体长度
    header_fields[IDX_TYPE]          = DataType.NET_SEND_CFG
    header_fields[IDX_FORMAT]        = 0
    header_fields[IDX_CHIP_VERSION]  = TOOL_VERSION
    header_data = pack_cmd_header(header_fields)

    # 2. 构建 tranfer_info_t
    transfer_info = struct.pack(
        TRANSFER_INFO_FORMAT,
        1,                  # tcp_open = 1
        1 if enable_raw else 0,   # raw_enable
        0,                  # raw_serial_num
        1 if enable_yuv else 0,   # yuv_enable
        0,                  # yuv_serial_num
        0,                  # jepg_enable
        0,                  # video_enable
        0,                  # video_code
        0,                  # bit_stream
        0,                  # fream_interval
        pipe_line,          # pipe_line
        channel_id,         # channel_id
        0,                  # param_id
        0,                  # param_data
    )

    return header_data + transfer_info


def parse_frame_info(header_fields: list) -> dict:
    """
    从 header 字段中提取图像帧信息.

    Args:
        header_fields: 解包后的 20 字段列表

    Returns:
        包含帧信息的字典
    """
    return {
        'type':       header_fields[IDX_TYPE],
        'type_name':  DataType(header_fields[IDX_TYPE]).name if header_fields[IDX_TYPE] < len(DataType) else "UNKNOWN",
        'format':     header_fields[IDX_FORMAT],
        'width':      header_fields[IDX_WIDTH],
        'height':     header_fields[IDX_HEIGHT],
        'stride':     header_fields[IDX_STRIDE],
        'pipe_id':    header_fields[IDX_PIPE_ID],
        'chn_id':     header_fields[IDX_CHN_ID],
        'frame_id':   header_fields[IDX_FRAME_ID],
        'data_len':   header_fields[IDX_LEN],
        'chip_ver':   header_fields[IDX_CHIP_VERSION],
    }