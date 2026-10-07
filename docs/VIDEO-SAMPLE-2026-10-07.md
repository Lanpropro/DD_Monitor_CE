# 样片 02

用户已授权按修改后的脚本制作，本版使用 HyperFrames HTML、GSAP、真实录屏和指定的 Future Bass Tech Corporate — PaulYudin。没有直播原声或旁白。

- 成片：`videos/dd-monitor-ce-plugins-promo/renders/sample-v2.mp4`，60 秒、1920×1080、30fps、1800 帧。样片 01 文件保留供对比。
- 工程：`videos/dd-monitor-ce-plugins-promo/`；八个子场景分别可编辑，精确场景时间见 `index.html`。
- 预览：`http://127.0.0.1:3017/#project/dd-monitor-ce-plugins-promo`，交付时已检查 HTTP 200；本机服务停止后可按下方命令重启。
- 国内承担虚拟指针遍历、拉回及九格揭示，海外随后短展示。
- 末段本体总结：关注管理、画面弹幕、插件管理；不含跨平台或比赛二路等插件功能。
- 两处音乐静音：20.909–21.212 秒、28.485–29.091 秒，切口各 10ms 淡化，片尾淡出。
- 双解说原声位置：二路操作之后的 43.03–49.091 秒，约 6 秒。当前没有原声音轨，等待有声实录再替换该段画面、接入真实声音并压低配乐。

用户反馈的两处僵硬转场已调整：约 21 秒的三列遮挡限制在软件窗口内，进出运动各 0.55 秒；约 31 秒切换对齐素材时，延续上一段实录并在 0.6 秒内淡出。窗口位置和尺寸连续，音乐断点及其余段落不变，详见工程 `STORYBOARD.md`。

国内新素材仍缺，用旧 B 站实录占位，片中持续标注。海外采用新增整墙实录，画面含混合平台来源且已说明；本次没有逐格拼接。末段使用现有软件全景，标注待替换为对应本体更新录屏。九格依次亮起是剪辑遮罩，不代表加载性能。二路对照区与计时器直接来自实录，未重绘读数。

## 验证与复现

`dev/test_plugins_promo_sample.py` 验证场景连续、媒体范围、无直播音轨、每秒关键帧、导出规格、完整解码以及实际导出音频的两处静音与前后音乐；新增导出画面的切源连续性和转场外背景保持检查。与脚本测试一起执行，共 9 项通过。

最终 HyperFrames 检查的静态规则、运行时、布局、对比度及动画断言均通过，零错误、零警告。布局检查 11 个时间点，动画检查 300 个采样，验证开场与片尾入场、更新字幕顺序以及片尾不出界。动画映射辅助脚本因独立依赖下载迟迟未完成而中止，改用已安装 CLI 的动画断言与导出关键帧复核，没有将未生成的映射计为通过。

```powershell
python dev/prepare_plugins_promo.py
cd videos/dd-monitor-ce-plugins-promo
npm run check -- --at 1.5,6,15,19,24,30,34,39,46,53,58 --json
npm run dev -- --background --port 3017
npm run render -- --fps 30 --quality looks --output renders/sample-v2.mp4
cd ../..
python -m unittest dev.test_video_script_20261007 dev.test_plugins_promo_sample -v
```

先渲染再执行包含成片验证的测试。HTML 媒体由框架控制，关键帧已按每秒重新编码，便于 seek 与预览。检查与渲染日志、14 张导出关键帧总览保存在 `work/promo-sample-20261007/`。HyperFrames CLI 固定为 0.8.139；源码和来源清单提交 Git，录屏、配乐、字体与渲染二进制仅保留本机。重新准备资产需要原始素材；音乐许可信息见工程 `MEDIA.md`。

旧 ZIP 和旧视频工程保持原样。本次没有发布样片或修改软件业务代码。
