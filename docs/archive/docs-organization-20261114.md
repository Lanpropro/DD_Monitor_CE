# 2026-11-14 开发文档规范化与整理

> 类型：记录 ｜ 状态：稳定 ｜ 适用版本：0.7.x ｜ 更新：2026-11-14 ｜ 读者：维护者

本轮把软件本体、插件仓库和网站仓库的开发文档统一到同一套分层与校验规则。只整理文档结构与导航，
不修改软件行为、插件行为、页面内容或发布状态。

## 范围

| 仓库 | 角色 | 本轮处理 |
| --- | --- | --- |
| [DD_Monitor_CE](https://github.com/Lanpropro/DD_Monitor_CE) | 软件本体与宿主接口 | 文档中心、架构、规范、开发索引、版本索引、元信息、校验 |
| [DD_Monitor_Plugins](https://github.com/Lanpropro/DD_Monitor_Plugins) | 插件源码 | 文档中心、开发指南、插件文档规范、元信息、校验 |
| [DD_Monitor_Website](https://github.com/Lanpropro/DD_Monitor_Website) | 展示网站 | 开发文档目录、同步/发布流程、文档规范、校验 |

## 盘点发现

- 本体的 71 份已跟踪文档链接整体可用，但入口是一个平铺表：缺少架构页、文档规范和子目录索引。
- 版本索引停在 0.7.1，遗漏 0.7.2、0.7.3 和二路插件新版本；`UNRELEASED.md` 标题仍是 `v0.7.2`。
- 长期维护文档没有统一的类型、状态、适用版本、更新日期和读者信息；`testing.md`、`repository-map.md`、
  `bug-cases.md` 等长文档没有阅读导航。
- 插件仓库已有增量记录、发布记录和逐插件文档，但缺少文档入口、开发指南和统一的文档规则。
- 网站仓库把开发说明分散在 README、CONTRIBUTING、WEBSITE、MIGRATION，缺少独立开发文档目录，
  且两份文档写入了本机绝对路径。
- 三个仓库都没有把“文档是否入索引、是否带元信息、链接是否有效”纳入自动检查。

## 决策

- **保持既有路径**：不为整理批量移动功能文档和发布说明，避免破坏已分享链接、构建脚本和历史记录。
  新增文档进入 `docs/architecture/`、`docs/standards/` 或既有子目录。
- **一个共享基线，各自补充**：完整规范放在本体 `docs/standards/documentation.md`；插件和网站各自保留
  简短规范，写仓库特有规则，并链接共享基线。
- **文档检查随仓库入口执行**：本体接入 `repository` 套件；插件扩展 `check_contributing.py`；
  网站新增 `tests/docs.test.mjs`，随 `npm test` 运行。
- **发布说明保持历史**：已发布正文和插件哈希固定的发布记录不改写；新结论写入新的记录或增量记录。

## 本体改动

- 新增[开发文档规范](../standards/documentation.md)：全流程、分层、元信息、写作、生命周期、跨仓库约定和模板。
- 新增[架构文档](../architecture/README.md)与[架构总览](../architecture/overview.md)：进程、分层、启动关闭、
  职责域、状态所有权和关键数据流。
- 重写[文档中心](../README.md)，新增[开发指南索引](../development/README.md)和[版本记录索引](../releases/README.md)。
- 为 20 份长期维护文档补元信息；为验证指南、案例库、插件接口、组件目录、文件清单和皮肤文档补阅读导航。
- 修正 `UNRELEASED.md` 标题与阅读说明，明确“待人工验收/已验收”和发布时汇总规则。
- 新增 `dev/selfcheck_documents.py`，接入 `repository` 套件、检查索引和贡献指南。

## 插件仓库改动

- 新增 `docs/README.md`（文档中心）、`docs/development/README.md`（开发指南）、
  `docs/standards/documentation.md`（插件文档规范）。
- 为目录说明、增量记录索引、发布索引、归档索引、监测记录、平台图标说明和网站迁移说明补元信息。
- 更新根 README 与 CONTRIBUTING 的文档入口；修正目录说明中过时的插件数量和发布说明数量。
- 扩展 `tests/check_contributing.py`：文档入口、索引可达、元信息、链接与锚点、本机路径检查。

## 网站仓库改动

- 新增 `development/`：开发文档索引、文档规范、内容与数据同步、发布流程。
- 更新 README、CONTRIBUTING、WEBSITE 的开发文档入口；移除文档中的本机绝对路径。
- 新增 `tests/docs.test.mjs`：开发文档与公开站点分离、索引可达、元信息、链接、本机路径与同步流程检查。

## 验证

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 本体仓库 | `python dev/run_checks.py --suite repository --timeout 120` | 8/8 通过 |
| 本体文档 | `python dev/selfcheck_documents.py` | 8 项通过 |
| 插件文档 | `python tests/check_contributing.py` | 13 项通过 |
| 网站文档 | `node --test tests/docs.test.mjs` | 5 项通过 |
| 网站全量 | `npm run build` + `npm test` | 93 项通过（默认 base 重建 dist 后） |

格式检查使用 `git diff --check`；插件源码编译使用 `python -m compileall -q plugins tests tools`。
测试只验证结构、链接与文档事实，不代替真实直播、安装包或线上部署验收。

## 未覆盖与后续

- `docs/local/`、根目录 `PROJECT_STATE.md`、历史交接和宣传过程资料仍只在本机保留，未纳入本轮整理，
  也未提交。
- 既有功能文档和发布说明没有物理移动；如需按 `features/`、`reference/` 重新分目录，应另起一次改动，
  一次性更新全部链接并重新验证。
- 插件和网站文档中的共享规范链接指向本体 `develop` 分支；本体合入后生效，合并前可能暂时 404。
- 本轮不重新打包本体、插件或网站，不创建标签，不改写已发布正文。
