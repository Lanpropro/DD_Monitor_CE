# 2026-10-19 已验收界面与性能改动集成

## 基线与范围

集成基线为 `develop` 的 `9f174c0`，已包含 #18（500ms 预览）、#19（按时长分段录制）和 #20–#22（PR 模板、smoke CI、测试矩阵及插件边界）。

用户已确认近期功能、关注栏滚动、设置切页动效与录制页内部滚动通过。本次汇总 `function/manual-integration` 中尚未进入 develop 的后续修改；分支历史保留为追溯依据，不重复合入已经进入 develop 的 #18／#19 提交。

| 范围 | 后续改动 | 主要来源提交 |
| --- | --- | --- |
| 悬停预览 | 提前取流、准备播放器、静音预览缩短流分析等待 | `03d4d37`、`4f3e78b` |
| 格子边缘 | 圆角指示、平滑边缘及与底栏的前后关系 | `18dd177`、`14cb7fc` |
| 表情 | 按账号／直播间持久化分类缓存、恢复分类图标、普通表情首分类的本地图标 | `fb48625`、`192be9b` |
| 通知 | 按类别选择持续显示、向下堆叠、保留关闭按钮、主播头像；开播通知只填入可见空格，无空位则关闭 | `cabd8cd`、`c3551e6`、`14fc68d`、`e70b278` |
| 性能与设置 | 透明边框上传复用、背景视频帧转换后台化、设置窗口释放、切页快照合成、录制设置内部滚动 | `7ad35ec`、`790fa11`、`b61f783`、`9b9a18e` |

## 合并处理

- 保留 develop 已有的 PR 模板、CI、必跑测试矩阵和插件源码边界。
- 预览与录制的冲突保留用户已验收的后续实现：提前取流及录制／导出通知的主播快照；对应测试同步保留。
- 待办文档更新为实际验收状态，不再把已确认的预览、通知和卡顿优化记为未完成。

## 验证入口

使用合成房间、临时缓存和隔离录制输出；不读取真实账号，不向真实直播间发送消息。各命令结果记录在集成 PR。

- `python dev/run_checks.py --suite repository`
- `python dev/run_checks.py --suite smoke --timeout 120`
- `python dev/run_checks.py --suite offline`
- `python dev/run_checks.py --suite native`
- 设置动效与滚动：`dev/selfcheck_settings_transition.py`、`dev/selfcheck_ui_motion.py`；缩放覆盖 100%、150%、200%。
- 预览／缓存：`dev/selfcheck_preview.py`、`dev/selfcheck_emoticon_tabs.py`、`dev/selfcheck_danmaku_composer.py`。
- 录制／回放：`dev/selfcheck_recording.py`、`dev/selfcheck_recording_shutdown.py`。
- 背景视频和滚动：`dev/selfcheck_skins.py --playback-only`、`dev/selfcheck_sidebar_performance.py`。
- 编译应用源码与 `git diff --check`。

原生界面检查顺序执行，避免多个可见测试争用桌面影响时序判断；smoke 只验证功能契约，不能作为视觉帧率或任意网络环境下播放性能的保证。

## 本轮边界

不构建便携包或 EXE，不创建标签和 GitHub Release，不修改软件版本号，不向 main 发起发布合并。卡片自定义优先级仍待明确。本机 AGENTS.md 和随手想法文件不进入本次提交。
