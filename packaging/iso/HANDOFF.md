# 交接遗言 — LinkerHand Edu 持久化 Live USB ISO

## 一句话
把 LinkerHand L10（ROS2 Jazzy / Ubuntu 24.04）工作空间打成「插U盘即用、改动持久化、GRUB 双模式（持久化默认/Live干净，英文菜单）」的可分发 ISO+U盘。计划已批准，脚本已写完待实跑。

## 计划文件
`/home/larkume/.claude/plans/u-iso-u-u-u-starry-giraffe.md`（**注意**：其第 8 节是早期「单菜单 sed」版；**最终设计是双模式英文菜单**，以本文「GRUB 菜单」段为准）。

## 已完成（脚本写完、静态审过）
`packaging/iso/` 下：
- `build-iso.sh`（560 行）— 静态审 8/8 PASS，**唯一风险见下**
- `chroot-customize.sh` + `llm_settings.template.json` — 静态 PASS（真实 key 零进、sudoers 最小权限 %sudo 组、colcon copy 模式、3 项打磨齐）
- `make-usb.sh`（390 行，含 --selftest）— 静态 7/7 PASS
- `test-iso.sh`（470 行，4 模式）— 静态 PASS
- `README.md` 起稿（实测数字待 Stage 3 补）
- `legacy/`（cubic.conf + fastinstall.bash 参考）、`.gitignore` 已加 packaging/iso/out/

## 当前状态：等用户跑 Stage 3（用户本机自己跑）
用户已定：保持 dev-team PM 模式，Stage 3 用户本机跑（沙箱禁了 agent 的 bash/chmod/visudo/sudo）。
Stage 3 清单（Phase A–E）见上轮对话 / 计划文件「实施阶段」。**关键阻塞：等用户贴 Phase A 输出，尤其第 5 条 `xorriso -report_el_torito as_mkisofs` 的完整输出**。

## 唯一真实风险（Phase B 构建前必先修）
`build-iso.sh:444` 的 `patch_repro_sh` 用 sed `s# +[^ -][^ ]*$##` 从 `as_mkisofs` 输出剥离源目录参数——作者没见过真实格式，可能改错 token，**生成「能构建但无法启动」的 ISO**。拿到用户真实输出后，派 Coder 校准。

## 待办修复（一次 Coder dispatch 合并）
1. `build-iso.sh`：`patch_repro_sh` 的 sed 依据真实 `as_mkisofs` 输出校准
2. `build-iso.sh`：加 `echo "$patched"` 诊断 + 删死变量 `MOUNTED_DEVS`（L24）
3. `test-iso.sh`：几处 `read` 加 `|| true`（L296/327/341，防 stdin EOF）

## 接力者下一步
1. 读本文 + 计划文件。
2. 若用户已贴 Phase A 输出 → 派 Coder 做上面 3 项修复 → Code Reviewer。
3. 用户跑 Phase B：`sudo ./packaging/iso/build-iso.sh`，贴日志 + `file packaging/iso/out/*.iso`。
4. 用户跑 Phase C（QEMU 四象限）、D（烧录）、E（真机）。
5. 输出回来 → PM 断言/修。
6. 补 README 实测数字 + 主 README「分发与部署」小节 → commit。

## 关键约束（必知）
- **dev-team PM 模式**：主 agent 禁 Read/Write/Bash/Edit，只能委派 subagent（先加载 development-team:pm + development-team）。
- **沙箱**：subagent 禁 bash/chmod/visudo/sudo；grep/python3/ls/mkdir/Write-to-workspace 可用。`.claude/` 子树写不进 → 用 packaging/iso/docs/。
- **计划文件同步问题**：subagent 只能写 -agent-<hash> 文件，主计划文件靠某种同步；双模式改动在 agent 文件，主文件第 8 节是旧的。
- **持久化机制**（已从 initrd.gz 内 casper 1.498 脚本核实）：内核 persistent 参数 + ext4 分区标签 writable（casper-rw 回退兼容），casper 作 COW 覆盖层。
- chroot 共享宿主机网络命名空间（宿主机联网即可）；live 用户 uid 不硬编码（靠 casper skel-copy 自动 chown）。

## 双模式 GRUB 菜单（英文，最终版）
```
set default=0
set timeout=10
menuentry "LinkerHand Edu - Persistent (default)"       { linux /casper/vmlinuz persistent --- quiet splash }
menuentry "LinkerHand Edu - Live (clean, no save)"      { linux /casper/vmlinuz --- quiet splash }
menuentry "LinkerHand Edu - Persistent (safe graphics)" { linux /casper/vmlinuz persistent nomodeset --- quiet splash }
menuentry "LinkerHand Edu - Live (safe graphics)"       { linux /casper/vmlinuz nomodeset --- quiet splash }
```

## test-iso 4 模式
`test-iso.sh <iso>` / `--uefi` / `--persist [--uefi]` / `--live [--uefi]`。交互默认（手操 VM）；--persist 附加 writable.img、--live 不附加（回退内存）；--uefi 需 ovmf（Phase B apt 装）。

---

## 后续更新（2026-06-18 ~09:00，by PM）

**7 个构建 bug 已修复并通过 Code Review**（fresh evidence + red-green 回归测试，每个都有 delivery doc 于 `.claude/development-team/coder/` 与 review 于 `.claude/development-team/code-reviewer/`）：
1. `patch_repro_sh` sed（引导令牌被误删）→ 仅剥离路径型尾部 token + 诊断 echo
2. `ORIG_ISO` 在 sudo 下解析到 `/root` → 经 `SUDO_USER`/`getent` 解析真实用户家目录
3. `casper/initrd.gz` → `casper/initrd`（24.04 改名）
4. resolv.conf 悬空符号链接 `cp` 中止 → `cp --remove-destination`
5. numpy 2.x vs 系统 1.26.4 冲突 → pin `numpy==1.26.4` + `opencv-contrib-python==4.11.0.86`
6. `source /opt/ros/jazzy/setup.bash` 在 `set -u` 下中止 → strict-mode save/restore 守卫
7. `verify_product` 门禁要求 libmagic 不输出的 `GPT` token → 改用 `xorriso -report_el_torito` 校验真实可启动记录

**主动审计结果：** `[6/11]`–`[11/11]` 及 chroot-customize `C1` 之后步骤已审计，无 HIGH 风险（`verify_product` 已预防性修复；`recompute_md5` 在 pipefail 下为低概率残留，按需反应式修复）。

**当前状态：** 构建脚本已就绪。沙箱无法 sudo，Phase B 必须由用户在本机终端运行：`sudo ./packaging/iso/build-iso.sh 2>&1 | tee /tmp/iso-build.log`。

**下一步：** Phase B 成功 → Phase C（QEMU 四模式启动/持久化测试）→ D（写 U 盘 make-usb.sh）→ E（真机启动）→ README 实测数据回填（Task #4）→ commit（Task #5）。

**计划文件：** `/home/larkume/.claude/plans/luminous-soaring-sifakis.md`
