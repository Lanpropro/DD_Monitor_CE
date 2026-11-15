# 版本记录

> 类型：索引 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-15 ｜ 读者：维护者、贡献者、用户

本目录保存已发布版本的说明和下一版本的开发记录。发布说明是历史证据，发布后保持原文；
措辞勘误可以在发布页同步修改，但不改写旧结论。

## 当前与进行中

| 文档 | 说明 |
| --- | --- |
| [RELEASE-v0.7.3](RELEASE-v0.7.3.md) | 当前已发布版本（源码 `ddm/version.py`） |
| [UNRELEASED](UNRELEASED.md) | 下一版本累积记录；按条目追加，发布前汇总 |

## 本体版本

| 版本 | 说明 |
| --- | --- |
| [v0.7.3](RELEASE-v0.7.3.md) | 设置、弹幕管理、画面墙交互、更新器与诊断整理 |
| [v0.7.2](RELEASE-v0.7.2.md) | 热修复 |
| [v0.7.1](RELEASE-v0.7.1.md) | 热修复 |
| [v0.7](RELEASE-v0.7.md) | 0.7 系列 |
| [v0.6](RELEASE-v0.6.md) | 0.6 系列 |
| [v0.5.2](RELEASE-v0.5.2.md) | 0.5.2 系列 |
| [v0.5.2 醒目留言](RELEASE-v0.5.2-super-chat.md) | 醒目留言补充说明 |
| [v0.5.1](RELEASE-v0.5.1.md) | 热修复 |
| [v0.5](RELEASE-v0.5.md) | 播放内核迁移与批量修复 |
| [v0.4](RELEASE-v0.4.md) | 外观、皮肤与直播间组合 |
| [v0.3.1](RELEASE-v0.3.1.md) | 0.3.1 修复 |
| [v0.3](RELEASE-v0.3.md) | 0.3 系列 |
| [v0.2](RELEASE-v0.2.md) | 0.2 系列 |
| [v0.1](RELEASE-v0.1.md) | 首个公开版本 |

## 比赛二路插件

插件版本独立于本体；下表只保存本仓库的历史快照，不表示插件最新版本。2026-11-15 核对的
[比赛二路同步最新正式版为 v1.7.0](https://github.com/Lanpropro/DD_Monitor_Plugins/releases/tag/match-sync-v1.7.0)；插件源码与安装包在独立仓库发布。

| 版本 | 说明 |
| --- | --- |
| [v1.3](PLUGIN-match-sync-v1.3.md) | 本仓库最新历史快照 |
| [v1.2.10](PLUGIN-match-sync-v1.2.10.md) | |
| [v1.2.9](PLUGIN-match-sync-v1.2.9.md) | |
| [v1.2.8](PLUGIN-match-sync-v1.2.8.md) | |
| [v1.2.7](PLUGIN-match-sync-v1.2.7.md) | |
| [v1.2.6](PLUGIN-match-sync-v1.2.6.md) | |
| [v1.2.5](PLUGIN-match-sync-v1.2.5.md) | |
| [v1.2.4](PLUGIN-match-sync-v1.2.4.md) | |
| [v1.2.3](PLUGIN-match-sync-v1.2.3.md) | |
| [v1.2.2](PLUGIN-match-sync-v1.2.2.md) | |
| [v1.2.1](PLUGIN-match-sync-v1.2.1.md) | |
| [v1.2](PLUGIN-match-sync-v1.2.md) | 首个记录 |

## 发布约定

- 本体发布：修改 `ddm/version.py` → 运行发布检查 → 构建 → 打标签 → 创建 GitHub Release。
- 发布说明标题固定为 `# DD监控室CE v<版本> 更新说明`；网站与软件更新页直接读取该正文。
- 新版正文参照上一正式版本的 `RELEASE-v<版本>.md` 和 GitHub Release 正文安排结构；只写本版实际包含的变化，核对兼容、验证和限制，不复制旧版仍未解决的结论。
- 本体每次正式发布保留独立版本标签、Release 与说明；同版本热修复按内部修订号管理，不能用覆盖附件掩盖源码和修订差异。
- `UNRELEASED.md` 按时间倒序追加，每条写状态（待人工验收、已验收等）；发布时把实际包含且已验收的条目
  汇总到同版本说明，未包含的条目保留。
- 插件发布说明在插件仓库维护；本仓库只保留已发布的二路插件记录。
- 版本、标签、源码 commit 和构建产物必须对应；具体命令与验证见[贡献指南](../../CONTRIBUTING.md)
  和[Windows 安装包](../development/windows-installer.md)。
