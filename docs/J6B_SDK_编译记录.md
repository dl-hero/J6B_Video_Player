# J6B SDK 编译记录

> **编译目标:** J6B QNX 8.0 (BAIC Debug)  
> **编译日期:** 2026-07-23  
> **编译环境:** Ubuntu 22.04 + Docker 29.1.3  
> **编译结果:** ✅ 成功，生成 947MB img 镜像文件  

---

## 一、环境概要

| 项目 | 信息 |
|------|------|
| 主机 | Ubuntu 22.04, x86_64 |
| 用户 | jinnuo (uid=1000) |
| Docker | v29.1.3 |
| SDK 路径 | `/media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS` |
| Docker 镜像 | `build_docker.tar` (2GB) → `docker.hobot.cc/systemsoft/devenv/debian-12:latest` |
| 目标芯片 | J6B (Horizon Robotics) |
| 目标系统 | QNX 8.0 |
| OEM | BAIC (北汽) |
| 构建模式 | debug |

---

## 二、编译流程概览

```
source qnxsdp-env.sh     → 设置 QNX 编译器环境变量
make lunch               → 选择 defconfig (j6b_debug_defconfig_BAIC)
source envsetup.sh       → 加载构建环境 + 快捷命令
bdall BAIC               → Docker 容器内全量编译
  ├─ paral_build.py build all   (145 任务并行编译)
  ├─ build_img all              (生成分区镜像)
  ├─ build_symbols              (打包调试符号)
  └─ build_check                (验证产物)
```

---

## 三、问题排查全记录

### 问题 1：`out/` 目录归属为 root，且 `.config` 不存在

**现象:**
```
NO_CONFIG_FILE
```

**原因:** 之前在其他环境（可能是 root 用户）编译过，`out/` 目录及其内容所有者均为 root，且 `.config` 中的 QNX 路径是另一台服务器的 `/workspace/` 路径。

**解决:**
```bash
# 重命名旧 out 目录（mv 不需要 root 权限）
mv out out.bak

# 后续可清理旧目录
sudo rm -rf out.bak
```

---

### 问题 2：Docker 权限不足

**现象:**
```
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

**原因:** 用户 `jinnuo` 不在 `docker` 用户组。

**解决:**
```bash
sudo usermod -aG docker jinnuo
# 重新登录系统使权限生效
```

验证: `docker images` 不加 sudo 正常输出即为成功。

---

### 问题 3：Docker 镜像 tag 不匹配

**现象:**
```
Docker image: docker.hobot.cc/systemsoft/devenv/debian-12:latest does not exist!
```

**原因:** `envsetup.sh` 中硬编码了 `DOCKER_IMG="docker.hobot.cc/systemsoft/devenv/debian-12:latest"`，但 `docker load` 加载后镜像名称为 `systemsoft/devenv/debian-12:latest`。

**解决:**
```bash
# 加载镜像
docker load -i /media/jinnuo/work/SourceCode/HR-J6B/build_env/build_docker.tar

# 添加构建脚本期望的 tag
docker tag systemsoft/devenv/debian-12:latest docker.hobot.cc/systemsoft/devenv/debian-12:latest
```

---

### 问题 4：root 所有的源代码文件导致权限拒绝

**现象（第一次）:**
```
Permission denied: '.../secure_keys_files/keyimage/header_keyimage_aes128_ohp.key'
```

**现象（第二次）:**
```
/media/jinnuo/.../install/etc/version: Permission denied
```

**原因:** 之前 root 编译在源码目录中留下了 root 所有的文件（`secure_keys_files/`、`install/`、`hbre/`、`external/` 等多个目录）。

**解决:**
```bash
sudo chown -R jinnuo:jinnuo /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
```

---

### 问题 5：Python 模块 `progressbar` 缺失

**现象:**
```
ModuleNotFoundError: No module named 'progressbar'
```

**原因:** Docker 镜像内 `/root/.local/build-python3-env` 缺少 `progressbar` 包。编译在容器内以 jinnuo 用户执行，但 venv 在 `/root/` 下。

**解决过程（多轮迭代）:**

| 尝试 | 方法 | 结果 |
|------|------|------|
| 1 | 在宿主机安装 progressbar | ❌ 编译在容器内运行，宿主机安装无效 |
| 2 | `docker commit` 安装到镜像 venv | ❌ 容器 entrypoint 接管控制权，难以调试 |
| 3 | 发现 `/root` 权限为 700，jinnuo 无法访问 | ❌ `chmod 755 /root` 破坏了 PAM 环境 |
| 4 | 预创建 jinnuo 用户到镜像 + 修复 `/root` 权限 | ✅ 最终方案 |

**最终解决方案:**
```bash
# 在镜像中预创建 jinnuo 用户
docker run --name prebuild --entrypoint "" -dt \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest /bin/bash

docker exec -t prebuild /bin/bash -c "
  chmod 700 /root && \
  groupadd -g 1000 jinnuo 2>/dev/null
  useradd -u 1000 -g 1000 -d /home/jinnuo -s /bin/bash jinnuo 2>/dev/null
  echo 'jinnuo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
"

# 确保 venv 完整
docker exec -t prebuild /bin/bash -c "
  source /root/.local/build-python3-env/bin/activate && \
  pip install progressbar==2.5 cryptography==42.0.8
"

# 修复 /root 权限让 jinnuo 组可读
docker exec -t prebuild chmod 710 /root

docker commit prebuild docker.hobot.cc/systemsoft/devenv/debian-12:latest
docker rm -f prebuild
```

---

### 问题 6：容器 entrypoint 创建用户失败

**现象:**
```
+ docker exec -t jinnuo_BaseSW_J6B_BS /bin/bash -c \
  'while [ true ]; do cat /etc/passwd | grep jinnuo > /dev/null && break; done'
# 无限等待...
```
或：
```
Error response from daemon: unable to find user jinnuo: no matching entries in passwd file
```

**原因:** 容器 entrypoint 脚本 `/etc/init.d/hobot_init.sh` 通过环境变量动态创建用户，但 `chmod 755 /root` 操作破坏了 PAM 认证环境，导致 `groupadd`/`useradd` 执行异常。

**解决:** 问题 5 的方案中已包含预创建用户，entrypoint 检测到用户已存在时会直接 `su` 跳过创建步骤。

---

### 问题 7：宿主机 Python venv 损坏

**现象:**
```
/home/jinnuo/.local/build-python3-env/bin/python3: No module named pip
```

**原因:** 之前的操作导致宿主机的 Python 虚拟环境 pip 损坏。

**解决:**
```bash
rm -rf /home/jinnuo/.local/build-python3-env
python3 -m venv /home/jinnuo/.local/build-python3-env
source /home/jinnuo/.local/build-python3-env/bin/activate
pip install -r /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS/build_tools/hobot_tools/requirements.txt
```

---

### 问题 8：容器内 Python 3.11 venv 找不到 cryptography==42.0.8

**现象:**
```
ERROR: Could not find a version that satisfies the requirement cryptography==42.0.8
```

**原因:** 容器内 jinnuo 用户重建 venv 时，pip 镜像源（清华源）对于 Python 3.11 没有该版本的预编译包。

**解决:** 使用镜像内已有的 root venv（`/root/.local/build-python3-env`），在问题 5 中已将缺失的包补充安装。

---

### 问题 9：`select_OEM` 脚本的兼容性警告（非致命）

**现象:**
```
[: GAC: unary operator expected
[: BAIC: unary operator expected
OEM not specified:
Usage: bdall [GAC|BAIC|SAIC]
OEM: BAIC
```

**原因:** `build.sh` 中 `bdall` 不带参数时 `$2` 为空，`select_OEM` 的 `[ "GAC" == $1 ]` 比较因 `$1` 为空导致 shell 语法错误。但 OEM 值实际从 `.config` 文件（`export OEM="BAIC"`）中读取，不影响最终编译。

**说明:** 这是源码中的脚本健壮性问题，属非致命警告。带参数执行 `bdall BAIC` 即可消除。

---

### 问题 10：`make CHIP_DIR=j6 j6b_debug_defconfig_BAIC` 无法匹配

**现象:**
```
make: *** No rule to make target 'j6b_debug_defconfig_BAIC'. Stop.
```

**原因:** Makefile 中 `%defconfig` 模式规则只匹配以 `defconfig` 结尾的目标名，`_BAIC` 后缀导致不匹配。

**解决:** 使用交互式 `make lunch`，通过管道输入编号自动选择：
```bash
echo "1" | make lunch
```

---

## 四、最终成功的编译命令序列

```bash
# 1. 进入编译目录
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS

# 2. 设置 QNX 编译器环境
source build_tools/Compiler/qnx800/qnxsdp-env.sh

# 3. 选择构建配置 (选 #1: j6b_debug_defconfig_BAIC)
echo "1" | make lunch

# 4. 加载构建环境
source envsetup.sh

# 5. 执行全量编译
bdall BAIC
```

---

## 五、编译产物

产物位于 `out/debug-qnx-64/target/product/img_packages/`，总计约 **947 MB**：

| 镜像文件 | 大小 | 说明 |
|----------|------|------|
| `basesystem.img` | 20 MB | QNX 基础系统镜像 |
| `boot.img` | 60 MB | 启动镜像 (kernel + procnto) |
| `app.img` | 1.5 GB | 应用分区镜像 |
| `bl31.img` | 556 KB | ARM Trusted Firmware |
| `gpt_main.img` | 17 KB | GPT 分区表 |
| `HSM_FW.img` | 288 KB | HSM 安全固件 |
| `fpt.img` / `IVF.img` / `keyimage.img` | — | OTA / 安全相关镜像 |
| `flash_all.sh` | 13 KB | 一键烧录脚本 |

---

## 六、Docker 镜像修改记录

原始镜像经过以下修改后保存为最终可用的编译镜像：

| 修改项 | 目的 |
|--------|------|
| 预创建 jinnuo 用户 (uid=1000) | 绕过 entrypoint 用户创建的不稳定性 |
| `chmod 710 /root` | 允许 jinnuo 组访问 venv |
| `pip install progressbar==2.5` | 补充缺失的 Python 依赖 |
| `pip install cryptography==42.0.8` | 确保加密库版本匹配 |

---

## 七、关键经验

1. **编译必须用 `source envsetup.sh` 而非直接执行**，它会导出大量环境变量和 Shell 函数。
2. **Docker 容器内的 Python venv 路径是硬编码的**（`/root/.local/build-python3-env`），非 root 用户需要 `/root` 目录的读+执行权限。
3. **不要用 `chmod 755 /root`**，这会破坏容器的 PAM 环境，用 `chmod 710` 即可。
4. **源码目录中不能有 root 所有的文件**，Docker 内 jinnuo 用户编译时需要写入权限。
5. **宿主机的 Python venv 和容器内版本可能不同**（宿主机 Python 3.10 vs 容器 Python 3.11），宿主机的 venv 仅用于宿主机脚本，编译时使用容器内的 venv。

---

## 八、全新代码目录重新设定编译环境

当以下场景发生时，需要重新设定编译环境：
- 从另一台机器 clone / 拷贝了全新的 SDK 代码
- `out/` 目录被清空或不存在
- 更换了不同的 OEM 或芯片型号

### 8.1 初始化清单

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 加载 Docker 镜像 | 一次性操作，镜像已在本地则跳过 |
| 2 | 修复源码文件权限 | 全新目录通常已是正确权限，仅当有 root 文件时需要 |
| 3 | 生成 `.config` | 通过 `make lunch` 创建 |
| 4 | 设置环境并编译 | `source envsetup.sh` + `bdall <OEM>` |

### 8.2 完整命令序列

```bash
# ========== 一次性操作（仅初次需要）==========

# 1. 加载 Docker 镜像（约 2 分钟）
docker load -i /media/jinnuo/work/SourceCode/HR-J6B/build_env/build_docker.tar

# 2. 添加构建脚本期望的 tag
docker tag systemsoft/devenv/debian-12:latest \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest

# 3. 修复 Docker 镜像（预创建用户 + venv 依赖）—— 仅需执行一次
docker run --name init_img --entrypoint "" -dt \
  docker.hobot.cc/systemsoft/devenv/debian-12:latest /bin/bash
docker exec -t init_img /bin/bash -c "
  chmod 700 /root && \
  groupadd -g $(id -u) $(whoami) 2>/dev/null
  useradd -u $(id -u) -g $(id -u) -d /home/$(whoami) -s /bin/bash $(whoami) 2>/dev/null
  echo '$(whoami) ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
  source /root/.local/build-python3-env/bin/activate && \
  pip install progressbar==2.5 cryptography==42.0.8
  chmod 710 /root
"
docker commit init_img docker.hobot.cc/systemsoft/devenv/debian-12:latest
docker rm -f init_img

# 4. 修复源码目录归属（如有 root 文件）
sudo chown -R $(whoami):$(whoami) <SDK路径>

# ========== 每次编译都需要 ==========

# 5. 进入 SDK 目录
cd <SDK路径>

# 6. 设置 QNX 编译器环境
source build_tools/Compiler/qnx800/qnxsdp-env.sh

# 7. 生成 .config（选择对应的 defconfig）
echo "1" | make lunch

# 8. 重建宿主机 Python venv（如不存在或损坏）
if [ ! -f "$HOME/.local/build-python3-env/bin/activate" ]; then
  python3 -m venv "$HOME/.local/build-python3-env"
  source "$HOME/.local/build-python3-env/bin/activate"
  pip install -r build_tools/hobot_tools/requirements.txt
fi

# 9. 加载构建环境
source envsetup.sh

# 10. 编译
bdall BAIC
```

### 8.3 切换 OEM 或构建模式

```bash
# 交互式重新选择配置
make lunch
# 选择新的 defconfig（例如 #3: j6b_debug_defconfig_GAC）

# 然后编译时指定对应的 OEM
bdall GAC
```

> **注意:** 切换 defconfig 后必须重新 `source envsetup.sh` 使新配置生效。

---

## 九、快速增量编译（重启后/代码更新后）

### 9.1 重启电脑后的快速恢复

重启后只需 4 行命令即可恢复编译环境（假设 Docker 镜像和 `.config` 已就绪）：

```bash
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
source build_tools/Compiler/qnx800/qnxsdp-env.sh
source envsetup.sh
bdall BAIC
```

> **注意:** 重启后宿主机 Python venv 仍然是完好的（在 `~/.local/` 下），`source envsetup.sh` 会自动激活。Docker 服务需在运行状态（默认开机自启）。

### 9.2 代码小幅修改后的增量编译

如果只修改了少数模块，不需要全量 `bdall`，可使用模块编译：

```bash
# 编译单个模块（例如只改了 hbre 下的 otaupdate）
cd /media/jinnuo/work/SourceCode/HR-J6B/BaseSW_J6B_BS
source envsetup.sh
bdm otaupdate

# 编译内核模块
bdkm hobot-driver

# 重新打包镜像（不重新编译模块）
build.sh docker disk BAIC
```

**快捷命令速查：**

| 命令 | 等价 | 用途 |
|------|------|------|
| `bdall <OEM>` | `build.sh docker all <OEM>` | Docker 内全量编译 + 生成镜像 |
| `bdm <模块>` | `build.sh docker module <模块>` | Docker 内编译单个模块 |
| `bdkm <模块>` | `build.sh docker k_modules <模块>` | Docker 内编译内核模块 |
| `bddisk <OEM>` | `build.sh docker disk <OEM>` | Docker 内只生成镜像（不重新编译） |
| `ball <OEM>` | `build.sh all <OEM>` | 本地全量编译（不使用 Docker） |

### 9.3 一键编译脚本

将以下内容保存为 `~/bin/j6b_build.sh`，方便快速编译：

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

### 9.4 编译前检查清单

执行 `bdall` 前，逐项确认：

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| Docker 可用 | `docker images \| grep debian-12` | 两个 tag 均出现 |
| 在 SDK 目录 | `pwd` | `/media/jinnuo/.../BaseSW_J6B_BS` |
| `.config` 存在 | `ls out/.config` | 文件存在 |
| `.config` 中 QNX 路径正确 | `grep QNX_HOST out/.config` | 路径以 `HR_TOP_DIR` 开头 |
| 源码无 root 文件 | `find . -user root ! -type l 2>/dev/null \| head -5` | 无输出（或仅有 out.bak） |

### 9.5 故障快速排查

| 现象 | 大概率原因 | 快速修复 |
|------|-----------|----------|
| `Permission denied` / `ModuleNotFoundError` | Docker 镜像未修复 | 重新执行 8.2 节步骤 3（初始化镜像） |
| `Please run make menuconfig` | `.config` 不存在 | 执行 `make lunch` 重新生成 |
| `Docker image does not exist` | 镜像 tag 丢失 | `docker tag systemsoft/devenv/debian-12:latest docker.hobot.cc/...` |
| `Python virtual environment is NOT properly set up` | 宿主机 venv 损坏 | `rm -rf ~/.local/build-python3-env` 后重新 `source envsetup.sh` |
| docker 权限错误 | 重启后 docker 组未生效 | `newgrp docker` 或重新登录 |
