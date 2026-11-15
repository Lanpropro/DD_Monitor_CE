# 开发指南

> 类型：索引 ｜ 状态：维护中 ｜ 适用版本：0.7.x ｜ 更新：2026-11-15 ｜ 读者：贡献者、维护者

本目录放"怎么做"的文档：环境、验证、界面组件、打包安装、工作区维护和专项采集。
系统组成与边界见[架构总览](../architecture/overview.md)；流程和提交规则见[贡献指南](../../CONTRIBUTING.md)。

## 开始开发

| 文档 | 用途 | 何时读 |
| --- | --- | --- |
| [贡献指南](../../CONTRIBUTING.md) | 分支、提交、PR、验证范围、发布规则 | 第一次提交前；每次准备 PR |
| [开发目录说明](../../dev/README.md) | `dev/` 下工具、套件入口、独立设置进程 | 找检查脚本或构建工具 |
| [验证指南](testing.md) | 套件分类、执行条件、单项命令、结果记录 | 改完代码后选择测试 |
| [专项检查索引](../../dev/checks/README.md) | 全部 `selfcheck_*` / `check_*` 的分类与隔离条件 | 需要找某个功能的专项 |

```powershell
# 基础三件套，不联网、不读账号
dev\run-checks.cmd --suite repository
python -m compileall -q ddm blivedm main.py
git diff --check
```

编译检查也应使用项目虚拟环境的 Python；系统 PATH 若指向旧版解释器，不能用其失败结果判断源码有误。

## 按改动类型查找

| 改动 | 必读 | 最低验证 |
| --- | --- | --- |
| 设置、通知、快捷键 | [验证指南](testing.md)对应小节 | `selfcheck_main_notices`、设置专项 |
| 界面控件、主题、外观 | [共用界面组件](ui-components.md)、[外观设计](../appearance-design.md) | 组件/外观专项，高 DPI 人工检查 |
| 播放、解码、原生窗口 | [验证指南](testing.md)、[窗口缩放性能](../resize-performance.md) | `--suite native`，真实直播人工验收 |
| 弹幕、SC、画中画 | [验证指南](testing.md)、[多画面画中画](../picture-in-picture.md) | 对应离屏/原生专项 |
| 录制、回放、退出 | [插件接口](../plugins.md#录制服务-v1配套开发接口)、[验证指南](testing.md) | 录制与退出专项，核对生成文件 |
| 安装、更新、发布 | [Windows 安装包](windows-installer.md)、[在线更新](../online-updates.md) | 发布元数据与安装器专项 |
| 卡顿、错位等未决问题 | [久用卡顿采集](responsiveness-capture.md) | 先采集证据，再做针对性修改 |

## 打包、安装与发布

| 文档 | 内容 |
| --- | --- |
| [Windows 安装包与卸载范围](windows-installer.md) | 安装模式、数据目录、UAC、更新替换边界 |
| [在线更新与插件商店](../online-updates.md) | 检查、下载校验、暂存替换、插件目录 |
| [本机工作区维护](workspace-maintenance.md) | 目录归属、旧运行库、归档与检查纳入标准 |
| [发布记录](../releases/README.md) | 历史版本说明、未发布记录与发布约定 |

发布使用根目录已提交的完整源码构建，不从开发目录挑选文件；打包与验收命令见贡献指南和安装包文档。

## 诊断与专项采集

| 文档 | 内容 |
| --- | --- |
| [久用卡顿的真实采集](responsiveness-capture.md) | BUG-070 的采集范围、字段和人工步骤 |
| [独立诊断工具](../../tools/diagnostics/README.md) | 不依赖 Qt/Python 的现场收集器 |
| [验证指南 · 未决问题专项](testing.md#未决问题专项与独立诊断工具) | 各诊断入口的适用条件 |

采集工具只验证"采到了什么"，不能证明故障已定位或性能已改善；结论按[开发文档规范](../standards/documentation.md)
的证据分层书写。
