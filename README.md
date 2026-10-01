# CSNO-ESP

基于 Frida 的安卓《CSNO》内存研究与 ESP（透视框）演示工具。

> **方案定位（重要）**：当前版本 `v1.0-frida` 为**授权研发环境下的参考实现**。
> Frida 方案会在客户机内留下大量可见痕迹（frida-server 进程、注入的 agent 内存区、
> `TracerPid`、27042 端口等），**不是长期隐蔽方案**，也请勿在此假设之外使用。
> 下一阶段的正式方向是**宿主侧（Windows 读取 dnplayer 进程内存）**零客户机组件的
> 读取方案。

## 项目简介

《CSNO》是一款由 **乐迪** 移植到安卓平台的 CS:GO 风格游戏（包名 `com.ledi.csno`，Source 引擎构建）。
本项目是对该游戏的**纯只读内存逆向研究**：通过解析 Source 引擎的 RecvTable 网络变量表、客户端实体列表（Entity List）与视图矩阵，在 PC 端叠加显示透视框（ESP）——包括玩家方框、血量条、阵营颜色等。**全程只读取内存，不修改、不写入任何游戏数据。**

原作者：**乐迪**
游戏介绍视频：<https://www.bilibili.com/video/BV1imat6dEM1>

## ⚠️ 免责声明

本项目**仅供娱乐与技术学习研究用途**，请在离线人机对局等不影响他人的环境中使用。

- 禁止用于任何商业用途
- 禁止在任何涉及真实玩家的对局中使用，或以任何方式影响他人游戏体验
- 使用本工具产生的一切后果由使用者自行承担
- 本项目与游戏原作者乐迪及 Valve 无任何关联

## 工作原理

1. **静态分析**：从 `libkm_client_panorama_client.so` / `libkm_engine_client.so`（未加壳、未剥离符号的 NDK 构建）中解析出 RecvTable 结构和网络变量偏移（`m_iHealth`、`m_iTeamNum`、`m_vecOrigin` 等）
2. **运行时定位**：通过 `/proc` maps 解析模块基址（支持 Houdini ARM→x86 转译环境与原生 arm64），并用 ADRP+ADD 特征码扫描校验全局指针，不硬编码任何地址
3. **数据读取**：按已验证的实体列表公式 `entity(i) = *(client + 0x16432A0 + 0x28 + 0x20*i)` 枚举玩家（每帧约 130 次指针读取，毫秒级开销）
4. **投影绘制**：读取引擎视图矩阵（CRender+0xA4），World-To-Screen 投影后在透明置顶窗口上绘制方框

## 文件说明

| 文件 | 说明 |
|------|------|
| `config.js` | 运行时配置：模块名、结构偏移、RVA 种子、特征码 |
| `offsets.json` | 静态分析提取的完整偏移配置（含验证来源说明） |
| `frida_run.py` | 非交互式 Frida 脚本驱动器 |
| `esp_loop.js` | 常驻 RPC 帧数据提供端（纯内存读取） |
| `esp_overlay.py` | PC 端透明置顶叠加窗口（Windows，~30 Hz 刷新） |
| `esp_auto.py` | 全自动守护脚本：监测模拟器 / frida-server / 游戏进程状态，自动启动绘制 |
| `start_esp.bat` | Windows 一键启动：自动拉起模拟器 → 等待开机 → 启动游戏 → 运行守护脚本 |
| `config.example.json` | 一键脚本的本机路径配置模板（复制为 `config.json` 使用） |

## 使用方法

环境要求：Windows + 已 root 的安卓模拟器（如 LDPlayer）+ Python 3 + Frida

### 一键启动（推荐 · 懒人模式）

1. 把 `config.example.json` 复制为 `config.json`，填入你自己机器上的路径：
   - `python`：Python 解释器完整路径（需已 `pip install frida`）
   - `adb`、`ldconsole`：模拟器安装目录下的对应工具路径
   - 路径建议不含空格，分隔符用 `/`（JSON 里反斜杠需要转义，正斜杠最省事）
2. 双击 `start_esp.bat`：自动完成「启动模拟器 → 等待安卓开机 → 启动游戏 → 运行 ESP 守护脚本」全流程，各阶段等待均有 3 分钟超时保护
3. 退出：点击屏幕右上角红色 **「✕ ESP」** 悬浮按钮（或关闭脚本窗口 / 在控制台按 Enter）

> `config.json` 已加入 `.gitignore`，仅存在于本机，不会被提交；没有 `config.json` 时，脚本退回使用系统 PATH 中的 `python` / `adb` / `ldconsole`。

### 手动启动

```bash
# 1. 安装依赖
pip install frida frida-tools

# 2. 启动模拟器中的 frida-server（需 root，架构需匹配模拟器）
adb push frida-server /data/local/tmp/frida-server
adb shell "su -c 'chmod 755 /data/local/tmp/frida-server'"
adb shell "su -c 'setsid /data/local/tmp/frida-server > /dev/null 2>&1 &'"

# 3. 启动游戏并进入人机对局

# 4. 启动全自动守护脚本（推荐 —— 一条命令搞定）
#    自动监测：模拟器在线状态 / frida-server 存活（掉线自动重启）/
#    游戏进程（启动自动附加、退出自动分离、重启自动重连）/ 模拟器窗口移动
python esp_auto.py
#    退出：点击右上角红色 "✕ ESP" 悬浮按钮，或在控制台按 Enter

#    或使用手动版本（单次附加，不自动恢复）
python esp_overlay.py
```

> adb 不在 PATH 时，先设置 `ADB` 环境变量指向模拟器自带的 adb.exe。

绿色框 = 队友，红色框 = 敌人，左侧竖条 = 血量；左上角灰字为状态与追踪人数提示。

> 注：`offsets.json` 中的 RVA 种子仅对当前游戏构建版本有效，游戏更新后需重新提取；网络变量偏移（netvars）与特征码具有更好的跨版本稳定性。偏移提取方法见 `esp_loop.js` 与 `config.js` 中的注释。

## 支持环境

- LDPlayer 等安卓模拟器（游戏进程为 x86_64 + Houdini ARM 转译，工具已适配）
- 原生 arm64 安卓设备（实体公式与偏移通用；`frida-server` 需换成 arm64 版本）
