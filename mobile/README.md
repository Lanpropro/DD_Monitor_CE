# Flutter 移动端预览

Android 与 iOS 共享 Dart 界面、房间状态和匿名取流逻辑。
播放器通过 video_player 使用 Android Media3 / iOS AVPlayer。
手机使用竖屏画面墙；宽度达到 720 逻辑像素时显示直播间侧栏。
底部 Dock 固定为观看、关注、插件、设置，页面切换保留当前播放。

当前完成单路 B 站直播：添加数字房间号、播放、暂停、静音、停止、备用 CDN、后台释放与返回恢复。
关注管理、插件商店、多路画面和桌面布局导入尚未实现；页面明确显示预览状态。
没有读取桌面账号、配置、录制或本机插件，也不发送弹幕。

## 开发

使用 Flutter 3.47.9 / Dart 3.13.7、JDK 21、Android SDK 36 及项目 Gradle wrapper。
最低 Android 7.0（API 24）；iOS 工程最低 iOS 15。
先运行 `flutter doctor`，Android 首次构建需要接受 SDK 许可并下载依赖。
SDK、PUB_CACHE、GRADLE_USER_HOME、AVD 和构建产物可放到容量充足的磁盘；不提交本机路径。

仓库根目录执行 `run.cmd --mobile` 启动移动端，`run.cmd` 无参数继续启动 Windows 客户端。
Flutter SDK 的 bin 目录需要在 PATH 中。多台设备连接时按提示选择。

在本目录执行：

```powershell
flutter pub get
flutter analyze
flutter test
flutter test integration_test/watch_test.dart -d emulator-5554
flutter build apk --debug
```

集成测试会访问公开 B 站房间 6，验证真实播放器初始化、持续播放、Dock 切换、后台恢复与停止。
房间停播或网络异常会导致测试失败，离线单元测试使用独立 MockClient。
生成的 APK 位于 `build/app/outputs/flutter-apk/app-debug.apk`，使用预览应用 ID 和调试签名。

iOS 必须在 macOS 配合 Xcode 完成构建、签名和设备验收；Windows 上生成工程不代表 iOS 验证通过。
iOS 只选 H.264 HLS；Android 在 HLS 不可用时可回退 FLV。
实际清晰度以平台返回值为准。API 请求走 HTTPS，部分媒体 CDN 使用 HTTP，因此开启 Android 明文媒体访问和 iOS 媒体 ATS 例外。

## 人工验收

1. 右上角添加直播间，空值 / 0 显示提示；合法公开直播间出现真实画面与声音。
2. 暂停、继续、静音、停止生效；切到关注再回观看，直播继续。
3. 横竖屏、后台返回、断网后重试不崩溃；停止后不继续出声。
4. 手机竖屏、平板横屏检查布局和软键盘；关注与插件空态可读。

旧 Kotlin / Chaquopy 原型保存在 Git 提交 `86f841c`；本目录替代它作为移动端开发入口。
