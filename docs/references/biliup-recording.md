# biliup 录制与切片参考

> 类型：参考 ｜ 状态：已记录 ｜ 适用版本：当前开发版 ｜ 更新：2026-11-22 ｜ 读者：维护者、贡献者

用户提供的评论提到部分 B 站游戏直播的流格式与平时不同，并提及 biliup。现有截图没有直播间号、发生时间或流日志，具体输入格式仍待核实。

biliup 的官方文档明确列出 B 站 HLS 支持。默认下载器 `mesio` 支持 `hls_fmp4`，`stream-gears` 自 v1.3.0 起支持 HLS TS 和 fMP4。研究时核对的是 v1.3.5 发布说明、官方文档和公开修复记录。读取资料和本项目离线回归是本次证据，尚未运行 biliup 或用原评论中的直播实测。 [biliup 仓库](https://github.com/biliup/biliup) · [v1.3.5 发布说明](https://github.com/biliup/biliup/releases/tag/v1.3.5) · [HLS 常见问题](https://doc.biliup.rs/guide/getting-started/%E5%B8%AE%E5%8A%A9/faq.html)

## 本项目已有处理

- 本体的 B 站 H.264 取流按 App FLV → 同一次响应里的 App HLS → 旧网页接口尝试。提交 `f85ae797` 补上了 App FLV 的 CDN 全部失败后尝试 HLS 的步骤。回退顺序、请求头、实际画质及菜单档位已有离线用例。 [取流实现](../../ddm/bili.py) · [专项用例](../../dev/selfcheck_bili_codec.py)
- 本体默认由 FFmpeg 复制源编码，再按录制配置选择输出封装。DDCut Replay 的切片素材另写为本地 HLS，H.264／HEVC 用 TS，AV1 用 fMP4，并保存初始化段。源流走 FLV 或 HLS 与本地归档选用哪种封装属于两个阶段。 [本体录制参数](../../ddm/recording_output.py)

## 可借鉴的做法

1. **按输入格式验证断流后的录制完整性。** biliup 对未完成的录像区分格式。FLV／TS 保留能播放的内容，fMP4 保留初始化段和完整分片。它还用回归测试覆盖上游 DTS 回退或归零。对我们而言，优先核查录制中切源、断流和续录，分别确认前一段可播放、音画仍对齐、选区可导出，并记录丢失范围。用离线样本覆盖分支，用真实房间单独验证问题。 [未完成的录像](https://doc.biliup.rs/guide/getting-started/%E9%85%8D%E7%BD%AE/global-config.html#未完成的录像) · [时间戳修复 PR](https://github.com/biliup/biliup/pull/1802)
2. **按文件引用和实际占用判断可回收空间。** biliup 将处理产物与来源文件的关系写入数据库，重启后仍可判断一个中间文件是否被多个成品使用。本体已有剩余空间检查和分段租用。若将来扩展清理，可先列出文件大小、预计释放量和引用来源，优先考虑可重建且无人引用的缓存。biliup 的紧急低空间模式可能清理到被引用的旧分段，这条规则不宜直接沿用。 [本体分段保留](../../ddm/recording_replay.py) · [biliup 存储与清理](https://doc.biliup.rs/guide/getting-started/%E9%85%8D%E7%BD%AE/global-config.html#存储与清理)
3. **按场次浏览短时间续播。** biliup 可把同一主播的相邻录制归到同一条时间轴，标出停录缺口，原文件仍各自保留。DDCut 已能标记清单断点，可借鉴的是录像库的场次视图及跨录播定位。 [biliup 剪辑台](https://doc.biliup.rs/guide/webui/usage.html)
4. **在快速剪前显示可落刀的关键帧。** biliup 维护关键帧索引，并向回看界面提供查询。DDCut 的快速复制已有关键帧前滚，可参考其界面反馈，显示请求入点、实际可落刀入点和前滚时长。 [会话及关键帧索引发布记录](https://github.com/biliup/biliup/releases/tag/v1.2.9) · [关键帧接口](https://doc.biliup.rs/guide/api/rest-api.html)
