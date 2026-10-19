# 仓库整理审查

2026-10-14。用户确认深浅色功能完成后要求集中说明、审查多余测试、移除过时文件。
本次删除均为 Git 跟踪文件，可通过本次提交的父提交恢复；未触碰六项本机未跟踪保护项或真实配置。

## 文档集中

- 根目录四份 RELEASE-v*.md 移到 `docs/releases/`，作为历史版本记录保留，不因版本旧而删除。
- 根目录 NOTICE.md 移到 `docs/NOTICE.md`；纠正“录制未实现”的过时描述。
- 根目录历史 HANDOFF-*.md 与 idea.txt 移到 `docs/local/`，继续只在本机保留。
- 根目录 README、LICENSE、AGENTS.md、PROJECT_STATE.md 是仓库和交接入口，保留原位。插件/资源内 README 保持就近存放。
- 软件源码读取新文档路径，仍兼容 EXE 同级版本说明；打包继续将 NOTICE 和当前版本说明复制到 EXE 同级。
- [统一文档入口](../README.md)列出分类和导航。

## 已移除的四个文件

| 文件 | 判断依据 | 保留的相关检查 |
| --- | --- | --- |
| dev/selfcheck_appearance_prototype.py | 定义独立 IconPrototype，并临时覆盖样式展示旧原型，不检查正式 FolderIconDialog；正式功能已实现且用户确认完成 | [文件夹图标](../../dev/selfcheck_folder_icons.py)、[浅色细节](../../dev/selfcheck_light_refinements.py) |
| dev/selfcheck_final2.py | 早期顶栏/音量/画质外观打印脚本，无自动失败断言；现有正式控件检查更明确 | [格子界面](../../dev/selfcheck_tile_ui.py)、[物理控件](../../dev/selfcheck_control_physical_edges.py) |
| dev/selfcheck_quality2.py | 早期画质请求打印脚本，无自动失败断言，且使用 config.load() 读取本机配置；不适合作为自动回归 | [B站画质](../../dev/selfcheck_bili_quality.py)、[自动画质](../../dev/selfcheck_auto_quality.py)、[画质切换](../../dev/selfcheck_auto_quality_switch_live.py) |
| dev/selfcheck_login2.py | 早期真实登录窗口/截图诊断，无自动失败断言，会等待真实网络二维码；与离线回归混用容易误报成功 | [二维码刷新](../../dev/selfcheck_qr_refresh.py)、[二维码响应](../../dev/selfcheck_qr_responsiveness.py) |

上述“相关检查”覆盖现有功能行为，并不宣称与每个历史打印/截图一一等价。
删除前已检索跟踪源码，未发现其作为其他脚本的导入依赖；原型文档引用同步修正。

## 为什么保留其他测试

项目要求每次改动补充相关测试，长期按具体问题新增脚本，未形成统一入口分类，因而积累较多。
本轮删除后仍有 202 个 selfcheck_*.py；这个数字包含仓库检查、功能回归和需人工条件的诊断，并不等于 202 个重复测试。
大量脚本来自不同故障的回归：播放生命周期、声音路由、弹幕、插件更新、账号及主题/DPI 等各有独立触发条件。
同一功能的离线逻辑检查、原生 Windows/VLC 检查和真实直播诊断验证层次不同，不能只因名称相似或功能完成就删除。
深浅色测试仍需保护已完成的功能，尤其空格子快照、播放透明孔、原生圆形区域和连续切换。
`selfcheck_ui3.py` 虽命名较早，但包含时长浮标隐藏、下播停计时的有效断言，本轮保留。
`selfcheck_quality.py` 是真实播放诊断，本轮没有证明其价值已被完全替代，暂保留。
没有断言不必然代表无用，构建检查也可能使用 unittest；此次判断结合脚本用途和正式实现。

## 保留供下一步审查的项目

| 项目 | 本轮保留的原因 |
| --- | --- |
| docs/website-plan.md 及对应检查 | 属于独立网站任务，含旧基线与待核实信息；未取得网站任务完成或取消的证据，不能仅因日期旧就删除 |
| docs/BUG-STATUS-2026-10-02.md | 历史故障与未验证事项的记录，可追溯，不作为当前任务清单 |
| videos/、Video_reference/、raw/、results/ 宣传资料 | 混有原始素材、归档及最终成片，未逐一证明已无保留价值 |
| work/ | 混有依赖、工作树和测试资料，不能整体删除 |
| dev/mock_portrait.py、dev/portrait_mock.html 等六项保护项 | 用户本机未跟踪文件，保留现状，未并入提交 |
| docs 中历史交接、宣传过程文档 | 作为归档保留；当前入口已注明其历史性质 |

## 验证范围

验证文档链接、分类清单与 Git 索引一致、旧资料忽略规则、源码/便携布局的版本说明加载及发布脚本元数据。
本轮不重新打包、不联网验证直播或 PR；没有依据将整个仓库全部测试报告为通过。

实际验证：repository_map 的 4 项、repository_files 的 3 项，及 README、外观设计、发布元数据、二维码刷新、B站画质、文件夹图标、浅色细节共 7 个专项脚本均通过；git diff --check 通过。
浅色细节在 Qt offscreen 首次运行时窗口位置断言失败，原生 Windows 屏外测试复核通过；未修改该测试断言。
EXE 文档复制验证实际执行发布脚本中的复制片段，未构建完整安装包；没有运行依赖已有发布包的 check_release_package.py。
