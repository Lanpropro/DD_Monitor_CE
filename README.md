# DD 监控室 CE

多窗口 B 站直播监控。

这是 [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest)（原作者：[执明神君](https://space.bilibili.com/637783)）的二次开发版本，
**尝试性重构了 UI 以及部分功能**。

## 怎么跑

> 以下命令以 **Windows** 为例。需要 **Python 3.10+**，只支持 Windows。

1. 装 Python 依赖：

   ```bash
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

2. 补齐 VLC 运行库（见下方「关于 VLC 运行库」一节）。
   没补齐的话程序能开，但每一路都会取流失败。

3. 启动：

   - 双击 `run.cmd`：正常使用，不打开控制台。
   - 双击 `run-console.cmd`：带控制台，能直接看到取流、重连和弹幕日志。
   - 或者在命令行运行 `python main.py`。

第一次打开是空的，点左下角「+ 添加直播间」填直播间号（或长短链网址），或者用「导入关注」从 B 站账号导入。

## 多种可选布局

点击侧栏中的「布局预设」即可切换画面墙布局。布局分为「普通布局」和「弹幕布局」两组。

### 普通布局

| 类型 | 可选布局 |
| --- | --- |
| 自动 | 根据窗口大小自动决定行列 |
| 等分 | 单画面、上下两分、左右两分、四分、六分、九分 |
| 主画面 | 主画面 + 2/3/4/6 小画面 |
| 特殊排布 | 上 1 大 + 下 2、左 2 小 + 右 1 大、一大 + 一圈小、两大 + 侧 4 小 |

### 弹幕布局

| 可选布局 | 说明 |
| --- | --- |
| 主画面 + 弹幕 | 左侧显示直播，右侧整格显示弹幕 |
| 上 1 大 + 小画面 + 弹幕 | 上方为主画面，下方为小画面和弹幕 |
| 主画面 + 1/2/3 小 + 弹幕 | 主画面在左，小画面和弹幕在右侧排列 |
| 弹幕在左 + 主画面 + 2 小 | 弹幕、主画面和两个小画面并排 |

弹幕格会跟随当前主画面的直播间；切换主画面或弹幕布局后，弹幕会自动同步。如果直播间数量超过当前预设的格子数，额外画面会按相同列数继续向下排列。

## 关注列表排序

现有三种「排序」模式内置：

| 方式 | 说明 |
| --- | --- |
| 自定义顺序 | 自己拖出来的顺序，**会存进配置**，切换排序方式或重开程序都不会丢 |
| 开播优先 | 直播中的排在前面（同组内保持原顺序），每次刷新状态后自动重排 |
| 导入顺序 | 按加入关注的先后排 |

置顶的直播间永远排在最前面；手动拖动列表会自动切回「自定义顺序」。

## 关于 VLC 运行库（没放进仓库）

播放依赖 VLC 3.x 的 `libvlc.dll`、`libvlccore.dll` 和 `plugins\` 目录。这些文件没有进入版本库，需要自行补齐，两种方式均可：

- 从 DD监控室原仓库根目录把这三项复制到本项目根目录；
- 或者安装 VLC 3.x，把安装目录下的 `libvlc.dll`、`libvlccore.dll` 和 `plugins\` 一并复制过来。

`main.py` 会自动把 `PYTHON_VLC_LIB_PATH` 指向项目里的 `libvlc.dll`；这三样没补齐的话，程序能开但每一路都会取流失败。

## 目录里有什么

```
main.py            启动入口（先设好 libvlc 路径再拉起界面）
run.cmd            双击启动（无控制台）
run-console.cmd    带控制台启动
publish.cmd        提交并推送到 GitHub
ddm/               界面与业务代码
  theme.py         设计令牌与全局样式（配色/圆角/字号参考 BewlyCat）
  app.py           应用外壳：侧栏 + 画面墙、设置、快捷键、轮询、弹幕接谁、悬停预览
  widgets.py       侧栏、画面格子、画面墙、布局选择器、弹幕格、各种浮标
  dialogs.py       设置窗口（常规 / 弹幕 / 快捷键）、添加直播间、导入关注
  preview.py       悬停预览小窗（静音、低画质、随鼠标进出）
  danmaku.py       弹幕接入（blivedm + 后台线程）
  bili.py          B 站接口：房间信息、取流地址、关注列表、在线人数、弹幕服务器
  player.py        VLC 播放封装（直连 http FLV，带 Referer/UA）
  login.py         扫码登录；web_login.py 内置浏览器账号密码登录
  layouts.py       布局定义与缩略图
  images.py        头像与表情图下载、缓存
blivedm/           弹幕协议库（上游 xfgryujk/blivedm，原仓库自带的那份）
favicon.ico        程序图标
utils/config.json  你的配置：关注了哪些房间、画面墙、每格音量/画质、弹幕设置、排序方式等
logs/              运行日志（按天一个文件，启动时自动创建）
dev/               开发用的自检脚本和界面预览脚本
```

## 配置与日志放哪

- 配置：`utils/config.json`（关窗时写入，写入前把上一次备份成 `config.json.bak`）
- 日志：`logs/ddm-YYYY-MM-DD.log`
- 头像与表情缓存：`cache/avatars/`、`cache/emoticons/`

这几个都是运行期产生的，换机器直接删掉即可，不影响程序。注意 `utils/config.json` 里**包含登录凭证**，
所以它在 `.gitignore` 里，不会被提交。

## 开发

`dev/` 下的脚本都是离屏跑的（不弹窗口，也不动你真实配置，靠 `DDM_NO_SAVE=1`）：

- `dev\run-checks.cmd`：跑一遍全部自检
- `dev\selfcheck_*.py`：功能自检，比如侧栏拖动排序、布局切换、设置是否真的生效、人数显示、下播保留格子、
  弹幕连谁/换台重连、粉丝牌与表情渲染、字号滑块、条数上限、排序持久化、悬停预览的延迟与静音等
- `dev\preview_*.py`：把界面渲染成 PNG 存到 `dev\preview\`，改完样式拿这个看效果
- 需要联网的专项检查：`dev\probe_danmaku_live.py`（弹幕）、`dev\check_emoticon_live.py`（表情图下载）、
  `dev\check_preview_live.py`（悬停预览抓帧）、`dev\check_medal_size.py`（粉丝牌尺寸）

改动集中在 `ddm/theme.py`（样式）和 `ddm/widgets.py`（控件）里，改完先跑自检，再看预览图。

## 许可与来源

本仓库是 DD监控室的二次开发产物，原项目以 **LGPL-2.1** 发布并已获得原作者同意，详见 [`LICENSE`](LICENSE) 与 [`NOTICE.md`](NOTICE.md)。
