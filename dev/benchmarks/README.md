# 性能基准

从仓库根目录执行，需要开发依赖和 Windows 图形环境。

| 工具 | 测量范围 |
| --- | --- |
| [benchmark_danmaku_frames.py](benchmark_danmaku_frames.py) | 可见四格弹幕绘制间隔与定时精度对照，会显示窗口 |
| [benchmark_video_danmaku_render.py](benchmark_video_danmaku_render.py) | 本地生成测试视频，对照 raster 与 Quick 的帧回调和进程 CPU 时间 |

```powershell
python dev/benchmarks/benchmark_danmaku_frames.py --seconds 3
python dev/benchmarks/benchmark_video_danmaku_render.py --backend quick --seconds 3
```

这些工具测量 Qt 回调和进程工作量，不证明 DWM 的最终呈现帧率，也不替代真实直播验收。它们不在默认检查套件内。
