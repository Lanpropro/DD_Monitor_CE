# 全屏独享声音

进入某一路直播的全屏模式时，自动静音其他所有播放格，并取消当前格的静音。
全屏按钮、右键「全屏查看」和 F 快捷键均生效，也包含被布局隐藏的格子。

当前格已有音量保持不变；如果音量为 0，则使用设置中的默认音量，默认音量
也为 0 或无效时使用 50%。退出全屏后保留这次声音选择，不恢复之前的多路声音。
全屏期间仍可手动调节音量或静音；本插件只在进入全屏时切换一次。
仅控制 DD 监控室内的直播格子。

## 安装

将本目录放入程序旁的 `plugins_user/`，然后重启 DD 监控室。
不需要重新打包 exe。若配置中设置了 `plugins_enabled` 白名单，需在其中加入
`fullscreen_audio`；默认配置会自动启用。

退出软件后移走本目录即可卸载。插件不修改 exe，也不更换播放器。

实现使用 v0.2 的 `WallGrid.set_fullscreen_tile` 入口，并通过 `Tile.set_muted`
和 `Tile.set_volume` 同步界面、播放器及配置。升级软件后应重新运行相关自检。

## 验证

在源码根目录运行：

```powershell
python dev/selfcheck_fullscreen_audio.py
```

安装项目运行依赖并配置 VLC 后，还可运行离屏 Qt/VLC 集成测试（不播放直播）：

```powershell
python dev/selfcheck_fullscreen_audio_ui.py
```
