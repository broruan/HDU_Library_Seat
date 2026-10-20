# Android 安卓应用

安卓应用在手机内运行与桌面网页相同的 Python 预约服务和面板，无需电脑、远程中转服务器或手动粘贴 Cookie。手机端提供账号登录区、分区导航、适合触屏的表单和底部任务按钮。

## 安装与登录

1. 从 [GitHub Releases](https://github.com/broruan/HDU_Library_Seat/releases/latest) 下载 `HDU-Library-Seat-Android.apk`。适用于 **Android 7.0 及以上、64 位 ARM 手机**；同一 APK 也包含用于模拟器的 x86_64 版本。
2. 在手机上安装 APK。首次安装时，按系统提示允许当前文件管理器或浏览器安装应用。
3. 打开“杭电图书馆座位助手”，点击“账号密码登录”。应用会打开学校和图书馆的官方 HTTPS 登录页面，在该页面输入学校账号和密码。若学校要求验证码或二次验证，在官方页面完成即可。
4. 登录成功后，应用自动接收图书馆会话并返回预约面板。未自动返回时，可在登录页点击“完成登录”；会话失效时重新登录。
5. 设置使用时段和座位偏好，查询座位并选择目标；可先点击“试运行（不预约）”，再开始预约任务。

账号密码由官方页面处理，应用不保存学校密码。图书馆会话在应用内自动管理，用户无需查看或填写 Cookie。退出登录会清除应用保存的会话，并停止当前预约任务。

## 与网页端相同的功能

- 座位查询、可用状态和点击选择；目标座位、关键词、楼层、避开门口等偏好。
- 使用日期、整点开始时间、使用时长和人数。
- 立即启动、北京时间定时启动、轮询间隔、最大尝试次数和停止任务。
- 不提交真实预约的试运行，任务状态和操作日志。
- 预约成功邮件通知、SMTP 设置、发送测试邮件和通知结果。
- 配置在应用关闭、重新打开后保留。

安卓端的登录替换了桌面端的 Cookie 输入，其余预约、筛选、调度和邮件逻辑直接复用 `hdu_seat`，不维护另一份预约接口实现。

## 后台运行与数据

应用通过前台服务运行本机面板和预约任务，系统通知提供返回应用或停止服务的入口。建议允许通知，以便查看服务状态。定时启动使用北京时间；手机需保持联网。

Android 的省电模式、厂商后台限制、强行停止应用、关闭服务、重启手机或网络中断均可能中断任务。应用不承诺在这些情况下自动恢复预约；重要定时任务应提前打开应用，确认服务正在运行。关闭网页视图或切换到其他应用与停止服务是不同的操作。

配置和会话保存在应用私有目录；APK 不包含任何账号、密码或预置会话。学校登录页与具备本机功能的面板使用不同 WebView，学校页面不具有应用的 JavaScript 接口。本机 HTTP 服务只监听回环地址，并使用随机端口和随机路径隔离接口。面板接口不向 JavaScript 返回会话明文。卸载应用会删除应用数据；普通升级保留配置。

邮件功能仍需要用户自己的 SMTP 授权码和可访问的邮件服务器；它与学校登录密码无关。

## 构建

使用 JDK 17、Python 3.13 和 Android SDK 35。项目提供 Gradle Wrapper，无需全局安装 Gradle。首次构建需要联网下载 Gradle、Android 插件和 Chaquopy 运行时。

Windows 安装 Android Studio 或 Android 命令行工具，设置 `JAVA_HOME`、`ANDROID_HOME`，安装 `platforms;android-35` 与 `build-tools;35.0.0`，然后在仓库根目录运行：

```powershell
.\build-android.ps1
```

调试包位于 `dist/android/HDU-Library-Seat-Android-debug.apk`。调试包用于开发验证，不能覆盖使用正式密钥签名的安装包；切换两种签名需要先卸载，卸载会删除配置。

macOS/Linux 可直接执行：

```bash
cd android
./gradlew assembleDebug
```

### 正式签名

正式发布使用独立且持续保留的签名密钥。密钥文件和密码不进入 Git。需要创建自己的密钥时，可运行以下命令并按提示设置密码，然后安全备份密钥：

```powershell
keytool -genkeypair -keystore android-release.jks -alias hdu-seat -keyalg RSA -keysize 3072 -validity 10000
```

正式构建前设置环境变量：

| 变量 | 含义 |
| --- | --- |
| `HDU_ANDROID_KEYSTORE_PATH` | 密钥文件的绝对路径 |
| `HDU_ANDROID_KEYSTORE_PASSWORD` | 密钥库密码 |
| `HDU_ANDROID_KEY_ALIAS` | 密钥别名 |
| `HDU_ANDROID_KEY_PASSWORD` | 私钥密码 |

随后运行 `./build-android.ps1 -Variant Release` 或在 `android` 目录运行 `./gradlew assembleRelease`。正式产物为 `dist/android/HDU-Library-Seat-Android.apk`（PowerShell 脚本）或 `android/app/build/outputs/apk/release/app-release.apk`（Gradle）。缺少签名环境时，不应将未签名 release 文件作为可安装正式版本发布。

### GitHub Actions

工作流 [android-apk.yml](../.github/workflows/android-apk.yml) 支持手动运行，并在安卓、共享 Python 或相关测试更新时自动构建。它运行共享 Python 测试、Android lint、调试构建和 Android 15 模拟器安装测试。

仓库 Actions Secrets 配置以下字段后，工作流额外构建并验证正式签名 APK：

| Secret | 值 |
| --- | --- |
| `HDU_ANDROID_KEYSTORE_BASE64` | 密钥文件的 Base64 编码 |
| `HDU_ANDROID_KEYSTORE_PASSWORD` | 密钥库密码 |
| `HDU_ANDROID_KEY_ALIAS` | 密钥别名 |
| `HDU_ANDROID_KEY_PASSWORD` | 私钥密码 |

`android-apk` 构建产物包含 APK 和 SHA-256 校验值；`android-verification` 包含模拟器截图、检查结果和 lint 报告。没有签名凭据的构建只提供调试 APK。后续版本必须使用同一密钥，才能直接升级已安装的正式版。

## 验证范围

模拟器检查实际 APK 启动、嵌入式 Python 面板、手机布局、配置保存与进程重启后读取、未登录请求拦截、登录页隔离和正式 APK 安装。测试使用空会话与虚构偏好，不提交真实座位预约。学校账号密码登录、真实座位查询和实际邮件投递需要用户自己的有效账号与网络环境，发布检查不代替这些账号级验证。

在已启动的模拟器上手动复现检查：

```bash
python -m pip install websocket-client==1.8.0
python packaging/smoke_android.py --debug-apk dist/android/HDU-Library-Seat-Android-debug.apk --release-apk dist/android/HDU-Library-Seat-Android.apk
```

参考：[Chaquopy Android 构建文档](https://chaquo.com/chaquopy/doc/current/android.html)、[Android 前台服务](https://developer.android.com/develop/background-work/services/fgs)、[Android 模拟器 CI 工具](https://github.com/ReactiveCircus/android-emulator-runner)。
