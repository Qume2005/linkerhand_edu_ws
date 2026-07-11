# LinkerHand Edu 持久化 Live USB ISO — 构建 / 烧录 / 测试全流程

> 起稿版（Stage 1/2）。实测输出数字（ISO 体积、构建耗时、VM 内存占用等）留 TODO 占位，待 Stage 3 实跑后由 PM 再派人补齐。

## 1. 概述

把 LinkerHand Edu（ROS 2 Jazzy / Ubuntu 24.04）工作空间连同完整运行环境，打包成**「插 U 盘即用、改动持久化」**的可分发系统：

- **终端用户（老师 / 学生）**：拿到做好的 U 盘，插上、开机、即用，**零命令**。
- **生产端（我们）**：用本目录脚本一条命令重建定制 ISO、虚拟机自测、批量烧录成品 U 盘。

核心机制：内核参数 `persistent` + 一个 ext4 分区（标签 `writable`），casper 即把它作为 COW 读写覆盖层挂到只读 squashfs 之上，全部更改（装的包、改的配置、写的数据）持久化到 U 盘；无该分区时自动回退普通内存 live，不破坏启动。

---

## 2. 角色与交付模型

| 角色 | 操作 | 工具 / 命令 |
|---|---|---|
| **生产端（我们）** | 构建定制 ISO | `sudo ./build-iso.sh` |
| **生产端** | 虚拟机自测 ISO（BIOS / UEFI / 持久化） | `./test-iso.sh <iso> [--uefi] [--persist]` |
| **生产端** | 把 ISO 烧成成品持久化 U 盘 | `sudo ./make-usb.sh <iso> /dev/sdX` |
| **终端用户** | 拿到做好的 U 盘，插上、开机、即用 | 无（零命令） |

`make-usb.sh` 是**生产端**把 ISO 变成成品 U 盘的工具，**不是终端用户的命令**。

---

## 3. 目录结构

```
packaging/iso/
  build-iso.sh                 # 生产端：原 ISO → 定制持久化 ISO（一条命令重建）
  chroot-customize.sh          # chroot 内定制（换源/ROS/中文化/预编译/key 清理/sudoers）
  make-usb.sh                  # 生产端：ISO + writable 分区 → 成品持久化 U 盘（Linux）
  test-iso.sh                  # 生产端：QEMU 一键启动测试（BIOS/UEFI + 持久化验证）
  llm_settings.template.json   # 清理版 LLM 配置模板（空 key），进 git，镜像只放它
  README.md                    # 本文档
  out/                         # gitignored：最终 ISO 产物（linkerhand-edu-<ver>-amd64.iso）
  cache/                       # gitignored：离线安装包（apt deb + pip wheel + mediapipe 模型）
    customise/                 # 预装软件离线包（.deb / .tar.xz / .tar.gz），build-iso.sh 自动搬运进 chroot
  legacy/                      # 旧 Cubic 工程参考（cubic.conf、fastinstall.bash 参考）
```

| 文件 / 目录 | 职责 |
|---|---|
| `build-iso.sh` | 解包原 ISO → 注入工作空间 → chroot 定制 → 重打包 squashfs → 加 `persistent` → xorriso 生成 isohybrid ISO |
| `chroot-customize.sh` | 在 chroot 内执行：换源、装 ROS Jazzy / 系统 / pip 依赖、中文化、fcitx5、桌面启动器、预编译工作空间、清理 LLM key、CAN 免密 sudoers、从 `cache/customise/` 预装离线软件包（.deb dpkg 安装 / tarball 解压到 /opt/ + desktop entry） |
| `make-usb.sh` | 把 ISO `dd` 到 U 盘并追加一个标签为 `writable` 的 ext4 分区，产成品 U 盘 |
| `test-iso.sh` | QEMU 启动 ISO，支持 BIOS / UEFI / 持久化三种模式，持久化模式内置跨重启文件存在断言 |
| `llm_settings.template.json` | 保留 `provider/base_url/model`（stepfun 结构），`api_key` 为空；镜像里只放它 |
| `out/` | 构建产物目录（`.gitignore` 忽略） |
| `legacy/` | 旧 `install/iso/` Cubic 工程的 `cubic.conf` 与 `fastinstall.bash` 参考，仅供回溯 |

---

## 4. 生产端：构建 ISO（`build-iso.sh`）

### 4.1 前置依赖（host）

脚本启动时会自检并提示安装：

```bash
sudo apt install -y xorriso squashfs-tools mtools dosfstools gdisk parted \
  grub-pc-bin grub-efi-amd64-bin grub2-common rsync qemu-system-x86 ovmf ca-certificates
```

（含 `qemu-system-x86` / `ovmf` 供 `test-iso.sh` 用）

### 4.2 用法

```bash
sudo ./build-iso.sh
```

### 4.3 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ORIG_ISO` | `/home/larkume/下载/ubuntu-24.04.4-desktop-amd64.iso` | 原始 Ubuntu 24.04.4 桌面 ISO（6.65G） |
| `VERSION` | `2026.06.16`（或脚本内置日期） | 产物文件名版本段 |
| `BUILD_DIR` | `/tmp` | 解包 / rootfs 中间件目录，需 ≥25G 可用 |

### 4.4 产出

```
packaging/iso/out/linkerhand-edu-<VERSION>-amd64.iso
```

### 4.5 流程（脚本内部步骤）

1. **校验**：原 ISO 存在、工具齐全、`EUID==0`、`BUILD_DIR` ≥25G。
2. **解包原 ISO**：`xorriso -osirrox on -indev "$ORIG_ISO" -extract / "$ISODIR"`，校验 `casper/minimal.squashfs` / `vmlinuz` / `initrd.gz` / `boot/grub/grub.cfg` / `EFI/boot/`。
3. **unsquashfs**：解出主 rootfs。
4. **注入工作空间**：host 上 rsync 工作空间到 `$ROOTFS/_payload/ws/`，排除 `build/ log/ .pytest_cache/ install/ __pycache__/ .git/ *.pyc llm_settings.json`（**真实 key 任何阶段都不进构建**）；拷 `chroot-customize.sh` + `llm_settings.template.json` 进 rootfs；将 `cache/customise/` 下的 .deb / tarball 安装包搬运到 `$ROOTFS/_payload/` 供 chroot 安装。
5. **chroot 定制**：bind-mount `/dev /dev/pts /proc /sys`、`tmpfs /run`、拷 `/etc/resolv.conf`；`chroot "$ROOTFS" /usr/sbin/chroot-customize`；退 `apt-get clean`。
6. **重打包 squashfs**：`mksquashfs ... -comp xz -b 1048576 -Xdict-size 100% -noappend`，排除 apt 缓存 / tmp / root cache。
7. **更新元数据**：`filesystem.size`、`filesystem.manifest`（chroot 内 `dpkg -l`）、`.disk/info`。
8. **加持久化（核心）**：改 `boot/grub/grub.cfg` 与 `boot/grub/loopback.cfg`，每条 `linux` 行的 `---` 前插 `persistent`：
   ```bash
   sed -i -E 's#(linux\s+/casper/vmlinuz\s+[^#]*?)\s*---#\1 persistent ---#g' "$f"
   ```
   **无需重建 initrd**。
9. **重算 md5sum.txt**。
10. **xorriso 生成 isohybrid ISO**：`xorriso -indev "$ORIG_ISO" -report_el_torito as_mkisofs > repro.sh`（从原 ISO 探测确切参数），改源目录 / 输出 / 卷标后 `bash repro.sh`。24.04 为 `isohybrid-gpt-basdat` + MBR + `EFI/boot/bootx64.efi`。
11. **产物校验**：`file "$OUT_ISO"` → `DOS/MBR boot sector ... GPT`。

### 4.6 构建期自动断言（脚本内置）

| 断言 | 方法 |
|---|---|
| squashfs 压缩为 xz | `unsquashfs -s` |
| `grub.cfg` 与 `loopback.cfg` 均命中 `persistent` | `grep -c persistent` ≥ 1（两个文件都查） |
| sudoers 语法 OK | chroot 内 `visudo -cf` |
| 真实 key 从未进 payload / 镜像 | rsync `--exclude llm_settings.json` + `grep -c '[A-Za-z0-9]\{20,\}' /etc/skel/Desktop/llm_settings.json` → 0 |
| 预编译产物存在 | `/etc/skel/Desktop/install/setup.bash` |
| 镜像可挂载、结构完整 | `xorriso -indev -ls /` |

### 4.7 实测耗时 / 体积

> `<待 Stage 3 实测>`：ISO 体积、总构建耗时、rootfs 解包体积、squashfs 重压缩耗时。

---

## 5. 生产端：VM 自测（`test-iso.sh`）

QEMU 一键启动测试，4 种用法：

```bash
./test-iso.sh <iso>                      # BIOS live 启动（桌面可用性快速验证）
./test-iso.sh <iso> --uefi               # UEFI live 启动
./test-iso.sh <iso> --persist            # 持久化验证（BIOS）
./test-iso.sh <iso> --persist --uefi     # 持久化验证（UEFI）
```

### 5.1 持久化原理（`--persist`）

casper 启动时扫描所有块设备找标签 `writable` 的分区作为 COW 覆盖层。VM 测试里，ISO 作 cdrom 启动 + 附加一个预格式化的覆盖盘即可模拟真机 U 盘的持久分区：

```bash
truncate -s 4G "$BUILD_DIR/writable.img"
mkfs.ext4 -F -L writable "$BUILD_DIR/writable.img"
qemu-system-x86_64 -m 4096 -enable-kvm \
  -cdrom <iso> -boot d \
  -drive file="$BUILD_DIR/writable.img",format=raw \
  -display gtk
```

**两轮断言**（脚本内置自动断言）：
1. 首启：VM 内写 `~/persist-test` 文件 → 关机。
2. 用**同一** `writable.img` 再启 → 校验 `~/persist-test` 仍在 → **PASS**。

### 5.2 Live 模式（无 `--persist`）

不附加 `writable.img`，casper 找不到 `writable` 标签 → 回退内存覆盖层。同样写 `~/persist-test` → 重启 → 文件消失（断言消失）。用来验证「无持久分区时普通 live 仍可启动」。

> **attach / detach writable.img 即持久化门**：有它 = 持久化，无它 = 纯 live。

### 5.3 INTERACTIVE vs CI 模式

- **INTERACTIVE**（默认）：`-display gtk`，开图形窗口供人眼确认桌面。
- **CI**（如脚本支持）：无显示，仅跑可自动断言项（persistent cmdline、跨重启文件存在）。

### 5.4 OVMF / KVM 说明

- **UEFI**：附加 `-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd` + 一份可写 vars 副本。
- **KVM**：`-enable-kvm`，失败时回退 TCG 并 `warn`（极慢但可跑）。

> `<待 Stage 3 实测>`：VM 实测内存占用、启动到桌面耗时（KVM / TCG 各一）。

---

## 6. 生产端：烧录 U 盘（`make-usb.sh`）

### 6.1 用法

```bash
sudo ./make-usb.sh packaging/iso/out/linkerhand-edu-<ver>-amd64.iso /dev/sdX
```

### 6.2 安全防呆（脚本内置）

| 检查 | 行为 |
|---|---|
| 目标是整盘 `/dev/sdX`，非分区 `/dev/sdX1` | 拒绝 |
| 目标非系统盘 / 非已挂载根盘 | 拒绝 |
| 启动前 `lsblk` 展示目标盘信息 | 供人确认 |
| 要求输入大写 `YES` 确认 | 防误触 |

### 6.3 流程

1. `dd if=ISO of=DEV bs=8M conv=fsync status=progress`
2. `partprobe` / `udevadm settle`（重读分区表，**必在 sgdisk 前**）
3. `sgdisk --new=2:0:0 --typecode=2:8300 --change-name=2:"writable" "$DEV"`
4. `mkfs.ext4 -F -L writable -m 0 "${DEV}2"`（**标签正好 `writable`**）
5. `lsblk` / `blkid` 验证

### 6.4 产出

U 盘含两个分区：

| 分区 | 类型 | 标签 | 内容 |
|---|---|---|---|
| 1 | ISO9660（isohybrid GPT+MBR） | （ISO 卷标） | 只读系统 |
| 2 | ext4 | `writable` | casper COW 持久层 |

**推荐 U 盘 ≥16G**（需 > ISO 体积 + ≥1G 持久层）。

---

## 7. GRUB 双模式菜单

开机 GRUB 提供 4 个选项（英文标签，避免中文字体缺失乱码）：

| 菜单项 | 内核参数 | 含义 |
|---|---|---|
| `LinkerHand Edu (Persistent, default)` | `persistent` | **保留所有更改**，关机不丢 |
| `LinkerHand Edu (Live clean)` | 无 `persistent` | **原始干净系统**，关机清空 |
| `LinkerHand Edu (Persistent, safe graphics)` | `persistent nomodeset` | 持久化 + 兼容显卡 |
| `LinkerHand Edu (Live, safe graphics)` | `nomodeset` | 纯 live + 兼容显卡 |

**默认超时进 Persistent**（第一条）。

---

## 8. 终端用户使用

1. 把做好的 U 盘插到目标电脑。
2. 开机，进 BIOS 选 U 盘启动（或机器已设 U 盘优先）。
3. GRUB 默认超时进 **Persistent** 模式 → 进桌面，**改的东西自动存 U 盘**，下次开机还在。
4. 想回到原始干净系统 → 开机时在 GRUB 选 **Live clean**（该次改动不保存）。

### LLM 控制功能

桌面有 `llm_settings.json`（空 key 模板）。**LLM 控制功能需先在此文件填入自己的 API key**：

- 模板保留 `provider` / `base_url` / `model`（stepfun 结构），仅 `api_key` 为空。
- 空 key 时 UI 拦截并提示用户填入。
- 加载点是 `os.getcwd()/llm_settings.json`，launch 从 `~/Desktop` 启动，落点正确。

---

## 9. 验证矩阵

完整测试矩阵，每项含方法与期望输出。脚本可自动断言的标「脚本」，需人眼 / 手动的标「手动」。

| 层 | 验证项 | 方法 | 期望 | 自动? |
|---|---|---|---|---|
| 构建 | squashfs 压缩 xz | `unsquashfs -s` | 报 xz | 脚本 |
| 构建 | grub / loopback 命中 `persistent` | 解 ISO `grep persistent` | 两文件各 ≥1 | 脚本 |
| 构建 | sudoers 语法 OK | chroot 内 `visudo -cf` | OK | 脚本 |
| 构建 | 真实 key 从未进 payload / 镜像 | rsync exclude + grep 长串 | 计数 0 | 脚本 |
| 构建 | 预编译产物存在 | `install/setup.bash` | 存在 | 脚本 |
| 构建 | 镜像可挂载、结构完整 | `xorriso -indev -ls /` | 列出根目录 | 脚本 |
| 启动 | BIOS 可启动进桌面 | `test-iso.sh <iso>` | 进桌面 | 半自动 |
| 启动 | UEFI 可启动进桌面 | `test-iso.sh <iso> --uefi` | 进桌面 | 半自动 |
| 启动 | `persistent` 在 cmdline | VM 内 `cat /proc/cmdline \| grep persistent` | 命中 | 手动 / 脚本 |
| 持久化 | overlay 挂载 writable | VM 内 `mount \| grep -i writable` | 命中 | 手动 |
| 持久化 | 写文件 → 重启 → 仍在 | `test-iso.sh --persist` 两轮 | 文件存在 | 脚本 |
| 功能 | ROS 环境 source 可用 | VM 内 `source ~/Desktop/install/setup.bash && ros2 pkg list \| grep l10` | 列出 l10 包 | 手动 |
| 功能 | CAN 免密 sudo | VM 内 `sudo -n ip link set can0 up ...` | 不提示密码 | 手动 |
| 功能 | 桌面启动器秒开（无 colcon build） | VM 内点启动器计时 | 秒开 | 手动 |
| 烧录 | writable 分区正确 | `lsblk` / `blkid`（make-usb 后） | 分区 2 标签 `writable` | 脚本 |
| 真机 | 灵巧手响应真机控制 | 插 CAN 盒测（VM 测不了硬件） | 响应 | 手动 |
| 真机 | 摄像头 `camera_id=0` | 物理摄像头测（VM 无直通） | 手势识别正常 | 手动 |

`test-iso.sh` 内置可自动断言的检查：persistent 命中、文件跨重启存在。

---

## 10. 排错

| 现象 | 排查 |
|---|---|
| **persistent 不生效**（重启数据丢失） | ① 查 `boot/grub/loopback.cfg` 是否也改了（不止 `grub.cfg`），两文件都须命中 `persistent`；② 查持久分区标签是否正好 `writable`（`blkid`），casper 优先 `casper-rw`，默认找 `writable` |
| **真机 CAN 起不来 / sudo 要密码** | ① 查 live 用户是否在 `sudo` 组（casper 默认应在）；② 查 `/etc/sudoers.d/linkerhand-can` 存在且 `chmod 440`，`visudo -cf` 通过 |
| **摄像头编号漂移**（多设备时 camera_id 非 0） | 本次**未做 udev**（摄像头型号不固定），多设备时手动改 `camera_id` |
| **GRUB 中文乱码** | 已统一用英文标签，避免字体缺失 |
| **QEMU 无 KVM（极慢）** | `-enable-kvm` 失败自动回退 TCG，慢但可跑；真机 / 有 KVM 的机器优先 |
| **构建空间不足** | `BUILD_DIR`（默认 `/tmp`）需 ≥25G，前置 `df -h /tmp` 检查 |
| **chroot 内 apt / 联网失败** | chroot 共享宿主机网络命名空间，宿主机联网 + `/etc/resolv.conf` 已拷入即联网 |

---

## 11. 遗留 / 清理

### 旧 Cubic 工程已废弃

旧打包流程位于 `install/iso/`（Cubic GUI 工程），已被本目录纯脚本流水线替代，**不再维护**。`install/` 本身是 colcon 构建产物目录（`.gitignore` 已忽略），整套旧打包逻辑从未进 git。

### 大型中间件可手动清理

`install/iso/` 下的大型中间件（均为 gitignored，新流水线不再需要）可手动删除释放约 16G：

- `install/iso/custom-root/`（~6G）
- `install/iso/custom-disk/`（~4.6G）
- 旧 ISO
- `install/iso/partition-*.img`

> 删前 `du -sh` 确认；**`fastinstall.bash` 原件删前先归档**到 `packaging/iso/legacy/`。

### `legacy/` 备查

`packaging/iso/legacy/` 留有：

- `cubic.conf` — 旧 Cubic 工程配置
- `fastinstall.bash.reference` — 旧 chroot 定制脚本，`chroot-customize.sh` 的演进来源

仅供回溯，不参与构建。

---

## References

- 计划文件：`/home/larkume/.claude/plans/u-iso-u-u-u-starry-giraffe.md`（方案设计 / 验证矩阵 / 角色与交付模型 / 实施阶段）
- `.gitignore`：`packaging/iso/out/` 已忽略
- casper 持久化基石：镜像 `initrd.gz` 内 casper 1.498 脚本（默认 `writable` 标签，有 `casper-rw` 则优先）
