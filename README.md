# DD 监控室 CE

多窗口 B 站直播监控：左边是关注列表，右边是画面墙，一路一个格子，可以同时挂十几个直播间。

CE = Community Edition。这是 [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest)（原作者：智明神君）的二次开发版本，
**界面层全部重写**，取流、B 站接口与弹幕接入参考原项目实现；播放仍然走 python-vlc + libvlc。

## 怎么跑

1. 准备环境并装依赖：

   ```bash
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

2. 补齐 VLC 运行库（见下一节，缺了不出画面）。

3. 启动：

   - 双击 `run.cmd`：正常使用，不开控制台
   - 双击 `run-console.cmd`：带控制台，能直接看到取流/重连/弹幕的日志
   - 或者命令行 `python main.py`

第一次打开是空的，点左下角「+ 添加直播间」填房间号，或者用「导入关注」从 B 站账号导入。

## 弹幕

弹幕占画面墙里的一整格（布局菜单里有专门的「弹幕布局」那一栏，比如「主画面 + 弹幕」），
显示的是**主画面那一路**的弹幕：换台、切布局都会自动跟着换，切到普通布局就自动断开，不占资源。

- 普通弹幕、礼物、上舰、醒目留言（SC）都会进面板，颜色区分：弹幕蓝、礼物粉、上舰紫、SC 橙。
- 面板右上角显示连接状态和已收到的条数（连接中… / 已连接 / 重连中…）。
- **建议先登录**：没登录时 B 站会把别人的昵称打码，面板上看到的用户名就是星号。
- 实现放在 `ddm/danmaku.py`：一个后台线程跑一个 asyncio 循环，用 `blivedm` 收发；
  服务器地址和 token 走 `room/v1/Danmu/getConf`（官方新的 `getDanmuInfo` 现在一律返回 -352 风控，
  老接口还正常，详见 `ddm/bili.py` 里的 `danmaku_conf`）。

## 关于 VLC 运行库（没放进仓库）

播放依赖 VLC 3.x 的 `libvlc.dll`、`libvlccore.dll` 和 `plugins\` 目录。它们体积大（约 80MB）且属于第三方二进制，
所以没有进版本库，需要自己补上，两种办法都行：

- 从 DD监控室 原仓库根目录把这三样拷到本项目根目录；
- 或者装一个 VLC 3.x，把安装目录下的 `libvlc.dll`、`libvlccore.dll` 拷过来，并一并拷 `plugins\`。

`main.py` 会自动把 `PYTHON_VLC_LIB_PATH` 指向项目里的 `libvlc.dll`；这三样没补齐的话，程序能开但每一路都会取流失败。

## 目录里有什么

```
main.py            启动入口（先设好 libvlc 路径再拉起界面）
run.cmd            双击启动（无控制台）
run-console.cmd    带控制台启动
publish.cmd        提交并推送到 GitHub
ddm/               界面与业务代码
  theme.py         设计令牌与全局样式（配色/圆角/字号参考 BewlyCat）
  app.py           应用外壳：侧栏 + 画面墙、设置、快捷键、轮询、弹幕接谁
  widgets.py       侧栏、画面格子、画面墙、布局选择器、弹幕格、各种浮标
  dialogs.py       设置窗口、添加直播间、导入关注
  danmaku.py       弹幕接入（blivedm + 后台线程）
  bili.py          B 站接口：房间信息、取流地址、关注列表、在线人数、弹幕服务器
  player.py        VLC 播放封装（直连 http FLV，带 Referer/UA）
  login.py         扫码登录；web_login.py 内置浏览器账号密码登录
  layouts.py       布局定义与缩略图
  images.py        头像异步下载与缓存
blivedm/           弹幕协议库（上游 xfgryujk/blivedm，原仓库自带的那份）
favicon.ico        程序图标
utils/config.json  你的配置：关注了哪些房间、画面墙、每格音量/画质等
logs/              运行日志（按天一个文件，启动时自动创建）
dev/               开发用的自检脚本和界面预览脚本
```

## 配置与日志放哪

- 配置：`utils/config.json`（关窗时写入，写入前把上一次备份成 `config.json.bak`）
- 日志：`logs/ddm-YYYY-MM-DD.log`
- 头像缓存：`cache/avatars/`

这几个都是运行期产生的，换机器直接删掉即可，不影响程序。注意 `utils/config.json` 里**包含登录凭证**，
所以它在 `.gitignore` 里，不会被提交。

## 开发

`dev/` 下的脚本都是离屏跑的（不弹窗口，也不动你真实配置，靠 `DDM_NO_SAVE=1`）：

- `dev\run-checks.cmd`：跑一遍全部自检（当前 13 个，全部通过）
- `dev\selfcheck_*.py`：功能自检，比如侧栏拖动排序、布局切换、设置是否真的生效、人数显示、下播保留格子、弹幕连谁/换台重连等
- `dev\preview_*.py`：把界面渲染成 PNG 存到 `dev\preview\`，改完样式拿这个看效果
- `dev\probe_danmaku_live.py`：联网实测弹幕（从关注列表挑一个正在直播的房间，收 25 秒弹幕）

改动集中在 `ddm/theme.py`（样式）和 `ddm/widgets.py`（控件）里，改完先跑自检，再看预览图。

## 更新到 GitHub

双击 `publish.cmd`（会依次 `git add` / `commit` / `push`），或者手动：

```bash
git add -A
git commit -m "这次改了什么"
git push
```

`.gitignore` 里已经排除：`utils/config.json`（含凭证）、`libvlc*.dll`、`plugins/`、`logs/`、`cache/`、`dev/preview/`、`__pycache__/`。

## 许可与来源

本仓库是 DD监控室 的二次开发产物，原项目以 **LGPL-2.1** 发布，详见 `LICENSE` 与 `NOTICE.md`。
