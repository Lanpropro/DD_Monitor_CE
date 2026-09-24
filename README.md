<div align="center">

# DD监控室CE

专为 B 站直播设计的多窗口监控与观看工具

[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)](#运行环境)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-LGPL--2.1-blue.svg)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/Lanpropro/DD_Monitor_CE)](https://github.com/Lanpropro/DD_Monitor_CE/commits/main)
[![Stars](https://img.shields.io/github/stars/Lanpropro/DD_Monitor_CE?style=flat)](https://github.com/Lanpropro/DD_Monitor_CE/stargazers)

[功能特性](#功能特性) · [快速开始](#快速开始) · [布局系统](#布局系统) · [开发指南](#开发指南) · [许可与来源](#许可与来源)

</div>

---

## 项目简介

DD监控室CE 是一款基于 Python、PySide6 和 VLC 的 B 站多窗口直播监控工具。

它可以将多个直播间集中显示在同一个画面墙中，并提供直播状态监控、关注导入、弹幕显示、横竖屏两套布局和单路播放控制等功能。

本项目是 [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest) 的二次开发版本，原作者：[执明神君](https://space.bilibili.com/637783)。在保留原项目取流与播放能力的基础上，尝试重构了界面及部分交互功能。


## 项目展示

![DD监控室CE 普通布局](docs/overview1_Landscape_mode.png)

![DD监控室CE 弹幕布局](docs/overview2_Landscape_mode.png)

竖屏（主画面 16:9 占满宽度、小画面填满下面）：

![DD监控室CE 竖屏布局](docs/overview1_Portrait_Mode.png)

## 功能特性

- 📺 最多同时管理 16 路直播画面
- 🧩 横屏两套布局（平分布局 / 大带小）与弹幕布局，外加一整套竖屏预设
- 📱 竖屏模式：顶部横栏（搜索 + 图标 + 账号那一块）、主画面 16:9 占满宽度、小画面自动铺满下面
- 🔀 拖窗口换方向时，按「能放几路」自动切到最相似的另一套布局
- 🔄 自动刷新主播开播、下播及直播间状态
- 🔔 支持开播提醒
- 👀 支持关注列表悬停预览
- 📌 支持主播置顶及拖动排序
- 🔐 支持 B 站扫码登录（未登录时侧栏也会露出「登录」按钮）
- 📥 支持从 B 站账号导入关注列表
- 🎚️ 每个播放格可以独立设置音量、静音、画质
- ⏺️ 每格独立录制直播流、保存最近数分钟的即时回放（便携包内置 FFmpeg）
- 🎧 每一路可以单独路由到左声道 / 右声道
- 🛠️ 支持断流重连和画面卡死检测
- 🧩 支持插件（`plugins_user/<名字>/plugin.py`）
- 💾 自动保存布局（分横竖屏各记一套）、音量、画质和界面状态

录制按钮位于每块画面**底栏暂停键右侧**，标着 `● 录制`；点击开始/停止。
第一次点击时需在「设置 → 录制」选择保存目录；取消设置则不会开始录制。
右键格子可以保存最近一段（即时回放）。即时回放**跟着直播自动开**，不用手动点；
默认范围是「只跟着录制走」—— 只有正在录制的格子才开缓存。这是因为每开一格缓存
都是**再拉一路同样的流**（带宽翻倍）加一个 FFmpeg 进程（约 155 MB 内存）；
想让每格都能随时回放，可在设置里改成「所有播放中的格子」，
并用「缓存格子数上限」封顶（默认 3 格）。完全不需要这个功能的话，把「设置 → 录制 →
即时回放」的勾去掉即可：不给任何格子开缓存、右键菜单里也没有「保存最近 N 分钟」、
结束录制时也不再顺手存回放 —— 录制本身不受影响，照常写完整文件。
默认 MP4 + 原始流直存，不重编码；只有选择 H.264
重编码时，设置里的码率和帧率才生效；直接修改任一数值会自动切换到 H.264。
格式另可选 MKV、MOV、TS。默认开启「录制时锁定原画」；直播源未提供原画时不会
把较低画质当作原画录制，停止后恢复录制前的画质。可在录制设置里关闭此锁定。
文件只含这一路直播的画面和原始声音，
不含软件弹幕或控件。格子被布局隐藏、主播下播或关闭这一路时会自动停止。
保存目录空间低于警戒线时，会提示并停止该路录制；已写入分段保留在保存目录的
`.ddm-parts` 中，导出空间不足时可在清理磁盘后手动恢复。

录制和导出都跑在独立的 FFmpeg 子进程里，进程被压到 Windows 的「后台模式」
（CPU 与磁盘 IO 优先级都降到最低），并挂在主进程的 Job Object 上 —— 主进程
无论是正常退出、崩溃还是被任务管理器强杀，后台的 FFmpeg 都会一起结束，
不会留下关了软件还在偷偷录的孤儿进程。纯缓存的会话会边录边裁分段，
只保留「回放缓存时长」那么多，不会一直堆积。

## 运行环境

目前仅支持 Windows。

| 组件 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 64 位 |
| Python | 3.10 或更高版本（**只有从源码跑才需要**；exe 便携版不用装） |
| VLC | VLC 3.x（exe 便携版已自带运行库，源码版要自己准备） |
| 图形界面 | PySide6 |
| 播放组件 | python-vlc / libVLC |
| 录制组件 | FFmpeg（exe 便携包内置，自动发现；从源码运行时可通过 `PATH` 提供） |

## 快速开始

### 方式一：下载 exe（推荐，免装 Python）

1. 到 [Releases](https://github.com/Lanpropro/DD_Monitor_CE/releases) 下载
   `DDMonitorCE-v0.1-exe.zip`。
2. 解压到任意目录（比如 `D:\DD监控室CE`）。
3. 双击解压出来的 **`DD监控室CE-v0.1-exe.exe`** 就能用。

配置、缓存、日志都在解压出来的那个目录里（`utils\config.json`、`cache\`、`logs\`），
整个目录拷到别的 Windows 机器也能直接用；删掉 `utils\config.json` 等于恢复出厂设置。
`_internal\` 里是运行库（含 `libvlc.dll` 和 `plugins\`），别删。

exe 便携包内置 `ffmpeg.exe`，录制无需另行配置 FFmpeg 路径；仍需首次选择保存目录。

### 方式二：从源码运行

1. 获取项目：

```powershell
git clone https://github.com/Lanpropro/DD_Monitor_CE.git
cd DD_Monitor_CE
```

2. 创建虚拟环境：

```powershell
python -m venv .venv
```

3. 安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

4. 准备 VLC 运行库：播放功能依赖以下文件，可以从 DD监控室原项目复制到本项目根目录，
   或安装 VLC 3.x 后从 VLC 安装目录复制（`libvlc.dll`、`libvlccore.dll`、`plugins\`）。

5. 启动程序：

- 双击 `run.cmd`：普通启动，不显示控制台。
- 双击 `run-console.cmd`：显示取流、重连及弹幕日志。
- 命令行运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

## 基本使用

第一次启动时，关注列表和画面墙均为空。

1. 点侧栏的「登录」按钮扫码登录 B 站账号（不登录也能加直播间，只是不能导入关注、
   部分弹幕信息会缺）。
2. 点击「+ 添加直播间」，输入直播间号、直播间链接或短链接。
3. 将主播从关注列表拖入画面墙。
4. 点击「布局预设」选择画面布局（菜单里只列当前方向能用的布局）。
5. 把窗口拖成竖的，会自动切到对应的竖屏布局；再拖回横屏同理。

登录之后还可以用「导入关注」批量导入关注的主播。

> 登录凭证会保存在本地 `utils/config.json` 中。该文件已加入 `.gitignore`，请勿手动上传或分享。

## 布局系统

菜单里**只列当前窗口方向能用的布局**，分成三栏。

### 普通布局（横屏）

平分布局（每格一样大）：

- 单画面、上下两分、左右两分
- 四分、六分、九分

大带小（菜单里单独一段，以小标题「大带小」开头）：

- 主画面 + 2 小、2 小 + 主画面（镜像，和前者左右相反）
- 主画面 + 3 小、主画面 + 4 小
- 上主画面 + 下 2 小
- 主画面 + 5 小环绕
- 双主画面 + 4 小

### 弹幕布局（横屏）

- 主画面 + 弹幕
- 上 1 大 + 小 + 弹幕
- 主画面 + 1/2/3 小 + 弹幕
- 弹幕在左 + 主画面 + 2 小

### 竖屏布局

竖屏不按行列等分摆，而是**主画面按 16:9 占满整宽**、小画面自动铺满下面：

- 主画面 + 2/4/6 小
- 主画面 + 2/4/6 小 + 弹幕（弹幕占最底下一整条）

### 换方向时的对映

把窗口在横竖屏之间拖动时，程序会按「能放几路」找**最相似**的那一套接上
（横屏「主画面 + 2 小」↔ 竖屏「主画面 + 2 小」，弹幕布局只对映弹幕布局），
而不是退回某个万能布局。

弹幕格会自动跟随当前主画面的直播间。布局变大时，多出来的格子保持空白，不会把
关注列表里下一个直播间自动填进来。

## 关注列表

| 排序方式 | 说明 |
| --- | --- |
| 自定义顺序 | 通过拖动调整顺序，并自动保存 |
| 开播优先 | 正在直播的主播自动排在前面 |
| 导入顺序 | 按主播加入关注列表的先后排列 |

置顶的直播间始终位于列表顶部。手动拖动列表后，程序会自动切换回自定义排序。

## 弹幕功能

弹幕面板目前支持：

- 粉丝牌和 B 站表情显示
- 字体与字号调整
- 屏蔽词过滤

未登录时，部分弹幕用户名可能会被 B 站隐藏，建议登录后使用。

## 快捷键

| 默认按键 | 功能 |
| --- | --- |
| `F` | 将鼠标所在的直播画面设为主画面 |
| `Esc` | 恢复上一个布局 |
| `M` | 静音 / 取消静音鼠标所在的那一路 |
| `Alt` + `M` | 只保留鼠标所在画面的声音（鼠标不在画面上＝全部静音） |

快捷键可以在程序设置中修改。

## 配置、日志与缓存

| 内容 | 路径 |
| --- | --- |
| 用户配置 | `utils/config.json` |
| 配置备份 | `utils/config.json.bak` |
| 运行日志 | `logs/ddm-YYYY-MM-DD.log` |
| 主播头像 | `cache/avatars/` |
| 直播封面 | `cache/covers/` |
| 弹幕表情 | `cache/emoticons/` |

## 开发指南

安装依赖后，可以运行全部离线自检（25 个脚本，不需要联网）：

```powershell
dev\run-checks.cmd
```

要打发布包（exe 便携版 + 源码包 + 两个 zip，输出到 `results\`）：

```powershell
powershell -File dev\build_release.ps1
```

> 冻结 exe 用的是单独的 PySide6 6.9 依赖目录 `work\deps`（主开发环境是 6.11，
> 6.11 冻出来的 exe 起不来）；脚本缺了会提示怎么装。

主要开发文件：

- `ddm/theme.py`：颜色、字号和圆角等设计令牌。
- `ddm/widgets.py`：主要界面控件。
- `ddm/app.py`：应用状态及业务流程。
- `ddm/layouts.py`：画面布局（布局表、横竖屏对映、缩略图）。
- `ddm/player.py`：播放器控制。
- `ddm/version.py`：版本号与显示名。

## 已知限制

- 目前仅在 Windows 上使用和测试。
- 依赖 B 站非公开接口，接口调整可能导致部分功能失效。
- 源码方式运行需要自己准备 VLC 运行库（exe 便携版已自带）。
- 原项目的热榜和悬浮窗功能尚未迁移。
- 接别的直播平台仍走插件接口；录制与即时回放已经内置。

## 插件

不想塞进本体的功能可以做成插件。插件放 `plugins_user/<插件名>/plugin.py`，
接口说明见 [`docs/plugins.md`](docs/plugins.md)。

- 可直接用的例子：`plugins_user/danmaku_log/`（弹幕落盘 + 发弹幕）
- 接别的平台的骨架：`plugins_user/_template_platform/plugin.py`

插件是受信任代码，和本体同进程运行 —— 只装自己看过源码的插件。
还没做、打算怎么做的，记在 [`idea.txt`](idea.txt)。

## 贡献

欢迎提交 Issue 或 Pull Request。提交问题时，建议附上 Windows、Python 和 VLC 版本、问题复现步骤、对应日志及必要的界面截图。
你也可以尝试直接私信[b站账号](https://space.bilibili.com/193559518)
请在分享日志前检查并移除账号凭证等敏感信息。

## 致谢

- [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest)：原始项目及主要播放、取流实现参考。
- [blivedm](https://github.com/xfgryujk/blivedm)：B 站直播弹幕协议实现。
- [BewlyCat](https://github.com/keleus/BewlyCat)：界面配色和部分视觉设计参考。

详细来源说明请参阅 [`NOTICE.md`](NOTICE.md)。

## 许可与来源

本项目基于 **GNU Lesser General Public License v2.1** 发布。

使用、修改或分发本项目之前，请阅读：

- [`LICENSE`](LICENSE)
- [`NOTICE.md`](NOTICE.md)

## 免责声明

本项目是个人维护的第三方工具，与哔哩哔哩官方无关。

本项目的使用、修改与分发权利以 [`LICENSE`](LICENSE) 为准。使用者应自行遵守哔哩哔哩用户协议以及所在地适用的法律法规，并自行承担使用本项目可能产生的风险。
