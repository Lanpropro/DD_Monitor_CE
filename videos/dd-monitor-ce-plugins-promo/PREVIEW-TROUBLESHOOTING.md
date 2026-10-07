# 预览 `limited` 修复记录

2026-10-08，用户在播放和拖动时间轴时反复收到 `limited`。
临时诊断保留原始 `console.error` 并取得用户报错预览的真实调用栈：

```text
isLimited (chrome-extension://eilkilgemogpkebfmhkkapogkiijikli/vt.zh-cn.user.js:537:21)
VideoTogetherExtension.VideoClicked (.../vt.zh-cn.user.js:4152:18)
```

来源是 Edge 中的 VideoTogether（一起看）3.0.23。它给所有视频注册
`play pause seeked` 监听器，5 秒内超过 15 次请求就把限流记录为控制台错误。
多个视频随时间轴一起跳转会触发这个条件。没有该扩展的诊断浏览器无法复现。

`index.html` 的 `preview-media-isolation` 只处理当前合成 `#root video`：
使用扩展已有的 `VideoTogetherDisabled` 标志退出同步候选列表，移除扩展实例
`VideoClickedListener` 注册的三个监听器。DOM 观察器的微任务在扩展观察器之后
执行，覆盖扩展晚注入和子场景动态挂载。框架自己的监听器、控制台和其他视频保留。
这是针对已核实版本的页面兼容处理；如果未来扩展更改实例或监听器名称，需重新核对。

用户已在原来报错的浏览器刷新、播放和拖动，确认“刷新后不再出现”。临时诊断脚本
已移除。测试 `dev/test_promo_videotogether.cjs` 先复现限流，再验证已有实例、晚注入、
两种观察器顺序、框架事件、真实错误及合成外视频的行为。

素材、时间轴与样片 07 的导出内容没有改动，此修复无需重新编码视频。
