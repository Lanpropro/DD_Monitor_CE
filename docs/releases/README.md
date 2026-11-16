# 版本记录

> 类型：索引 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-16 ｜ 读者：维护者、贡献者、用户

本页索引本分支保存的发布说明；源码版本以 `ddm/version.py` 为准，正式版本与附件以 Git 标签及 GitHub Releases 为准。规范入库不修改源码版本或发布状态。

- [下一版本开发记录](UNRELEASED.md)

## 本体版本

- [RELEASE-v0.7.3](RELEASE-v0.7.3.md)

- [RELEASE-v0.1](RELEASE-v0.1.md)
- [RELEASE-v0.2](RELEASE-v0.2.md)
- [RELEASE-v0.3.1](RELEASE-v0.3.1.md)
- [RELEASE-v0.3](RELEASE-v0.3.md)
- [RELEASE-v0.4](RELEASE-v0.4.md)
- [RELEASE-v0.5.1](RELEASE-v0.5.1.md)
- [RELEASE-v0.5.2-super-chat](RELEASE-v0.5.2-super-chat.md)
- [RELEASE-v0.5.2](RELEASE-v0.5.2.md)
- [RELEASE-v0.5](RELEASE-v0.5.md)
- [RELEASE-v0.6](RELEASE-v0.6.md)
- [RELEASE-v0.7.1](RELEASE-v0.7.1.md)
- [RELEASE-v0.7.2](RELEASE-v0.7.2.md)
- [RELEASE-v0.7](RELEASE-v0.7.md)

## 旧二路插件说明

以下文件是分离前保留的历史说明，不作为现行插件版本依据。插件开发、当前版本和后续发布以[独立插件仓库](https://github.com/Lanpropro/DD_Monitor_Plugins)为准；本次规范入库不删除其历史原文。

- [PLUGIN-match-sync-v1.2.1](PLUGIN-match-sync-v1.2.1.md)
- [PLUGIN-match-sync-v1.2.10](PLUGIN-match-sync-v1.2.10.md)
- [PLUGIN-match-sync-v1.2.2](PLUGIN-match-sync-v1.2.2.md)
- [PLUGIN-match-sync-v1.2.3](PLUGIN-match-sync-v1.2.3.md)
- [PLUGIN-match-sync-v1.2.4](PLUGIN-match-sync-v1.2.4.md)
- [PLUGIN-match-sync-v1.2.5](PLUGIN-match-sync-v1.2.5.md)
- [PLUGIN-match-sync-v1.2.6](PLUGIN-match-sync-v1.2.6.md)
- [PLUGIN-match-sync-v1.2.7](PLUGIN-match-sync-v1.2.7.md)
- [PLUGIN-match-sync-v1.2.8](PLUGIN-match-sync-v1.2.8.md)
- [PLUGIN-match-sync-v1.2.9](PLUGIN-match-sync-v1.2.9.md)
- [PLUGIN-match-sync-v1.2](PLUGIN-match-sync-v1.2.md)
- [PLUGIN-match-sync-v1.3](PLUGIN-match-sync-v1.3.md)

## 发布约定

- 本体发布：记录拟纳入版本的改动 → 核对上一正式标签至候选提交的差异 → 准备发布说明与候选包并运行发布检查 → 请维护者人工验收改动并确认发布说明 → 打标签并创建 GitHub Release。正文经维护者修改后，发布前重新运行相关文档和产物检查；人工验收前不得发布。
- 发布说明标题固定为 `# DD监控室CE v<版本> 更新说明`；网站与软件更新页直接读取该正文。
- 新版正文参照上一正式版本的 `RELEASE-v<版本>.md` 和 GitHub Release 正文安排结构；只写本版实际包含的变化，核对兼容、验证和限制，不复制旧版仍未解决的结论。
- 本体后续更新默认递增版本号，或为同版本热修复新建 `-hotfix.N` 标签与独立 Release，并保留对应源码提交、说明和附件。只有维护者针对某次发布明确允许时，才可覆盖现有 Release；该例外仍须递增内部修订号，记录被替换附件的名称、SHA-256、对应源码提交与新附件的对应关系，先完成候选验证和人工验收。不得以覆盖附件掩盖源码和修订差异。
- 独立热修复使用单独的 `RELEASE-v<版本>-hotfix.N.md` 保存公开正文；基础版本说明保持其最终公开正文，不在原文件顶部追加后续修订。旧标签中的正文仍可从 Git 历史追溯。
- 每次完成拟纳入本体版本的修改后及时更新 `UNRELEASED.md`，按时间倒序写明变更、提交和状态（待人工验收、已验收等）。准备发布时，用它和 Git 差异生成本机临时审核单 `docs/local/release-drafts/v<版本>.md`，逐项列出相对上一正式版新增、修复、未纳入的内容，以及对应提交、验证范围和待人工验收项。
- 将临时审核单和 `docs/releases/RELEASE-v<版本>.md` 草稿一同展示给维护者；维护者对实际软件改动人工验收，并审阅、修改或确认发布正文。只有两者明确通过，才把已包含且已验收的条目写入正式说明并继续发布；未纳入条目留在 `UNRELEASED.md`。
- 发布成功并核对版本标签、源码提交与公开附件后，删除本机临时审核单，从 `UNRELEASED.md` 移走本次已发布条目；正式说明和 Git 历史保留。将上一版本的本机发布 ZIP 移入 `results/archive/`，最新版本在 `results/` 保留正式附件和一个解压入口。
- 插件发布说明在插件仓库维护；分离前的本体二路源码 README 由 Git 历史追溯，不在本体发布目录重复存放。
- 版本、标签、源码 commit 和构建产物必须对应；具体命令与验证见[贡献指南](../../CONTRIBUTING.md)
  和[Windows 安装包](../development/windows-installer.md)。
