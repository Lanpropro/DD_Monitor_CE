# 文档中心

> 类型：索引 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-15 ｜ 读者：用户、贡献者、维护者

这里是 DD监控室CE 的文档入口。根目录新增的文档只保留 README、贡献指南、许可证和 Agent 规则；
专题文档、开发记录和历史资料都从本页进入。

## 快速入口

| 我想… | 先看 |
| --- | --- |
| 下载、了解功能与插件 | [项目介绍](../README.md) |
| 第一次参与开发 | [贡献指南](../CONTRIBUTING.md) → [开发指南](development/README.md) |
| 知道代码怎么分层、该改哪里 | [架构总览](architecture/overview.md) |
| 新增或整理文档 | [开发文档规范](standards/documentation.md) |
| 改完代码跑哪些测试 | [验证指南](development/testing.md) |
| 打包、安装与更新 | [Windows 安装包](development/windows-installer.md)、[在线更新](online-updates.md) |
| 查历史故障和处理结论 | [Bug 案例库](bug-cases.md) |
| 看版本改了什么 | [版本记录](releases/README.md)、[下一版本](releases/UNRELEASED.md) |
| 写插件或改宿主接口 | [插件接口](plugins.md) |
| 查某个文件归谁管 | [仓库文件分类清单](repository-map.md) |

## 文档地图

### 规范与架构

| 文档 | 内容 |
| --- | --- |
| [开发文档规范](standards/documentation.md) | 本体/插件/网站共用的分层、元信息、写作、生命周期与校验规则 |
| [架构文档索引](architecture/README.md) | 架构页的阅读顺序与维护约定 |
| [架构总览](architecture/overview.md) | 进程、分层、启动关闭、职责域、状态所有权、关键数据流 |

### 开发与验证

| 文档 | 内容 |
| --- | --- |
| [开发指南索引](development/README.md) | 按改动类型找到验证、界面、打包和诊断文档 |
| [验证指南](development/testing.md) | 套件分类、环境变量、单项命令、按功能的验证记录 |
| [共用界面组件](development/ui-components.md) | 统一入口、组件目录和调用方式 |
| [Windows 安装包与卸载范围](development/windows-installer.md) | 安装模式、数据目录、UAC、更新替换 |
| [本机工作区维护](development/workspace-maintenance.md) | 目录归属、旧运行库归档、检查纳入标准 |
| [久用卡顿的真实采集](development/responsiveness-capture.md) | BUG-070 的采集字段、步骤与证据边界 |

### 功能与设计

| 文档 | 内容 |
| --- | --- |
| [深浅色模式与文件夹图标](appearance-design.md) | 主题、图标、外观交互与验证要求 |
| [皮肤与美化包](skins.md) | 分区美化、背景、插件包格式与优先级 |
| [多画面画中画](picture-in-picture.md) | 选流、组合、换位、比例与窗口交互 |
| [直播间组合预设](room-presets-design.md) | 保存范围、恢复规则与旧配置兼容 |
| [窗口缩放性能](resize-performance.md) | 交互阶段、几何更新与验收口径 |
| [头像与封面缓存](image-cache.md) | 占用统计、清理规则与新旧图替换 |
| [自由布局编辑器计划](customization-plan.md) | 尚未实现的布局结构编辑范围与待定规则 |

### 参考

| 文档 | 内容 |
| --- | --- |
| [参考项目与学习记录](references/README.md) | 用户指定的学习对象、研究程度、结论及后续去向 |
| [插件接口](plugins.md) | 宿主公开契约、事件、平台、发送、菜单、皮肤与录制服务 |
| [在线更新与插件商店](online-updates.md) | 检查、下载校验、暂存替换、目录缓存与发布 |
| [仓库文件分类清单](repository-map.md) | 已跟踪文件、目录归属与本机资料边界 |
| [Bug 案例库](bug-cases.md) | 按模块归纳的故障、根因、验证与验收状态 |
| [第三方来源与声明](NOTICE.md) | 许可证、参考项目与素材来源 |

### 版本与历史

| 文档 | 内容 |
| --- | --- |
| [版本记录索引](releases/README.md) | 本体版本说明、二路插件发布入口与发布约定 |
| [下一版本开发记录](releases/UNRELEASED.md) | 待发布条目、验收证据与待办 |
| [历史记录索引](archive/README.md) | 早期问题、PR 测试与仓库整理过程 |

### 本机资料（不进入版本库）

| 位置 | 内容 |
| --- | --- |
| `docs/local/` | 本机诊断记录和随手笔记，被 Git 忽略；历史交接归入 `docs/local/archive/handoffs/` |
| 根目录 `PROJECT_STATE.md` | 当前交接入口，被 Git 忽略 |
| `docs/VIDEO-*.md`、`docs/PROMO-*.md` | 宣传过程资料，被 Git 忽略 |

这些内容只在维护者本机保留，不作为公开文档，也不进入发布包。

## 维护约定

- 新增文档先按[开发文档规范](standards/documentation.md)确定类型和目录，再登记到本页或所属子目录索引。
- 长期维护文档在标题下写元信息（类型、状态、适用版本、更新日期、读者）；发布说明和历史归档除外。
- 移动或改名文档时同步更新所有相对链接和[仓库文件分类清单](repository-map.md)；不为整理反复搬迁路径。
- 提交前运行：

```powershell
dev\run-checks.cmd --script selfcheck_documents
dev\run-checks.cmd --suite repository
git diff --check
```

其他系统使用 Python 3.10 及以上版本运行相同脚本。

发现链接失效、文档未入索引或元信息缺失时，修正文档和索引，不删除检查规则。
