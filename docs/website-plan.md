# DD 监控室 CE 软件与插件展示网站

## 目标

建立面向用户的网站，展示 DD 监控室 CE 软件及独立插件，提供软件下载入口、
插件 ZIP 下载、安装说明和相关仓库入口。用户已要求由新对话继续制作，
并明确网站内容包含软件本身。

## 页面范围

- 首页：软件定位、主要功能、真实截图、软件下载和插件列表入口。
- 软件介绍：多画面直播墙、关注管理、横竖屏布局、弹幕及每路播放控制。
  对录制等功能先核对当前公开安装包，区分已发布功能与开发版本功能。
- 插件列表：图标、名称、简介、版本、支持平台、兼容要求、详情及下载按钮。
- 插件详情：功能、使用说明、更新记录、源码与问题反馈入口。
- 安装帮助：软件启动、插件 ZIP 导入、启用、重启和升级方法。

插件列表可按名称或平台搜索；分类随实际插件内容维护。
本轮不包含软件内一键安装、插件自动更新、用户登录或在线后台。

## 首批插件与下载

| ID | 名称 | 版本 | 平台 | 安装包 |
| --- | --- | --- | --- | --- |
| domestic_live | 国内直播平台 | 1.0 | 虎牙、斗鱼、抖音 | [下载 ZIP](https://github.com/Lanpropro/DD_Monitor_Plugins/releases/download/v1.0/domestic_live-1.0.zip) |
| global_live | Twitch 与 YouTube | 1.0 | Twitch、YouTube | [下载 ZIP](https://github.com/Lanpropro/DD_Monitor_Plugins/releases/download/v1.0/global_live-1.0.zip) |

两个插件提供关注卡片、拖入格子播放、实际画质档位、横竖屏悬停预览和聊天弹幕。
海外插件提供自动画质。禁用插件后关注及格子转为暂存。
插件各自记录版本与下载 URL，避免共用仓库的最新 Release 缺少某个插件安装包。

插件需要包含平台扩展接口的配套软件（源码基线 4bf84bc 或之后）。
公开源码已同步到包含该接口的 9f007e8；公开软件安装包兼容性仍需核实。
版本名称 v0.2 本身不足以证明兼容，页面应明确实际可用的配套构建。
GitHub 自动生成的 Source code ZIP 不能作为单插件包导入。

## 已有素材与内容入口

- [软件说明](../README.md)：功能、运行环境、布局及基础使用，需与公开版本核对。
- [软件标志 SVG](../assets/logo.svg)、[软件标志 PNG](../assets/logo.png)。
- [横屏截图](overview1_Landscape_mode.png)。
- [横屏弹幕布局截图](overview2_Landscape_mode.png)。
- [竖屏截图](overview1_Portrait_Mode.png)。

优先使用真实素材；以上截图可能对应早期界面，发布前需确认适用性。
复制到网站仓库时保留来源，优化网页图片体积，不修改原图。

## 技术与托管建议

以下是讨论中的建议，尚未完成部署：网站源文件放在插件仓库 docs/，
使用 VitePress 制作软件首页、文档与插件卡片，通过 GitHub Pages 发布。
可维护一份插件目录数据驱动列表，后续新增插件时补数据与详情即可。
安装包保留在 Releases，以各插件的实际发布地址提供下载。
自定义域名可后续决定，首版使用平台提供的域名。
本次授权制作网站；公开部署和修改仓库 Pages 设置前交付可审阅的预览与具体发布方案。

## 项目入口与参考

- [软件仓库](https://github.com/Lanpropro/DD_Monitor_CE)。
- [软件下载](https://github.com/Lanpropro/DD_Monitor_CE/releases)。
- [插件仓库](https://github.com/Lanpropro/DD_Monitor_Plugins)。
- [插件发布页](https://github.com/Lanpropro/DD_Monitor_Plugins/releases/tag/v1.0)。
- [用户参考页面](https://docs.sayu-bot.com/InstallPlugins/PluginsList.html)：参考列表结构与信息组织。
- [VitePress 文档](https://vitepress.dev/guide/what-is-vitepress)。
- [GitHub Pages 文档](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)。

## 验收

1. 桌面及手机均可浏览，软件展示与插件下载入口清楚。
2. 两个插件名称、ID、1.0 版本和安装包对应正确，兼容说明明确。
3. 下载按钮指向真实 ZIP，软件按钮指向经过核实的安装包或发布页。
4. 图标、截图、详情、安装说明及仓库链接完整，无空白占位内容。
5. 网站构建及相关测试通过，浏览器检查布局与交互，提交本次代码。
6. 先交付本地预览及部署方案；如取得发布授权，再验证公开网址及下载入口。
