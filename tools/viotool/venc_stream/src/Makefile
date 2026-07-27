# Makefile — J6B VENC Stream (CIM4 → H.264 → TCP)
#
# 编译前置条件: 已执行 bdall BAIC (生成所需的 .so)
#
# 编译步骤 (直接从 host 环境, 无需 Docker):
#   source build_tools/Compiler/qnx800/qnxsdp-env.sh
#   source envsetup.sh
#   cd tools/viotool/venc_stream/src && make
#
# 编译器: QNX SDP 自带的 qcc (自动处理 QNX sysroot)

TARGET = venc_stream
SRCS   = venc_stream.c
OBJS   = $(SRCS:.c=.o)

CC      = qcc
CFLAGS  = -Vgcc_ntoaarch64le -Wall -O2 -std=gnu99 -DCONFIG_ARCH_HOBOT_SOC_SIGIB

# ---- 头文件路径 ----
CFLAGS += -I$(HR_TOP_DIR)/install/usr/include
CFLAGS += -I$(HR_TOP_DIR)/tools/viotool/libhbplayer/include
CFLAGS += -I$(HR_TOP_DIR)/hbre/camsys/libcam/include
CFLAGS += -I$(HR_TOP_DIR)/hbre/camsys/libvio/include
CFLAGS += -I$(HR_TOP_DIR)/hbre/libhbmem/inc
CFLAGS += -I$(HR_TOP_DIR)/hbre/libmm/inc

# ---- 链接库 ----
SDK_LIB  = $(HR_TOP_DIR)/out/debug-qnx-64/target/deploy/rootfs/lib
HBPLAYER = $(HR_TOP_DIR)/tools/viotool/libhbplayer/aarch64/so.le
LDFLAGS  = -L$(SDK_LIB) -L$(HBPLAYER) -Wl,-rpath-link,$(SDK_LIB)
LDFLAGS += -lmultimedia -lhbplayer -lcamera -lvio -lvpf -lhbmem -lalog

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "  Build done: $(TARGET)"

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(TARGET) *.o
