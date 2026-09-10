# HDU Library Seat Helper / 杭电图书馆座位助手

[中文](#中文) · [English](#english)

一个面向杭州电子科技大学图书馆汇图/知书平台的本地座位预约工具。项目只使用 Python 标准库，提供 Web 可视化面板和命令行界面。

A local seat reservation helper for Hangzhou Dianzi University Library's Huitu/Zhishulib platform. It uses only the Python standard library and provides both a web dashboard and a command-line interface.

> [!IMPORTANT]
> 本项目不是学校或图书馆的官方服务。请遵守图书馆规则，合理设置轮询间隔，并妥善保管登录 Cookie。
>
> This is not an official university or library service. Follow library policies, use a reasonable polling interval, and keep your login cookie private.

## 中文

### 功能

- 在本地 Web 面板中查询、筛选和选择可预约座位
- 按座位编号、关键词、楼层等条件筛选
- 支持立即预约、指定使用时段和北京时间定时启动
- 支持试运行，不提交真实预约
- 提供等价的命令行操作
- Cookie 仅保存在本地配置中，不写入日志

### 环境要求

- Python 3.10 或更高版本
- 能正常访问 `hdu.huitu.zhishulib.com` 的网络环境
- 已登录图书馆系统后取得的有效 Cookie

项目没有第三方运行时依赖。

### 快速开始

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m hdu_seat init-config
python -m hdu_seat serve
```

然后打开 <http://127.0.0.1:8765>。Web 面板会把设置写入本地 `config.json`；该文件包含登录 Cookie，已经被 `.gitignore` 排除，请勿提交或分享。

macOS/Linux 激活虚拟环境时使用：

```bash
source .venv/bin/activate
```

也可以不安装项目，直接在项目根目录运行 `python -m hdu_seat serve`。

### 获取 Cookie

1. 在浏览器中打开图书馆座位页面并完成统一身份认证登录。
2. 按 `F12` 打开开发者工具，进入 **Network / 网络** 面板后刷新页面。
3. 选择一个发往 `hdu.huitu.zhishulib.com` 的请求。
4. 在 **Request Headers / 请求标头** 中复制完整的 `Cookie` 值。
5. 将它粘贴到 Web 面板，或写入本地 `config.json` 的 `cookie` 字段。

Cookie 相当于临时登录凭证。不要提交 `config.json`、粘贴到 Issue，或发送给他人；会话失效后请重新获取。

### 命令行用法

```powershell
# 从安全模板创建 config.json
python -m hdu_seat init-config

# 校验配置（不会输出 Cookie）
python -m hdu_seat validate-config

# 列出当前可预约座位
python -m hdu_seat list

# 只验证筛选结果，不提交预约
python -m hdu_seat once --dry-run

# 尝试一次预约
python -m hdu_seat once

# 按配置持续轮询，成功或达到 max_attempts 后停止
python -m hdu_seat run
```

使用其他配置文件时，在子命令前添加 `-c`：

```powershell
python -m hdu_seat -c my-config.json serve
```

Web 服务默认只监听 `127.0.0.1:8765`。不要将它绑定到 `0.0.0.0` 或直接暴露到公网，因为配置接口会处理 Cookie。

### 配置

复制 [`config.example.json`](config.example.json) 或运行 `init-config` 创建本地配置。

| 字段 | 含义 |
| --- | --- |
| `base_url` | 图书馆平台地址 |
| `cookie` | 登录后的完整 Cookie；也可通过 `HDU_LIBRARY_COOKIE` 环境变量提供 |
| `space_category.category_id` | 自习区域类别 ID |
| `space_category.content_id` | 自习室内容 ID |
| `booking.date` | 使用日期，格式为 `YYYY-MM-DD`；`null` 表示当天 |
| `booking.start_time` | 开始时间，格式为整点 `HH:MM`；`null` 表示立即 |
| `booking.duration_hours` | 使用时长（小时） |
| `booking.num` | 使用人数 |
| `rule.seat_ids` | 指定的内部座位 ID 或显示编号 |
| `rule.keywords` | 座位名称/区域必须包含的关键词 |
| `rule.preferred_floor` | 偏好楼层；`null` 表示不限 |
| `rule.avoid_near_door` | 是否排除靠门座位（取决于上游数据是否提供该标记） |
| `poll_interval` | 两次尝试之间的秒数 |
| `max_attempts` | 最大尝试次数 |
| `request_timeout` | 单次网络请求超时秒数 |
| `schedule_at` | 开始轮询的 ISO 时间；无时区偏移时按北京时间解释，`null` 表示立即 |

“预约使用时间”和 `schedule_at` 不同：前者是实际使用座位的时段，后者只是程序开始发送查询和预约请求的时间。

### 测试

```powershell
python -m unittest discover -v
```

测试使用模拟数据，不需要真实 Cookie，也不会访问图书馆接口。

### 项目结构

```text
hdu_seat/              核心 Python 包
  web/index.html       本地 Web 面板
tests/                 单元测试
config.example.json    可公开提交的配置模板
pyproject.toml         打包与项目元数据
```

### 常见问题

- **提示未登录或会话失效**：重新登录并更新 Cookie。
- **提示只支持整点**：将 `booking.start_time` 设置为类似 `08:00`、`18:00` 的整点。
- **`WinError 10013`**：Windows 防火墙、杀毒软件或当前运行环境阻止了 Python 访问网络，请为当前 Python 进程放行后重试。
- **需要图形验证码**：当前版本不会绕过验证码，请改用官方页面完成操作。

### 参与贡献

欢迎提交 Issue 或 Pull Request。请勿在测试、日志、截图或提交记录中包含真实 Cookie、学号、用户 ID 或预约响应数据；新增功能时请同时补充测试。

## English

### Features

- Browse, filter, and select reservable seats in a local web dashboard
- Filter by seat ID, keyword, floor, and other available metadata
- Reserve immediately, choose a booking window, or schedule polling in Beijing time
- Dry-run mode that never submits a reservation
- Equivalent command-line workflows
- Keeps the cookie in local configuration and out of logs

### Requirements

- Python 3.10 or newer
- Network access to `hdu.huitu.zhishulib.com`
- A valid cookie obtained after signing in to the library system

There are no third-party runtime dependencies.

### Quick start

Run the following commands from the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m hdu_seat init-config
python -m hdu_seat serve
```

Open <http://127.0.0.1:8765>. The dashboard stores its settings in the local `config.json`. This file contains your login cookie and is excluded by `.gitignore`; never commit or share it.

On macOS/Linux, activate the virtual environment with:

```bash
source .venv/bin/activate
```

You may also run `python -m hdu_seat serve` directly from the project root without installing the package.

### Getting a cookie

1. Open the library seat page and complete the university sign-in flow.
2. Press `F12`, select the browser's **Network** panel, and refresh the page.
3. Select a request sent to `hdu.huitu.zhishulib.com`.
4. Copy the complete `Cookie` value from **Request Headers**.
5. Paste it into the dashboard or save it under `cookie` in your local `config.json`.

A cookie is a temporary login credential. Never commit `config.json`, post it in an issue, or send it to anyone. Obtain a new cookie after the session expires.

### Command-line usage

```powershell
# Create config.json from the safe example
python -m hdu_seat init-config

# Validate the configuration without printing the cookie
python -m hdu_seat validate-config

# List seats that are currently reservable
python -m hdu_seat list

# Check matching and selection without submitting a reservation
python -m hdu_seat once --dry-run

# Attempt one reservation
python -m hdu_seat once

# Poll until successful or max_attempts is reached
python -m hdu_seat run
```

Pass `-c` before the subcommand to use another configuration file:

```powershell
python -m hdu_seat -c my-config.json serve
```

The web server listens on `127.0.0.1:8765` by default. Do not bind it to `0.0.0.0` or expose it directly to the public internet because its configuration API handles your cookie.

### Configuration reference

Copy [`config.example.json`](config.example.json) or run `init-config` to create a local configuration.

| Field | Description |
| --- | --- |
| `base_url` | Library platform URL |
| `cookie` | Complete signed-in cookie; alternatively use the `HDU_LIBRARY_COOKIE` environment variable |
| `space_category.category_id` | Study-area category ID |
| `space_category.content_id` | Room/content ID |
| `booking.date` | Booking date as `YYYY-MM-DD`; `null` means today |
| `booking.start_time` | Whole-hour start time as `HH:MM`; `null` means now |
| `booking.duration_hours` | Booking duration in hours |
| `booking.num` | Number of users |
| `rule.seat_ids` | Preferred internal seat IDs or displayed seat numbers |
| `rule.keywords` | Keywords required in seat names or areas |
| `rule.preferred_floor` | Preferred floor; `null` disables this filter |
| `rule.avoid_near_door` | Exclude seats marked as near a door when upstream data provides that flag |
| `poll_interval` | Seconds between attempts |
| `max_attempts` | Maximum number of attempts |
| `request_timeout` | Timeout for one network request, in seconds |
| `schedule_at` | ISO time at which polling starts; interpreted as Beijing time when no offset is present, or `null` for immediate start |

The booking window and `schedule_at` are separate: the former defines when the seat will be used, while the latter defines when the program starts querying and sending reservation requests.

### Tests

```powershell
python -m unittest discover -v
```

Tests use fixtures and mocks. They do not require a real cookie or access the library service.

### Project layout

```text
hdu_seat/              Core Python package
  web/index.html       Local web dashboard
tests/                 Unit tests
config.example.json    Public configuration template
pyproject.toml         Packaging and project metadata
```

### Troubleshooting

- **Not signed in / session expired**: sign in again and update the cookie.
- **Whole-hour start required**: use a time such as `08:00` or `18:00`.
- **`WinError 10013`**: allow the current Python process through Windows Firewall, antivirus, or other network controls.
- **Image CAPTCHA required**: this project does not bypass CAPTCHAs; complete the operation through the official page.

### Contributing

Issues and pull requests are welcome. Never include real cookies, student numbers, user IDs, or reservation responses in tests, logs, screenshots, or commits. Please add or update tests with functional changes.

## License / 许可证

This project is released under the [MIT License](LICENSE).

本项目采用 [MIT 许可证](LICENSE) 开源。
