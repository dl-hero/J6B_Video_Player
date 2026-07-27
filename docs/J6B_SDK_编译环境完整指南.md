# J6B SDK 编译环境 — 完整搭建与使用指南

> **最后更新:** 2026-07-25  
> **适用环境:** Ubuntu 22.04 x86_64 + Docker 29.1.3  
> **目标平台:** J6B (地平线 J6 芯片) + QNX 8.0  
> **OEM:** BAIC (北汽) / GAC (广汽)

---

## 目录

1. [快速开始（已有环境）](#1-快速开始已有环境)
2. [环境概览](#2-环境概览)
3. [初次环境搭建（完整流程）](#3-初次环境搭建完整流程)
4. [踩坑记录与解决方案（共 10 个问题）](#4-踩坑记录与解决方案)
5. [venc_stream 工具链（H.264 编码）](#5-venc_stream-工具链h264-编码)
6. [设备部署与调试](#6-设备部署与调试)
7. [增量编译与快捷命令](#7-增量编译与快捷命令)
8. [编译前检查清单](#8-编译前检查清单)
9. [故障快速排查表](#9-故障快速排查表)
10. [一键编译脚本](#10-一键编译脚本)
11. [关键经验总结](#11-关键经验总结)

---

## 1. 快速开始（已有环境）

如果你的环境已经按照本指南搭建完毕，重启后只需 **4 行命令** 即可恢复编译：

```bash
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
source build_tools/Compiler/qnx800/qnxsdp-env.sh
source envsetup.sh
bdall BAIC
```

> 前提：Docker 服务运行中（默认开机自启）、`.config` 已存在、镜像已修复。

---

## 2. 环境概览

### 2.1 路径一览

| 项目 | 路径 | 说明 |
|------|------|------|
| **SDK 源码目录** | `/media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS` | J6B 完整 SDK，含设备端代码 |
| **Docker 构建镜像** | `/media/jinnuo/work/SourceCode/HR-J6B/build_env/build_docker.tar` | ~2GB，离线镜像文件 |
| **编译产物 (img)** | `<SDK>/out/debug-qnx-64/target/product/img_packages/` | 约 947MB，含 flash_all.sh |
| **PC 端项目** | `/media/jinnuo/work/SourceCode/J6B_Video_Player` | TCP 接收 + GUI/CLI 显示 |
| **设备端工具** | `<SDK>/tools/viotool/venc_stream/` | VPU H.264 编码 + TCP 输出 |
| **设备调试 IP** | `192.168.0.140` | SSH 免密登录 |

### 2.2 两个项目的关系

```
PC 端 (J6B_Video_Player)                    J6B 设备端 (BaseSW_J6B_BS)
─────────────────────────                    ──────────────────────────
hb_video_gui.py / hb_video_cli.py  ──TCP──▶  hb_tool_server (libhbplayer)
hb_video_client.py (recv + decode)           venc_stream (VPU H.264 编码)
hb_protocol.py (协议层)                      camera_sample (NV12 原始流)
```

修改设备端代码（如 `venc_stream.c`）后，需在 SDK 目录编译并部署到设备。

### 2.3 Docker 镜像信息

| 属性 | 值 |
|------|------|
| 镜像名 | `docker.hobot.cc/systemsoft/devenv/debian-12:latest` |
| 基础系统 | Debian 12 |
| 预装工具 | aarch64 交叉编译器 + QNX 8.0 SDP |
| Python venv | `/root/.local/build-python3-env` (Python 3.11) |
| 已修复项 | 预创建 jinnuo 用户 / `/root` 权限 710 / progressbar + cryptography |

---

## 3. 初次环境搭建（完整流程）

### 3.1 一次性操作（仅初次需要）

#### Step 1: 安装 Docker 并配置权限

```bash
# 将用户加入 docker 组（免 sudo 使用 docker）
sudo usermod -aG docker jinnuo
# 重新登录系统使权限生效（或执行 newgrp docker）
```

验证：
```bash
docker images   # 不加 sudo 能正常输出即为成功
```

#### Step 2: 加载 Docker 镜像

```bash
# 加载离线镜像（约 2 分钟）
docker load -i /media/jinnuo/work/SourceCode/HR-J6B/build_env/build_docker.tar

# 添加构建脚本期望的 tag
docker tag systemsoft/devenv/debian-12:latest \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest
```

验证：
```bash
docker images | grep debian-12
# 预期输出两个 tag 指向同一镜像 ID
```

#### Step 3: 修复 Docker 镜像（预创建用户 + 补充依赖）

```bash
# 启动临时容器
docker run --name init_img --entrypoint "" -dt \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest /bin/bash

# 预创建 jinnuo 用户 + 补充 Python 依赖
docker exec -t init_img /bin/bash -c "
  chmod 700 /root && \
  groupadd -g 1000 jinnuo 2>/dev/null
  useradd -u 1000 -g 1000 -d /home/jinnuo -s /bin/bash jinnuo 2>/dev/null
  echo 'jinnuo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
  source /root/.local/build-python3-env/bin/activate && \
  pip install progressbar==2.5 cryptography==42.0.8
  chmod 710 /root
"

# 保存修改
docker commit init_img docker.hobot.cc/systemsoft/devenv/debian-12:latest
docker rm -f init_img
```

> **为什么需要这一步？** 容器的 entrypoint 脚本（`/etc/init.d/hobot_init.sh`）通过环境变量动态创建用户，但 `chmod 755 /root` 会破坏 PAM 环境导致创建失败。预创建用户到镜像中可彻底绕过此问题。详见 [问题 5](#问题-5python-模块-progressbar-缺失) 和 [问题 6](#问题-6容器-entrypoint-创建用户失败)。

#### Step 4: 修复源码目录权限

```bash
# 确保 SDK 源码目录中没有 root 所有的文件
sudo chown -R jinnuo:jinnuo /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
```

验证：
```bash
find /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS -user root ! -type l 2>/dev/null | head -5
# 预期无输出（或仅有 out.bak 等不需要的旧文件）
```

#### Step 5: 生成 .config 并编译

```bash
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS

# 设置 QNX 编译器环境
source build_tools/Compiler/qnx800/qnxsdp-env.sh

# 生成 .config（选择 #1: j6b_debug_defconfig_BAIC）
echo "1" | make lunch

# 加载构建环境
source envsetup.sh

# 全量编译
bdall BAIC
```

编译成功后输出：
```
Complete all compilation tasks (145 of 145)100%
Running build_img succeeded.
build all OK !!!
```

### 3.2 编译产物

产物位于 `out/debug-qnx-64/target/product/img_packages/`，总计约 **947 MB**：

| 镜像文件 | 大小 | 说明 |
|----------|------|------|
| `basesystem.img` | 20 MB | QNX 基础系统 |
| `boot.img` | 60 MB | 启动镜像 (kernel + procnto) |
| `app.img` | 1.5 GB | 应用分区镜像 |
| `bl31.img` | 556 KB | ARM Trusted Firmware |
| `gpt_main.img` | 17 KB | GPT 分区表 |
| `HSM_FW.img` | 288 KB | HSM 安全固件 |
| `fpt.img` / `IVF.img` / `keyimage.img` | — | OTA / 安全相关 |
| `flash_all.sh` | 13 KB | 一键烧录脚本 |

---

## 4. 踩坑记录与解决方案

> 以下按实际遇到的时间顺序排列，共 10 个问题。每个问题都附有**现象、原因、解决方案**。

### 问题 1：`out/` 目录归属为 root，`.config` 不存在

**现象：**
```
NO_CONFIG_FILE
```

**原因：** 之前在其他环境（可能是 root 用户）编译过，`out/` 目录及其内容所有者均为 root，且 `.config` 中的 QNX 路径是另一台服务器的 `/workspace/` 路径。

**解决：**
```bash
mv out out.bak        # 重命名旧目录
sudo rm -rf out.bak   # 后续清理（可选）
```

---

### 问题 2：Docker 权限不足

**现象：**
```
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

**原因：** 用户 `jinnuo` 不在 `docker` 用户组。

**解决：**
```bash
sudo usermod -aG docker jinnuo
# 重新登录系统使权限生效
```

> **关键教训：** `bdall` 命令内部调用的是 `docker`（不带 `sudo`），所以即使 `sudo docker` 能用，`bdall` 也不行。必须让当前用户免密码使用 docker。

---

### 问题 3：Docker 镜像 tag 不匹配

**现象：**
```
Docker image: docker.hobot.cc/systemsoft/devenv/debian-12:latest does not exist!
```

**原因：** `envsetup.sh` 中硬编码了 `DOCKER_IMG="docker.hobot.cc/systemsoft/devenv/debian-12:latest"`，但 `docker load` 加载后镜像名称为 `systemsoft/devenv/debian-12:latest`。

**解决：**
```bash
docker tag systemsoft/devenv/debian-12:latest docker.hobot.cc/systemsoft/devenv/debian-12:latest
```

---

### 问题 4：root 所有的源代码文件导致权限拒绝

**现象（多次出现）：**
```
Permission denied: '.../secure_keys_files/keyimage/header_keyimage_aes128_ohp.key'
Permission denied: '.../install/etc/version'
```

**原因：** 之前 root 编译在源码目录中留下了 root 所有的文件（分布在 `secure_keys_files/`、`install/`、`hbre/`、`external/` 等多个目录）。

**解决（一次性修复整个项目）：**
```bash
sudo chown -R jinnuo:jinnuo /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
```

> **关键教训：** 不是个别文件的问题，而是分散在多个目录的 root 文件。不要逐个目录修复，一次性 `chown -R` 整个项目目录。

---

### 问题 5：Python 模块 `progressbar` 缺失

**现象：**
```
ModuleNotFoundError: No module named 'progressbar'
```

**原因：** Docker 镜像内 `/root/.local/build-python3-env` 缺少 `progressbar` 包。编译在容器内以 jinnuo 用户执行，但 venv 在 `/root/` 下。

**踩坑过程（多轮迭代）：**

| 尝试 | 方法 | 结果 | 教训 |
|------|------|------|------|
| 1 | 在宿主机安装 progressbar | ❌ | 编译在容器内运行，宿主机安装无效 |
| 2 | `docker commit` 安装到镜像 venv | ❌ | 容器 entrypoint 接管控制权，难以调试 |
| 3 | `chmod 755 /root` 让 jinnuo 访问 | ❌ | **破坏了 PAM 环境**，导致后续更多问题 |
| 4 | 预创建 jinnuo 用户 + `chmod 710 /root` | ✅ | 最终方案 |

**最终解决方案：**
```bash
docker run --name prebuild --entrypoint "" -dt \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest /bin/bash

docker exec -t prebuild /bin/bash -c "
  chmod 700 /root && \
  groupadd -g 1000 jinnuo 2>/dev/null
  useradd -u 1000 -g 1000 -d /home/jinnuo -s /bin/bash jinnuo 2>/dev/null
  echo 'jinnuo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
"

# 确保 venv 依赖完整
docker exec -t prebuild /bin/bash -c "
  source /root/.local/build-python3-env/bin/activate && \
  pip install progressbar==2.5 cryptography==42.0.8
"

# 修复 /root 权限让 jinnuo 组可读（注意是 710，不是 755！）
docker exec -t prebuild chmod 710 /root

docker commit prebuild docker.hobot.cc/systemsoft/devenv/debian-12:latest
docker rm -f prebuild
```

---

### 问题 6：容器 entrypoint 创建用户失败

**现象：**
```
+ docker exec -t jinnuo_BaseSW_J6B_BS /bin/bash -c \
  'while [ true ]; do cat /etc/passwd | grep jinnuo > /dev/null && break; done'
# 无限等待...
```
或：
```
Error response from daemon: unable to find user jinnuo: no matching entries in passwd file
```

**原因：** 容器 entrypoint 脚本 `/etc/init.d/hobot_init.sh` 内容为：
```bash
#!/bin/bash
[ -z "$USER_NAME" -o -z "$GROUP_ID" -o -z "$USER_ID" ] && exec su - root
groupadd -g $GROUP_ID $USER_NAME
useradd -u $USER_ID -g $GROUP_ID -s /bin/bash $USER_NAME
exec su - $USER_NAME
```
`chmod 755 /root` 操作破坏了 PAM 认证环境，导致 `groupadd`/`useradd` 执行异常。

**解决：** 在问题 5 的方案中已包含预创建用户。entrypoint 检测到用户已存在时会直接 `su` 跳过创建步骤。

> **关键教训：** **绝对不要用 `chmod 755 /root`**！这会破坏容器的 PAM 环境。正确做法是用 `chmod 710`（让同组用户可访问）。

---

### 问题 7：宿主机 Python venv 损坏

**现象：**
```
/home/jinnuo/.local/build-python3-env/bin/python3: No module named pip
```

**原因：** 之前的操作导致宿主机的 Python 虚拟环境 pip 损坏。

**解决：**
```bash
rm -rf /home/jinnuo/.local/build-python3-env
python3 -m venv /home/jinnuo/.local/build-python3-env
source /home/jinnuo/.local/build-python3-env/bin/activate
pip install -r /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS/build_tools/hobot_tools/requirements.txt
```

---

### 问题 8：容器内 Python 3.11 venv 找不到 cryptography==42.0.8

**现象：**
```
ERROR: Could not find a version that satisfies the requirement cryptography==42.0.8
```

**原因：** 容器内 jinnuo 用户重建 venv 时，pip 镜像源（清华源）对于 Python 3.11 没有该版本的预编译包。

**解决：** 使用镜像内已有的 root venv（`/root/.local/build-python3-env`），在问题 5 中已将缺失的包补充安装。

> **关键教训：** 宿主机的 Python 3.10 venv 与容器内的 Python 3.11 venv **不能混用**。编译脚本 `envsetup.sh` 在检测到 Docker 环境时会硬编码使用 `/root/.local/build-python3-env`。

---

### 问题 9：`select_OEM` 脚本的兼容性警告（非致命）

**现象：**
```
[: GAC: unary operator expected
[: BAIC: unary operator expected
OEM not specified:
Usage: bdall [GAC|BAIC|SAIC]
OEM: BAIC
```

**原因：** `build.sh` 中 `bdall` 不带参数时 `$2` 为空，`select_OEM` 的 `[ "GAC" == $1 ]` 比较因 `$1` 为空导致 shell 语法错误。但 OEM 值实际从 `.config` 文件（`export OEM="BAIC"`）中读取。

**解决：** 这是源码中的脚本健壮性问题，属**非致命警告**。带参数执行 `bdall BAIC` 即可消除。

---

### 问题 10：`make j6b_debug_defconfig_BAIC` 无法匹配

**现象：**
```
make: *** No rule to make target 'j6b_debug_defconfig_BAIC'. Stop.
```

**原因：** Makefile 中 `%defconfig` 模式规则只匹配以 `defconfig` 结尾的目标名，`_BAIC` 后缀导致不匹配。

**解决：** 使用交互式 `make lunch`，通过管道输入编号自动选择：
```bash
echo "1" | make lunch
```

---

## 5. venc_stream 工具链（H.264 编码）

### 5.1 背景

`venc_stream` 是 J6B 设备端的新增工具，实现 CIM4 四路摄像头 DDR 输出 → VPU 硬件 H.264 编码 → TCP 发送到 PC 端。

### 5.2 关键配置（GAC 平台）

| 参数 | 值 | 来源 |
|------|------|------|
| Pipeline ID | 7, 8, 9, 10 | `vpm_config.json` pipeline7-10 |
| CAM Port | 7, 8, 9, 10 | `hb_j6dev.json` port_7-10 |
| 分辨率 | 1696×1168 | SC361AT 传感器 extra_mode=10 |
| 帧率 | 30fps | |
| MIPI 输入格式 | YUV422_8bit (datatype 0x1E) | CIM DDR 输出 format=30 |
| 编码格式 | H.264 CBR 4Mbps/路 | VPU 硬件编码 |
| 配置文件路径 | `case_matrix/GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4/` | GAC init.sh 中的配置 |

### 5.3 代码同步工作流

当修改 PC 端项目中的 venc_stream 代码后，按以下步骤同步到 SDK 并编译：

```bash
# 1. 确认 PC 端代码无误
ls /media/jinnuo/work/SourceCode/J6B_Video_Player/tools/viotool/venc_stream/src/venc_stream.c
ls /media/jinnuo/work/SourceCode/J6B_Video_Player/tools/viotool/venc_stream/bin/run.sh

# 2. 同步到 SDK 目录
SDK_DIR="/media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS"
PC_DIR="/media/jinnuo/work/SourceCode/J6B_Video_Player"
mkdir -p "$SDK_DIR/tools/viotool/venc_stream/src"
mkdir -p "$SDK_DIR/tools/viotool/venc_stream/bin"
cp "$PC_DIR/tools/viotool/venc_stream/src/venc_stream.c" "$SDK_DIR/tools/viotool/venc_stream/src/"
cp "$PC_DIR/tools/viotool/venc_stream/src/Makefile" "$SDK_DIR/tools/viotool/venc_stream/src/"
cp "$PC_DIR/tools/viotool/venc_stream/bin/run.sh" "$SDK_DIR/tools/viotool/venc_stream/bin/"

# 3. 编译
cd "$SDK_DIR"
source build_tools/Compiler/qnx800/qnxsdp-env.sh
source envsetup.sh
bdall BAIC
```

### 5.4 venc_stream 代码审核要点（曾踩过的坑）

在修改 venc_stream.c 时，需特别注意以下几点（从实际代码审核中发现）：

| # | 检查项 | 错误示例 | 正确写法 |
|---|--------|---------|---------|
| 1 | SDK 结构体字段名 | `bitrate` | `bit_rate`（`mc_h264_cbr_params_t` 实际字段） |
| 2 | buffer_size 字段 | `img_addr.buffer_size` | `img_info.size[0] + img_info.size[1]`（`address_info_t` 无此字段） |
| 3 | Pipeline ID 与 CAM Port | 共用一个数组 | 分别定义 `PIPE_IDS[]` 和 `CAM_PORTS[]` |
| 4 | run.sh 配置路径 | `4V_4xISX031_RX4` | `GAC_BYPASS_TEST_4V_SC361ATSTD_1696x1168_RSEMI_RX4` |

---

## 6. 设备部署与调试

### 6.1 设备信息

| 项目 | 值 |
|------|------|
| 设备型号 | J6B_GAC_AY5-TM |
| 调试 IP | `192.168.0.140` |
| SSH 登录 | `ssh root@192.168.0.140`（免密） |
| 系统 | QNX 8.0 |
| 应用目录 | `/app/sample/S83_Sample/S83E04_Module/` |

### 6.2 部署编译产物到设备

```bash
# 方法 1：通过 SSH + scp 部署单个程序
scp /path/to/venc_stream root@192.168.0.140:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
scp /path/to/run.sh root@192.168.0.140:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/

# 方法 2：烧录完整镜像（使用 flash_all.sh）
# 请参考 J6B 设备烧录手册
```

### 6.3 设备端启动

```bash
# SSH 登录设备
ssh root@192.168.0.140

# 方案 A: camera_sample — NV12 原始视频流（低延迟，高带宽）
camera_sample -s 1 -S 0

# 方案 B: venc_stream — H.264 压缩视频流（低带宽，轻微延迟）
cd /app/sample/S83_Sample/S83E04_Module/venc_stream/bin
sh run.sh
```

### 6.4 PC 端连接

```bash
# GUI 模式
python hb_video_gui.py

# CLI 模式
python hb_video_cli.py 192.168.0.140

# CLI 多路网格显示（指定通道）
python hb_video_cli.py 192.168.0.140 --pipe 0
```

### 6.5 已知限制

- **连接限制：** 设备端 `hb_tool_server` 在每次设备启动后**仅接受一次 TCP 连接**。连接断开后端口即关闭，需要重启设备才能再次连接。
- **重启设备：** `ssh root@<IP> "reboot"`

---

## 7. 增量编译与快捷命令

### 7.1 代码小幅修改后的增量编译

如果只修改了少数模块，不需要全量 `bdall`（全量编译约 30-60 分钟）：

```bash
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
source envsetup.sh

# 编译单个模块（例如只改了 hbre 下的 otaupdate）
bdm otaupdate

# 编译内核模块
bdkm hobot-driver

# 重新打包镜像（不重新编译模块）
build.sh docker disk BAIC
```

### 7.2 快捷命令速查

| 命令 | 等价 | 用途 |
|------|------|------|
| `bdall <OEM>` | `build.sh docker all <OEM>` | Docker 内全量编译 + 生成镜像 |
| `bdm <模块>` | `build.sh docker module <模块>` | Docker 内编译单个模块 |
| `bdkm <模块>` | `build.sh docker k_modules <模块>` | Docker 内编译内核模块 |
| `bddisk <OEM>` | `build.sh docker disk <OEM>` | Docker 内只生成镜像（不重新编译） |
| `ball <OEM>` | `build.sh all <OEM>` | 本地全量编译（不使用 Docker） |

### 7.3 切换 OEM 或构建模式

```bash
# 交互式重新选择配置
make lunch
# 选择新的 defconfig（例如 #3: j6b_debug_defconfig_GAC）

# 重新加载环境
source envsetup.sh

# 编译时指定对应的 OEM
bdall GAC
```

---

## 8. 编译前检查清单

执行 `bdall` 前，逐项确认：

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| Docker 可用 | `docker images \| grep debian-12` | 两个 tag 均出现 |
| 在 SDK 目录 | `pwd` | `/media/jinnuo/.../BaseSW_J6B_BS` |
| `.config` 存在 | `ls out/.config` | 文件存在 |
| `.config` 中 QNX 路径正确 | `grep QNX_HOST out/.config` | 路径以 `HR_TOP_DIR` 开头 |
| 源码无 root 文件 | `find . -user root ! -type l 2>/dev/null \| head -5` | 无输出 |

---

## 9. 故障快速排查表

| 现象 | 大概率原因 | 快速修复 |
|------|-----------|----------|
| `Permission denied` / `ModuleNotFoundError` | Docker 镜像未修复 | 重新执行 [3.1 节 Step 3](#step-3-修复-docker-镜像预创建用户--补充依赖) |
| `Please run make menuconfig` | `.config` 不存在 | 执行 `echo "1" \| make lunch` |
| `Docker image does not exist` | 镜像 tag 丢失 | `docker tag systemsoft/devenv/debian-12:latest docker.hobot.cc/...` |
| `Python virtual environment is NOT properly set up` | 宿主机 venv 损坏 | `rm -rf ~/.local/build-python3-env` 后重新 `source envsetup.sh` |
| docker 权限错误 | 重启后 docker 组未生效 | `newgrp docker` 或重新登录 |
| 容器无限等待 `grep jinnuo` | entrypoint 创建用户失败 | 确认镜像已预创建用户（Step 3），清理旧容器 `docker rm -f jinnuo_BaseSW_J6B_BS` |
| `No module named 'pip'` | 宿主机 venv 损坏 | 见 [问题 7](#问题-7宿主机-python-venv-损坏) |
| `Could not find cryptography==42.0.8` | 容器内重建 venv 时镜像源问题 | 使用 `/root/.local/build-python3-env`（不要重建） |

---

## 10. 一键编译脚本

将以下内容保存为 `~/bin/j6b_build.sh`：

```bash
#!/bin/bash
# J6B 快速编译脚本
# 用法: j6b_build.sh [OEM]  (默认 BAIC)

OEM="${1:-BAIC}"
SDK_DIR="/media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS"

cd "$SDK_DIR" || exit 1
source build_tools/Compiler/qnx800/qnxsdp-env.sh
source envsetup.sh
bdall "$OEM"
```

```bash
chmod +x ~/bin/j6b_build.sh

# 使用:
j6b_build.sh        # 默认 BAIC
j6b_build.sh GAC    # 编译广汽版本
```

---

## 11. 关键经验总结

1. **编译必须用 `source envsetup.sh` 而非直接执行**，它会导出大量环境变量和 Shell 函数（`bdall`、`bdm` 等）。

2. **Docker 容器内的 Python venv 路径是硬编码的**（`/root/.local/build-python3-env`），非 root 用户需要 `/root` 目录的读+执行权限。

3. **绝对不要用 `chmod 755 /root`**！这会破坏容器的 PAM 环境，导致 entrypoint 脚本的 `groupadd`/`useradd`/`su` 全部异常。正确做法是 `chmod 710`。

4. **源码目录中不能有 root 所有的文件**，Docker 内 jinnuo 用户编译时需要写入权限。一次性 `chown -R` 整个项目目录。

5. **宿主机的 Python venv 和容器内版本可能不同**（宿主机 Python 3.10 vs 容器 Python 3.11）。宿主机的 venv 仅用于宿主机脚本（如 `generate_oem_key`），编译时使用容器内的 venv。

6. **Docker 权限问题不会自动消失**，`sudo docker` 能用不代表 `bdall` 能用。必须让当前用户加入 `docker` 组并重新登录。

7. **容器的 entrypoint 机制不可靠**，预创建用户到镜像中是最稳定的方案。

8. **`venc_stream.c` 的字段名要与 SDK 头文件严格一致**（如 `bit_rate` 不是 `bitrate`），结构体中不存在的字段（如 `address_info_t.buffer_size`）需要从其他字段获取。

9. **Pipeline ID 和 CAM Port 是两个独立概念**，即使数值相同也应分开定义数组。

10. **设备端每次启动仅接受一次 TCP 连接**，调试时避免频繁断开/重连，断开后需重启设备。
