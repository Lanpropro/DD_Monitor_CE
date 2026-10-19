# PR #11、#12 本地集成测试

日期：2026-10-18。

后续：2026-10-19 已核对 #11、#12、#13 最新提交并补充整合测试，见[仓库与 PR 整合记录](repository-integration-20261019.md)。以下保留首次移植时的记录。

## 集成范围

- 在 `a30666f` 的 libmpv、Qt Quick 与 XAnimator 实现上，依次移植两份 PR 的功能提交。
- 包含 #11 的 `08f5725` 启动取消清理修复，以及 #12 截至 `41c5b5a` 的全部功能提交。
- 保留当前播放器、弹幕绘制文件、编解码状态重置、弹幕按钮提示及 `run.cmd` Quick 开关。
- 未操作 GitHub 合并按钮、推送或打包 EXE。

## 自动验证

20 个相关验证脚本最终均以退出码 0 完成：

`selfcheck_bili_cookies`、`selfcheck_danmaku_connection`、
`selfcheck_danmaku_room_switches`、`selfcheck_danmaku_send`、
`selfcheck_danmaku_composer`、`selfcheck_emoticon_tabs`、
`selfcheck_video_danmaku`、`selfcheck_video_danmaku_controls`、
`selfcheck_audio_cycle_shortcut`、`selfcheck_fullscreen_cursor`、
`selfcheck_tile_fullscreen`、`selfcheck_light_refinements`、
`selfcheck_danmaku_button`、`selfcheck_danmaku_smoothness`、
`selfcheck_danmaku_retention`、`selfcheck_repository_map`、`selfcheck_mpv`、
`selfcheck_video_danmaku_quick`、`selfcheck_danmaku_render_thread`、
`check_live_danmaku_motion`。

前六个核心脚本共 81 项测试。新增房间切换的编解码状态、输入栏房间号和弹幕提示回归；
全屏测试适配现有底栏滑出动画，浅色图标测试明确模拟未悬停状态。
仓库资料清单补齐现有开发工具和网站原型路径。

测试进程设置 `DDM_NO_SAVE=1`，并沿用主程序的 WMI 查询回退。
普通控件测试离屏执行；播放器和 Quick 测试使用 Windows 原生窗口。
原生测试保持 MTA 资源至 Qt 清理完成。未读取真实登录凭据或执行真实弹幕发送。
日志位于本机忽略目录 `work/pr11-pr12-tests/`。

## 真实直播验证

公开房间 `1883358196`，未登录：1280×720、30 FPS、D3D11VA。

- 收到并接受 7 条真实弹幕。
- 场景位置更新间隔中位数 4.16 ms，95 分位 4.47 ms。
- GUI 阻塞 350 ms 时记录到 82 个不同位置，移动 44.20 px，预期 45.26 px。
- 测量对象为屏幕外场景图；桌面最终显示效果仍需人工实测。

## 人工实测

1. 关闭旧实例，双击仓库中的 `run.cmd`。旧 EXE 尚未重新打包。
2. 查看真实直播间的滚动弹幕、暂停恢复、全屏输入和底栏收起。
3. 旧登录若提示缺少 `bili_jct`，退出 B 站账号并重新登录。
4. 在目标房间输入文字，测试回车发送、小表情插入和大表情发送。
5. 退出重启，检查登录保持和不同房间的弹幕开关。

集成前回退点为 `a30666f`；各移植提交和测试调整均保留独立 Git 记录。
