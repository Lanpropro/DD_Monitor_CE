# 来源与许可说明

## 这是什么

DD 监控室 CE 是 [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest) 的二次开发版本。

- 原项目作者：智明神君
- 原项目地址：https://gitee.com/zhimingshenjun/DD_Monitor_latest
- 原项目许可：GNU Lesser General Public License v2.1（见项目根目录 `LICENSE`，从原仓库原样保留）

## 改了什么

- **界面层全部重写**：左侧关注列表（可收起、可拖动排序、可置顶）、画面墙布局系统（普通布局 + 弹幕布局两组）、
  每个格子的控制条（画质 / 音量 / 静音 / 暂停 / 刷新 / 关闭）、设置窗口、快捷键。
- **单路控制**：每格独立画质与音量，主画面自动原画、其余自动 720P。
- **登录与导入**：扫码登录 + 内置浏览器登录，导入关注（多选、可只挑直播中的）。
- **取流**：直连 http FLV 不落盘，App 通道优先、失败回退 web 通道；断流按指数退避自动重连。
- **弹幕**：画面墙里可以放一整格弹幕，跟着主画面那一路走（换台/切布局自动跟随），
  用 `blivedm` 收弹幕、礼物、上舰、醒目留言。
- 播放、音频和悬停预览已迁移到 python-mpv / libmpv，不再依赖 VLC。

界面配色与尺度参考了 [BewlyCat](https://github.com/keleus/BewlyCat) 的设计令牌（基色、圆角、胶囊控件、字号层级）。

## 第三方组件

- 封面人物焦点使用本地 OpenCV 4.13（Apache-2.0）和
  opencv-python-headless 4.13.0.92（打包代码 MIT）；wheel 自带依赖许可。
  真人 YuNet 与二次元 lbpcascade_animeface 模型均为 MIT，固定上游来源、
  SHA256 和许可见 `ddm/assets/licenses/cover-focus-*` 与动漫模型 XML 内的许可。

- pypinyin 0.55.0：关注栏与导入关注使用其词典进行全拼、首字母搜索，
  上游 https://github.com/mozillazg/python-pinyin ，以 MIT 许可分发；
  许可文本见 `ddm/assets/licenses/pypinyin-LICENSE.txt`。

- Source Han Sans（思源黑体）：弹幕默认使用 Adobe 官方 2.005R 简体中文 Regular 字体，
  以 SIL Open Font License 1.1 分发。原始字体位于 `ddm/assets/fonts/`，
  版权与许可见 `ddm/assets/licenses/source-han-sans-LICENSE.txt`，
  固定来源与 SHA256 见 `ddm/assets/licenses/source-han-sans-SOURCE.json`。
- `blivedm/`：B 站直播弹幕协议库，上游 https://github.com/xfgryujk/blivedm 。
  这份是从原仓库带过来的，**仓库里没有附带它的许可文件**；如果以后要对外分发，需要补上上游的许可。
- libmpv：随包提供 shinchiro 的 Windows x64 构建；固定版本、下载地址、DLL 和
  压缩包校验值见 `ddm/assets/licenses/libmpv-SOURCE.json`。构建包含 GPL 组件；
  mpv 的版权说明及 GPL/LGPL 文本随包保留于 `mpv-license/`（源码中位于
  `ddm/assets/licenses/mpv-*`），具体构建及依赖来源见该来源清单。
- python-mpv 1.0.8：GPLv2+ 或 LGPLv2.1+，许可文本见
  `ddm/assets/licenses/python-mpv-LICENSE.*.txt`。
- 国内直播弹幕（`ddm/live_danmaku.py`）：协议字段及抖音 signature 算法参考
  [biliup](https://github.com/biliup/biliup/tree/master/crates/danmaku/src/protocols)，
  改写部分的 MIT 许可见 `ddm/assets/licenses/biliup-MIT.txt`。
- FFmpeg：录制/即时回放使用独立的 `ffmpeg.exe` 子进程。发布包所带的
  `ffmpeg-license/README.txt` 记录具体构建版本与对应源码地址，
  `ffmpeg-license/LICENSE` 为其许可证；该 GPLv3 构建未纳入本仓库源码。

## 还没做的

- 原项目的热榜、悬浮窗没有搬过来；录制已由 `ddm/recording.py` 实现。

## 关于分发

虎牙插件使用 [Streamlink](https://github.com/streamlink/streamlink) 8.6.1
解析公开直播流，许可证为 BSD-2-Clause。源码安装由 requirements.txt 安装依赖；
冻结打包使用 collect-all 保留其包内资源与许可文件。此接入不是虎牙官方 SDK，
不读取登录凭据，不处理付费、登录限制或 DRM 内容；平台页面变化可能影响可用性。

原项目以 LGPL-2.1 发布，允许修改与再分发，但需要保留许可、提供对应源码。
如果你打算把这套改动对外分享，建议先看 `docs/给原作者的授权咨询.md`（给原作者的说明草稿），
确认署名方式与许可选择；如果只是本地自用，这一条可以先不管。

Vulkan Runtime 1.4.363.0 来自 LunarG 官方可分发组件，使用 MIT / Apache-2.0 许可证。
发布包在 libmpv 同目录附带 x64 vulkan-1.dll 和 VulkanRT-License.txt，来源与 SHA256 见 ddm/assets/licenses/vulkan-SOURCE.json。
