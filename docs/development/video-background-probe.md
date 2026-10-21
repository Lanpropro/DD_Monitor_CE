# 原分辨率视频背景合成试验

## 状态与边界

2026-10-22：独立诊断原型，**未替换正式软件的背景后端**，不修改设置、启动脚本或视频素材。不重新引入 1080p/15fps 副本方案。相关工作继续归入 PR39。

正式路径是 `QMediaPlayer → QVideoSink → QVideoFrame.toImage → QPainter`。试验路径使用同一个原分辨率源，经 `QMediaPlayer → VideoOutput → QQuickWidget` 合成。没有应用层逐帧转 QImage，不等于已经证明驱动内部零拷贝；也没有测量 GPU 功耗或总占用。

## 重复执行

使用项目虚拟环境，先把仓库根目录加入 PATH（libmpv），设置 `QT_QPA_PLATFORM=windows`、`DDM_CHECK_MODE=offline`。分别启动两个独立进程，不能在同一进程切换后端，也不要并发采样：Quick 控件会改变渲染环境，CPU 竞争会污染结果。

```powershell
python dev/checks/bootstrap.py dev/selfcheck_skin_video_probe.py --backend raster --wall --width 3840 --height 2160
python dev/checks/bootstrap.py dev/selfcheck_skin_video_probe.py --backend quick --wall --width 3840 --height 2160
python dev/checks/bootstrap.py dev/selfcheck_danmaku_render_thread.py
python dev/checks/bootstrap.py dev/selfcheck_danmaku_render_thread.py --quick-widget
```

探针只生成临时 3840×2160/30fps H.264 测试视频、两路 640×360 本地 libmpv 视频；不读取账号或安装中的插件，不发弹幕，强制关闭配置保存，并使用临时配置路径。生成测试片不属于对用户视频进行转码。无 `--wall` 时使用简化半透明侧栏；有该参数时使用软件真实 1+5 画面墙。不会停止用户正在运行的软件。

每轮启动预热后采样 5 秒，结束时断言原始源路径和 4K 尺寸、视频持续变化、静音、暂停/恢复、两路模拟直播持续播放与 HWND 不变；Quick 路径另检查 GPU 后端、遮罩颜色和应用层转换次数为零。截图读回发生在采样之前。

## 本机初步结果

环境：PySide6 6.11.2，Quick 为 Direct3D11，DPR=1.5。请求 3840×2160 窗口后，系统实际客户区为 3629×1687 逻辑像素；两种后端均使用这个实测视口，不能将其描述为精确 4K 输出或全屏测量。视频源始终为 3840×2160。

| 真实画面墙 + 两路模拟直播 | Raster 第1/2/3轮 | Quick 第1/2/3轮 |
| --- | --- | --- |
| CPU 单核等效占用（%） | 152.67 / 125.52 / 128.08 | 13.10 / 15.58 / 15.62 |
| 10ms 事件探针间隔 P95（ms） | 33.09 / 29.74 / 33.02 | 11.12 / 11.39 / 11.13 |
| Python 帧转换次数 | 88 / 85 / 90 | 0 / 0 / 0 |

CPU 指标是 `process_time / wall_time × 100`，包含该进程内线程，允许超过 100%，不是任务管理器的整机百分比。三轮中位数从 128.08 降到 15.58，约减少 88% 的进程 CPU 时间；仅适用于本机合成负载，不承诺真实直播或其他显卡也有相同比例。事件探针不是显示帧率或最终 DWM 呈现延迟。

旧路径的帧转换 P95 为 18.32–20.65ms，绘制 P95 为 6.44–7.62ms。两个数不能直接相加当作主线程耗时：转换在后台线程执行。

弹幕场景对照中，界面线程暂停 350ms 时，原路径与额外加入 QQuickWidget 的进程均采到 84 个不同场景位置，位移约 35px。说明此版本下未复现“独立弹幕窗口随界面阻塞停住”；它是离屏场景图检查，不等于桌面可见的合成验收，也不能消除 Qt 文档所述线程循环限制。

## 下一阶段验收要求

- 正式集成先使用显式实验开关，保留 Raster 回退；默认启用前单独验收。
- 补齐图片/视频切换、静态首帧、设置页缩略预览、主题/遮罩、最小化、关闭、解码错误的生命周期。
- 实际验证 1+5/九格切换、Del 清空、卡片拖入/排序、弹幕、通知和窗口缩放，不以探针的 HWND 断言代替这些交互。
- 检查高 DPI、跨屏、实际高码率/HEVC/HDR 素材和不同显卡；记录 GPU 占用及功耗，避免只是把 CPU 压力转移到 GPU。
- QQuickWidget 有额外离屏合成成本，不调用其 `winId()`，不使用 `WA_AlwaysStackOnTop` 破坏控件层级。

## 依据

- [Qt QQuickWidget：性能与堆叠限制](https://doc.qt.io/qt-6/qquickwidget.html)
- [Qt VideoOutput：videoSink 与 PreserveAspectCrop](https://doc.qt.io/qt-6/qml-qtmultimedia-videooutput.html)
- [Wallpaper Engine：默认 GPU 视频解码](https://help.wallpaperengine.io/en/videos/performance.html)
- [DSH 视频通道](https://github.com/elysia395/dsh-wallpaper-engine/blob/main/src/video-layer.js)
- [DSH 原分辨率限帧转码实现](https://github.com/elysia395/dsh-wallpaper-engine/blob/main/lib/transcode.js)
