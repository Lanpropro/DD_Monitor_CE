# 安卓单路观看预览

第一阶段验证 Kotlin / Compose → Chaquopy / Python → Media3 的完整观看链路。
支持输入 B 站数字房间号、匿名取流、单路播放、播放控件、停止及横竖屏。
播放器在进入后台时释放，返回前台后恢复当前直播；CDN 播放错误时依次尝试备用地址。
没有接入桌面配置、账号、插件安装副本、录制和即时回放。

## 构建与启动

需要 JDK 21、Android SDK Platform 36 / Build Tools 36.0.0 和 Python 3.12。
在 Android Studio 打开本目录，SDK 路径填写本机位置；或创建不提交的 `local.properties`：

```properties
sdk.dir=D\:/Android/Sdk
```

将示例替换为本机 SDK 路径，Windows 盘符冒号写为 `\:`。
命令行设置 `JAVA_HOME`、`ANDROID_HOME`，可通过 `DDM_BUILD_PYTHON` 指定 Python 3.12 可执行文件。
建议将 `GRADLE_USER_HOME`、`ANDROID_USER_HOME`、`ANDROID_AVD_HOME` 放在容量充足的磁盘。
首次构建需要下载 Google Maven、Maven Central、Gradle 和 Chaquopy 的依赖。
代理设置放在本机 Gradle 用户目录的 `gradle.properties`，不提交账号或代理配置。

```powershell
.\gradlew.bat assembleDebug assembleDebugAndroidTest
.\gradlew.bat connectedDebugAndroidTest
python -m unittest discover -s tests -v
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n io.github.lanpropro.ddmonitor.preview/io.github.lanpropro.ddmonitor.MainActivity
```

APK 同时包含 x86_64（Windows 模拟器）和 arm64-v8a（手机、平板）；最低 Android 7.0。
预览包使用独立应用 ID 和调试签名，尚不是正式发布版本。
默认匿名请求 720P，实际画质由平台返回；没有接入账号登录或画质选择。
部分直播 CDN 使用 HTTP，因此 Manifest 开启明文流访问；API 请求仍使用 HTTPS。

## 验收

1. 安装并启动，输入无效房间号应显示提示，停止后清空错误。
2. 输入已开播的公开房间号，检查首帧、持续播放、控件及停止。
3. 旋转屏幕、切后台再返回，检查播放器恢复；关闭后不继续播放。
4. 未开播或请求失败时显示可理解的提示；重新输入房间号可重试。

离线单元测试覆盖房间号、短号转换、直播状态、AVC / HLS 选择、FLV 回退、CDN 地址及请求头。
设备测试覆盖真正的 Python 桥接、无效输入、停止操作和 Activity 重建后保留输入，不读取真实账号或访问网络。
真实直播验证需单独记录房间号和时间，不把一次实播当作所有直播源兼容性保证。

安卓入口位于本目录；仓库根目录 `run.cmd` 继续作为 Windows 客户端入口。
开发方案参考 [Chaquopy](https://chaquo.com/chaquopy/doc/current/android.html) 与
[Media3](https://developer.android.com/media/media3/exoplayer/hello-world)。
