# Windows 安装包与卸载范围

新用户使用 `DDMonitorSetup.exe`；已有用户继续使用软件内更新或 EXE 便携包。安装程序默认安装到当前用户的 `%LOCALAPPDATA%\Programs\DDMonitorCE`，无需管理员权限，支持选择目录和创建快捷方式。

安装向导使用深色背景、软件标志和蓝色品牌图。安装版不复制便携包的 `RELEASE-v0.5.md` 和 `运行说明.txt`，保留许可证、`ddm-build.json`（版本和更新识别）及 `.ddm-program-files.json`（更新时清理已登记的过期程序文件）。这些 JSON 是程序元数据，不是用户账号或多装的软件。

目录选择使用 Windows 原生 IFileOpenDialog 文件夹模式，支持地址栏、侧边栏和搜索；选择父目录后自动追加 `DDMonitorCE`，已经选择同名目录时不重复追加。取消保留原路径。系统对话框遵循 Windows 自己的主题。

可在 Windows“已安装的应用”、开始菜单，或安装目录的 `DDMonitorUninstall.exe` 启动卸载。后者是约 128KB 的本机入口，只定位并启动 `.ddm-uninstall` 内唯一的卸载 EXE，随后退出；真正卸载仍由 Inno 的逐文件记录管理，不重命名或移动原记录。目录内卸载 EXE 缺失或不唯一时提示使用 Windows 设置，避免猜测。开始菜单快捷方式仍遵循已有同名文件不接管的规则。修复安装不主动删除旧版已安装的说明文件，它们仍由原卸载记录管理。

交互卸载提供默认不勾选的“同时清除本机登录账号和软件设置”。仅清理 `utils/config.json`、其 `.bak` 备份，以及内置平台 AccountStore 的明确账号文件（`.bin` / `.tmp`）：bilibili、douyin、douyu、huya、youtube、twitch、douyin_follows、youtube_oauth_client、twitch_oauth_client。包括配置内的关注、布局和插件设置，不删除插件文件。第三方插件自行保存的凭据不在此白名单内，仍保留。录制、用户插件、皮肤、日志、缓存及其他文件始终保留；不递归清空 `utils` 或账号目录。静默卸载始终保留个人信息。已知清理路径包含链接时跳过整个个人信息清理并提示，删除失败也提示保留。清理前需退出应用，避免在退出时重新保存配置。

## 安装与卸载的边界

- 安装输入只能是经过验证的 Windows EXE 便携目录，拒绝账号、配置、插件、录制、未知文件和目录链接。
- 首次安装拒绝接管非空目录，避免覆盖其他软件或个人文件；已经由同一安装器登记的目录可以修复安装。
- 每个程序文件单独登记到 Inno Setup 的卸载日志，不使用通配符删除、整目录递归删除或自定义清盘逻辑。
- 卸载删除登记的程序文件、安装器元数据、它创建的快捷方式及卸载登记。默认保留账号和配置；用户主动勾选时按上述白名单清理。插件文件、录制、日志、缓存，以及后来放入的其他文件始终保留；非空目录不会被整目录删除。
- 已有的同名快捷方式不会被安装器接管。程序目录或已登记的程序子目录被改成链接时，安装和卸载都会停止，避免影响其他位置。
- 安装器提供初始 `.ddm-program-files.json`，供软件内更新清理已登记的过期程序文件；更新仍保留个人数据和未登记文件。该清单不打进在线更新 ZIP，避免覆盖旧版本的清理依据。
- 卸载使用安装器自身的文件记录。将来仅通过在线更新新增、尚未由安装器登记的文件可能保留；不会为追求清空目录而删除未知文件。需要时可使用新版安装器更新其登记记录。

## 构建与验证

先执行正常便携包构建及检查，再在 Visual Studio 的 x64 Native Tools 环境使用 MSVC 和 Inno Setup 6.7.3 编译安装器。原生入口使用静态 CRT，不要求用户安装 .NET 或额外运行库；同一入口在安装临时目录提供文件夹选择功能：

```powershell
python dev/build_setup.py --payload "<已验证的便携目录>" --out-dir "<产物目录>" --iscc "<Inno Setup 的 ISCC.exe>"
python dev/selfcheck_setup.py
python dev/check_setup_install.py --setup "<产物目录>\DDMonitorSetup.exe" --payload "<已验证的便携目录>" --update-zip "<同版本 EXE ZIP>"
```

最后一项仅限 Windows，使用项目 `work/` 下的临时目录、合成配置及临时插件。它真实运行安装器和卸载器；若当前账号已有该安装器的卸载登记会直接拒绝，避免接管已有安装。检查包括非空目录拒绝、修复安装、冻结程序启动与分享链接代码、更新清理范围、目录链接保护，以及卸载后的个人文件和相邻目录保留。不读取真实账号、不启动真实直播、不关闭用户的软件。

中文语言文件来自 [Inno Setup Chinese Simplified Translation](https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation)，固定源提交 `1ff90acc4ed4aee82b1cda43253243deee3daed4`，按 MIT 许可保留版权与许可文件，安装时随包提供。编译器属于构建依赖，不随本体源码或安装包携带。
