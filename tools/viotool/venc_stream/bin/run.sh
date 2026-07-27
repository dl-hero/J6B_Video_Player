#!/bin/ksh
# ================================================================
# run.sh — J6B VENC Stream 一键启动脚本
#
# 部署路径: /app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
#
# 使用方法:
#   直接运行 (使用默认配置):
#     sh run.sh
#
#   指定 JSON 配置文件:
#     sh run.sh ./my_vpm.json ./my_cam.json
# ================================================================

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
BIN="$SCRIPT_DIR/venc_stream"

# 默认 JSON 配置文件路径 (与 camera_sample 共享)
# 对应 device 端 camera_sample 启动命令:
#   camera_sample -c <hb_j6dev.json> -v <vpm_config.json> -r 0 -t b22 -s 1
CFG_BASE="$SCRIPT_DIR/../../camera_sample/cfg/case_matrix/GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4"
VIO_CFG="${1:-$CFG_BASE/vpm_config.json}"
CAM_CFG="${2:-$CFG_BASE/hb_j6dev.json}"

if [ ! -f "$BIN" ]; then
    echo "ERROR: $BIN not found. Please build first."
    exit 1
fi
if [ ! -f "$VIO_CFG" ]; then
    echo "ERROR: VIO config not found: $VIO_CFG"
    exit 1
fi
if [ ! -f "$CAM_CFG" ]; then
    echo "ERROR: Camera config not found: $CAM_CFG"
    exit 1
fi

echo "=========================================="
echo "  J6B 4-Channel H.264 Encoder + TCP"
echo "=========================================="
echo "  VIO cfg: $VIO_CFG"
echo "  Cam cfg: $CAM_CFG"
echo "=========================================="
echo ""

exec "$BIN" -v "$VIO_CFG" -c "$CAM_CFG"
