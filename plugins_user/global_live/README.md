# Twitch 与 YouTube

一个独立插件提供两个平台的公开直播，与“国内直播平台”分别启用。
在设置 → 插件中启用 **Twitch 与 YouTube**，按提示重启后，通过添加直播间输入官方链接。

## 使用

- Twitch：`https://www.twitch.tv/频道名`，也支持 `twitch:频道名`。
- YouTube 视频：`https://www.youtube.com/watch?v=直播视频ID`、`https://youtu.be/直播视频ID`、`/live/直播视频ID`。
  也可粘贴 `/shorts/直播视频ID`；资料接口仍会核对直播身份，普通短视频不会作为直播添加。
- YouTube 频道：`https://www.youtube.com/@频道/live` 或 `/channel/频道ID/live`；
  关注频道会在下次刷新/取流时解析该频道当前直播，适合继续观看后续直播。
  直接关注视频链接则固定该场直播，不会自动换到频道的另一场直播。

关注卡片支持昵称、标题、开播状态、头像与封面；拖入格子由 VLC 播放。
平台标识只用图标，关注栏仅有一个平台时隐藏。
人数不查询、不显示。网络失败保留上次开播状态。
关闭插件后关注及格子转为暂存，重新启用恢复位置和画质等设置。

画质菜单显示直播实际提供的 H.264 HLS 档位及其尺寸/帧率，并提供默认的“自动”。
自动模式从低档开始，用实际分片下载速度选择可流畅播放的最高档；
持续缓冲或带宽不足会降档，稳定播放后留出带宽余量再升档，切档设有冷却期。
按钮显示“自动 · 当前档位”，保存和重启保留自动模式，也可随时手动指定档位。
悬停预览独立选择最低视频档、静音，支持横屏卡片、竖屏卡片、列表及头像浮层；
预览不改变格子的手选画质。软件竖屏布局沿用现有实现，尺寸按流元数据读取。

聊天随主画面切换，支持普通文字和表情文字、屏蔽词、字号和保留数量。
Twitch 使用匿名只读 IRC WebSocket，处理 PING/PONG；YouTube 使用网页公开访客的聊天轮询。
不发送聊天，不读取浏览器登录资料/Cookie，不处理礼物、付费贴纸或聊天回放。
未启用 YouTube 聊天的直播显示对应提示，播放仍可使用。

## 实现范围

使用项目已固定的 Streamlink 8.6.1 解析公开直播 HLS，由 FFmpeg 复制音视频并转封装后交给 VLC。
不重新编码、不写录像文件、不保存带签名的媒体 URL 或访客 continuation。
播放、图片和聊天遵循当前系统/环境 HTTP 代理；需网络能够访问对应平台。
海外 HLS 经本机转发，清单/分片与取流使用相同 HTTP/TLS 栈及代理，
短暂网络错误重试三次；缓冲和画面停顿允许额外等待后再恢复格子。
匿名方式不覆盖需要登录、年龄验证、会员权限或地区授权的直播。
取流和 YouTube 聊天使用网页协议，平台变更可能需要更新插件；不是平台官方 SDK。

参考：[Streamlink 插件文档](https://streamlink.github.io/plugins.html)、
[Twitch IRC 协议](https://dev.twitch.tv/docs/chat/irc/)、
[YouTube 网页聊天协议研究实现](https://github.com/xenova/chat-downloader/blob/master/chat_downloader/sites/youtube.py)。
图标为平台官网 favicon，仅用于来源识别，出处见 `assets/platforms/README.md`。

## 验收

- `python dev/selfcheck_global_live.py`：离线链接、状态、头像封面请求头、真实竖屏尺寸/帧率、
  画质与预览隔离、Qt 添加/拖放/弹幕、图标、禁用暂存和恢复；本地真实网络服务验证 IRC 分帧、
  PING/PONG、YouTube 轮询/全部聊天 continuation、去重、Unicode、线程取消。
- `python dev/selfcheck_auto_quality.py`：带宽升降、缓冲降档、迟滞、手动/预览隔离、保存恢复与真实 Qt 取流接线。
- `python dev/selfcheck_auto_quality_live.py youtube:@LofiGirl` 或 `twitch:正在直播的频道`：
  真实分片下载与 VLC 播放、限速降档、取消限速后升档，以及进程/本机转发清理。
- `python dev/selfcheck_platform_quality_live.py twitch:sodapoppin` 或 `youtube:@LofiGirl`：
  逐档 VLC 解码、尺寸、保存值及进程释放。
- `python dev/selfcheck_platform_preview_live.py youtube:@LofiGirl 15`：
  四种预览形态、静音、持续解码、主格子不刷新和关闭/旋转/禁用后的资源释放；也可指定 Twitch。
- `python dev/selfcheck_live_danmaku_live.py 90 twitch:sodapoppin youtube:@LofiGirl`：
  真实聊天及及时退出。安静或已下播的房间需替换再验证。
- `python dev/selfcheck_huya_live.py youtube:@LofiGirl 90`：真实关注卡片/图片、
  拖放后的音视频解码与 PCM 音量/静音、连续播放、保存恢复和禁用后释放；同样支持 Twitch。
- `python dev/selfcheck_hls_proxy.py`、`python dev/selfcheck_stream_relay.py`：
  本机 HLS 转发、签名/相对地址/请求头/字节范围、重试、转封装参数和幂等清理。
- 上述自检设置 `DDM_NO_SAVE=1`，不修改用户配置；截图存放在 `work/<平台>-preview-live/`。
