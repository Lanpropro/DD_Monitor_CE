# 参考项目与学习记录

> 类型：索引 ｜ 状态：维护中 ｜ 适用版本：全部版本 ｜ 更新：2026-11-21 ｜ 读者：维护者、贡献者

本页汇总维护者要求学习或参考的项目，记录研究程度、可借鉴的内容和本项目中的去向。详细研究仍放在对应专题文档；列入本页只表示曾被提出或研究，不表示功能已实现，也不表示复用对方代码。

| 项目 | 来源与学习范围 | 记录状态 | 本项目中的去向 |
| --- | --- | --- | --- |
| [BewlyCat](https://github.com/keleus/BewlyCat) | 主题色、设置卡片与控件层次、Dock 和开关动效等界面参考 | 已对照具体界面及部分公开组件；记录散见[界面组件](../development/ui-components.md)、[皮肤文档](../features/skins.md) | 已用于部分界面设计；具体已发布范围以版本说明和源码为准 |
| [dsh-wallpaper-engine](https://github.com/elysia395/dsh-wallpaper-engine) | 背景媒体、主题遮罩、半透明面板的分层思路 | 设计参考，见[皮肤文档](../features/skins.md)与[早期外观计划](../archive/customization-plan-202610.md) | 本体使用自身的 Qt 绘制路径，不接入该项目 |
| [BiliBili ShadowReplay](https://github.com/Xinrea/bili-shadowreplay) | 录播档案、增长中的回看时间轴、切片选区、素材和任务状态 | 2026-11-04 完成首轮源码研究；详见[研究记录](../archive/bili-shadowreplay-learning.md) | 已决定沿用本地 HLS 归档思路；后续功能以实际提交和验收记录为准 |
| [直播水族馆](https://github.com/maofanyi/LiveAquarium-Releases) | 请求调度、全墙弹幕负载、布局过渡、回溯和音频交接 | 2026-11-04 完成设计研究；详见[研究记录](../archive/liveaquarium-learning.md) | 暂停竞品研究；候选方案需按具体故障与真实采集重新评估 |
| [Fy1Sync](https://github.com/Fy1ng/Fy1Sync) | 双路播放、时间偏移，以及 YouTube 首次登录流程 | 曾阅读 v0.3.1／v0.3.2 发布记录；2026-11-10 对固定提交 `fc875cc3` 的登录、Cookie 和取流代码作只读核对 | 参考独立浏览器登录的流程思路；该项目未提供两平台关注导入现成实现，未复制其代码。来源记录见本机 `docs/local/archive/handoffs/GLOBAL-LIVE-HANDOFF-20261110.md` |
| [FreeCast](https://github.com/Sur4lis/FreeCast) | 双路播放时逐路音量及可选人声分离 | 2026-11-02 只读参考 v1.21、提交 [`e8d080e`](https://github.com/Sur4lis/FreeCast/blob/e8d080e10971e31bf957763d0d625762366e6832/browser-extension/ui/dual-vocal.js) 的逐路音量实现 | 作为二路音频设计参考；本项目未引入 FreeCast。来源记录见本机 `work/domestic-functional-modules/tests/README_match_sync_performance.md` |
| [Notebook Navigator](https://github.com/johansan/notebook-navigator) | 左侧直播间／文件夹选项的自定义图标、颜色和背景交互 | 用户提供的参考项目，尚无专项研究结论 | 需求保留在本机 `docs/local/idea.md`，实现范围待设计 |
| [PureLive（纯粹直播）](https://github.com/wzgrx/PureLive) | 多平台直播聚合、多画面、小窗和录制等局部功能的候选参考；范围仅据项目 README 介绍 | 用户于 2026-11-18 提出；已浏览公开 README，未做源码研究或运行验证 | 维护者整体不看好，低优先级备查；遇到具体问题时再核对可能有用的局部内容，暂不安排深入研究或引入 |
| 浏览器二路融合扩展 0.17.1 | 二路观看交互参考；公开项目来源未记录，本机留有 `work/external-review/bili-fusion-0.17.1/` | 已查看本地扩展资料和候选交互 | 相同弹幕计数、SC 延迟及状态提示等待设计；已具备的屏蔽和位置控制不重复列为待办 |
| [木东渐变网站](https://mudong-gradient.pages.dev/) | 用户于 2026-11-16 指定的软件渐变颜色参考，配套视频为[《什么是电影感的渐变？》](https://www.bilibili.com/video/BV12rWD6SEPy/) | 已核对视频公开页及简介；网站本次访问受 DNS／代理连接失败影响，页面与工具功能待核对 | 作为主题与美化的渐变选色参考；具体记录见下方[渐变颜色参考](#渐变颜色参考) |

## B 站参考视频

以下分别记录已核对的视频页和历史录像线索；“画中画连续缩放录像”的现有记录仍无法判断是 B 站视频页，还是用户录制的 B 站播放画面：

| 记录 | 参考内容 | 来源状态 |
| --- | --- | --- |
| 画中画连续缩放录像 | 缩放期间实时播放并保持各路比例；见[画中画设计](../features/picture-in-picture.md#验证与验收) | 用户曾提供参考录像；来源类型、原标题、BV 号和视频页链接未核实 |
| [什么是电影感的渐变？](https://www.bilibili.com/video/BV12rWD6SEPy/)（`BV12rWD6SEPy`） | 渐变中间色与明暗过渡；用户说明为上述渐变网站的配套介绍 | 2026-11-16 已核对公开页、标题、作者木东东东CG及简介；未逐帧观看视频 |

其余 B 站参考视频尚未找到可核对的标题、BV 号或视频页链接。“浏览器二路融合扩展 0.17.1”是本地扩展资料，不能据此认定为某条 B 站视频。以后补到原链接时，逐条记录视频标题、链接、提出日期、参考的具体画面或交互，以及是否已核对原视频。

## 控件库设计评审

[控件图鉴与评审记录](ui-control-library-draft.md)涵盖本体控件、通用图标按钮和比赛二路的 Windows Qt 实拍。实装入口、试用操作与对照边界见[逐项核对清单](ui-control-coverage.md)。

在 Windows 上可通过仓库根目录的图鉴启动脚本打开，也可以用浏览器直接打开 [控件图鉴](ui-control-library.html)。

2026-11-19 操作 EasyUI 的组件预览后，将多项总览、独立试用详情和参数说明用于图鉴。 [设计评审记录](ui-control-library-draft.md#easyui-展示参考) · [EasyUI](https://easyui.site/)

## 渐变颜色参考

来源为用户于 2026-11-16 提供的[渐变网站](https://mudong-gradient.pages.dev/)和[配套视频](https://www.bilibili.com/video/BV12rWD6SEPy/)。视频作者为木东东东CG，标题为《什么是电影感的渐变？》。根据视频公开简介，同一组紫色与淡黄色端点可以形成不同的颜色过渡；设计时还应观察途中经过的中间色，并通过灰度检查明暗变化是否平顺。

本项目后续设计渐变配色时，可据此比较同一组端点的中段色相与明暗走势，并在灰度、深浅主题及实际控件背景上检查过渡和文字可读性。主题颜色继续集中在 `ddm/theme.py`，当前配色与美化入口见[外观设计](../features/appearance-design.md)和[皮肤与美化包](../features/skins.md)。本次收录参考来源与选色思路，尚未选定具体色值或修改软件配色。

核对范围：已读取视频公开页与公开接口中的标题、作者和简介；网页工具、浏览器及本机 HTTP 访问渐变网站均遇到连接或 DNS 解析失败，未取得站点正文。网站控件、预设色值、插值算法和视频的逐帧演示仍待实际核对。

## 协作约定参考

2026-11-18 阅读用户指定的[《6.2ASTRA 全新Agent.md》](https://www.xiaoheihe.cn/app/bbs/link/9ca272d6f450)，作者云裳宫阙；已核对文章的协作约定正文及随附英文提示文字。

结合本项目的 Qt、本机多任务与人工验收流程，将任务交付边界、工具故障分层排查、共享资源安排、按实际尺寸检查视觉交互、上下文接续和交付状态说明补入本机协作约定。用户明确选择继续保留“有疑问先问”，没有采用文中的普通细节默认自主决定方式；原有提交、测试、根 `run.cmd`、真实复现和发布约定继续适用。

本机 `AGENTS.md` 的规则更新按既有约定只留在本地；此处仅记录来源和适配结论。文章中的模型档位与自动委派建议未设为项目硬性要求，工具和外部材料不扩大操作授权。

## 记录新项目

维护者再次指定参考项目时，在表中补项目名称、可核对的来源、请求日期、想学习的具体问题和研究状态。做过源码或运行研究后，另写专题记录并在本页链接；只看过截图或演示时写明证据范围。已实现的改动指向对应提交或版本说明，未实施的想法留在本机 `docs/local/idea.md`，不把参考项目索引当功能待办或第三方许可清单。

[DD监控室原项目](https://gitee.com/zhimingshenjun/DD_Monitor_latest)是本项目的源码来源，署名和许可另见[来源与许可说明](../NOTICE.md)；依赖库和贡献 PR 不作为参考项目收录。
