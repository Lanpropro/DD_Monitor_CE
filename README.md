# DD 监控室 CE

多窗口 B 站直播监控：左边是关注列表，右边是画面墙，一路一个格子，可以同时挂十几个直播间。

CE = Community Edition。这是 [DD监控室](https://gitee.com/zhimingshenjun/DD_Monitor_latest)（原作者：智明神君）的二次开发版本，
**界面层全部重写**，取流与 B 站接口的调用逻辑参考原项目实现；播放仍然走 python-vlc + libvlc。

## 怎么跑

1. 准备环境并装依赖：

   ```bash
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

2. 补齐 VLC 运行库（见下一节，缺了不出画面）。

3. 启动：

   - 双击 `run.cmd`：正常使用，不开控制台
   - 双击 `run-console.cmd`：带控制台，能直接看到取流/重连日志
   - 或者命令行 `python main.py`

第一次打开是空的，点左下角「+ 添加直播间」填房间号，或者用「导入关注」从 B 站账号导入。

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
  app.py           应用外壳：侧栏 + 画面墙、设置、快捷键、轮询
  widgets.py       侧栏、画面格子、画面墙、布局选择器、各种浮标
  dialogs.py       设置窗口、添加直播间、导入关注
  bili.py          B 站接口：房间信息、取流地址、关注列表、在线人数
  player.py        VLC 播放封装（直连 http FLV，带 Referer/UA）
  login.py         扫码登录；web_login.py 内置浏览器账号密码登录
  layouts.py       布局定义与缩略图
  images.py        头像异步下载与缓存
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

- `dev\run-checks.cmd`：跑一遍全部自检（当前 12 个，全部通过）
- `dev\selfcheck_*.py`：功能自检，比如侧栏拖动排序、布局切换、设置是否真的生效、人数显示、下播保留格子等
- `dev\preview_*.py`：把界面渲染成 PNG 存到 `dev\preview\`，改完样式拿这个看效果

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
