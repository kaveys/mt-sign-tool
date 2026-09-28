# MT论坛自动签到工具

针对 **MT论坛（bbs.binmt.cc）**（Discuz! + k_misign 签到插件）的自动签到脚本，覆盖 **Windows 桌面 GUI 版** 与 **青龙面板命令行版** 两种形态。

**核心特点：零第三方依赖** —— 全部基于 Python 标准库（`urllib` / `http.cookiejar` / `ssl` / `tkinter`），无需 `requests`、`bs4` 等任何第三方包。

---

## ✨ 功能特性

- **多账号批量签到**：一次配置多个账号，逐个执行，自动处理间隔。
- **账号密码 + Cookie 双通道**：既支持表单登录，也支持直接导入已登录 Cookie（WAF/CDN 拦截场景下最有效的兜底）。
- **防风控随机延迟**：签到前随机等待、账号间随机间隔，降低被识别风险。
- **HTTP/HTTPS 代理出口**：本机或服务器 IP 被论坛拦截时可配置代理（如住宅代理 / 家庭宽带出口）。
- **自动重登录**：Cookie 过期或未登录时自动回退重登后再签到。
- **智能结果解析**：兼容 Discuz inajax 回调、`<root>` XML、纯回调、`+N 金币` 等多种签到响应格式。
- **完整日志**：本地文件日志（GUI 版）+ 青龙面板日志与多级推送通知。
- **单文件形态**：GUI 版与青龙版各自内嵌全部核心代码，可独立运行或打包。

---

## 📁 文件结构与说明

| 文件 | 说明 |
| --- | --- |
| `mt_sign.py` | **GUI 版**（Tkinter 桌面界面，单文件独立运行）。账号管理、签到设置、代理 / Cookie 导入导出 Tab、实时运行日志。可打包为 Windows 单文件 EXE。 |
| `mt_sign_qinglong.py` | **青龙面板版**（命令行，单文件独立运行）。账号密码通过环境变量填写，零改代码，适配青龙通知（Server酱 / PushPlus / Bark / 钉钉 / 企业微信 / Telegram 等）。 |
| `mt_sign_core.py` | **核心模块**。包含 `HttpSession`（纯标准库 HTTP 会话）、`BinMTSigner`（登录 + 签到逻辑）、`ConfigManager`（GUI 配置存储）。供其余版本复用。 |
| `test_sign_parse.py` | **TDD 单元测试**。复现并验证签到响应解析逻辑的 Bug 修复，覆盖 Discuz/k_misign 的各种响应格式。 |
| `MT论坛签到工具.spec` | PyInstaller 打包配置文件（生成单文件 EXE）。 |
| `icon.ico` | Windows EXE 图标。 |
| `icon_source.jpg` | 图标源图。 |

> ⚠️ **安全提示**：`mt_config.json`（GUI 版账号密码配置）与 `mt_sign.log`（运行日志）包含敏感信息，**不会上传到本仓库**，请勿外传。

---

## 🖥️ GUI 版使用（mt_sign.py）

### 源码运行

```bash
python mt_sign.py
```

### 打包为 Windows 单文件 EXE

```bash
pip install pyinstaller
pyinstaller -F -w --clean --noconfirm -n "MT论坛签到工具" --icon=icon.ico --add-data "icon.ico;." mt_sign.py
```

- `-F`：单文件打包；`-w`：运行时不弹黑色控制台窗口。
- 产物：`dist\MT论坛签到工具.exe`，可直接拷走双击使用。
- 账号密码保存在 EXE 同目录的 `mt_config.json`。

### 界面操作

- **账号管理**：添加 / 删除账号、显示 / 隐藏密码、查看上次签到时间与状态。
- **签到设置**：启动自动签到、启用随机延迟、自定义延迟范围（秒）。
- **代理出口**（高级）：填 HTTP/HTTPS 代理，如 `http://127.0.0.1:7890`。
- **Cookie 导入 / 导出**（终极兜底）：把已登录的 Cookie 以 JSON 粘贴导入；也可在能登录的环境下导出 Cookie 供青龙版使用。

---

## 🐉 青龙面板版使用（mt_sign_qinglong.py）

### Step 1 · 上传脚本

将 `mt_sign_qinglong.py` 上传到青龙面板的 `scripts` 目录（单文件，无需其他文件）。

### Step 2 · 配置账号（环境变量，三选一）

| 变量名 | 格式 / 示例 |
| --- | --- |
| `MT_BBS_ACCOUNTS`（推荐） | 多账号：`user1#pwd1 & user2|pwd2`（账号间用 `&` 或换行，账号内用 `#`/`|` 等分隔） |
| `MT_BBS_USER` + `MT_BBS_PASSWORD` | 单账号分两个变量 |
| `MT_BBS_JSON` | JSON 数组：`[{"username":"xx","password":"xx"}]` |

### Step 3 ·（可选）控制变量

| 变量名 | 说明 | 默认 |
| --- | --- | --- |
| `MT_BBS_RANDOM_DELAY` | 签到前随机延迟 | `true` |
| `MT_BBS_DELAY_MIN` / `MT_BBS_DELAY_MAX` | 延迟范围（秒） | `60` / `300` |
| `MT_BBS_NOTIFY` | 通知策略：`always`/`fail`/`never` | `fail` |
| `MT_BBS_INTERVAL_MIN` / `MT_BBS_INTERVAL_MAX` | 多账号间隔（秒） | `2` / `6` |
| `MT_BBS_PROXY` | 代理出口 | 空（直连） |
| `MT_BBS_COOKIE_JSON` | 导入已登录 Cookie（绕过 WAF） | 空 |

### Step 4 · 创建任务

- 命令 / 脚本：`task mt_sign_qinglong.py`
- 推荐定时规则：`0 10 8 * * ?`（每天 8:10，避开 0 点高压期）

### Step 5 · 通知

在青龙「系统设置 → 通知设置」配置推送渠道后，脚本按三级 fallback 自动推送：
① `notify.py` 经典发送 → ② `ql notify` CLI → ③ 裸 `notify` 命令 → ④ 输出到日志兜底。

---

## 🧪 测试（test_sign_parse.py）

解析逻辑曾有一个典型 Bug：**第一次点击签到论坛实际成功，脚本却判定失败**。

根因：
1. `format=empty&inajax=1` 返回的是 Discuz inajax 回调格式，不是 `<root>` XML；
2. 成功关键词集合过窄，漏掉「恭喜 / 奖励 / 积分 / 金币 / +XX」等常见成功提示。

`test_sign_parse.py` 以 TDD 方式复现并验证修复，覆盖 `succeedhandle_` 回调、`<root>` XML、纯回调、`+10 金币`、重复签到、需要登录、真正失败等多种响应变体。

运行测试：

```bash
python test_sign_parse.py
```

---

## 📌 说明与免责

- 本工具仅供个人自动化签到使用，请遵守论坛规则与相关法律法规，勿滥用或用于非法用途。
- 请勿在凌晨 0 点集中签到，避免给服务器造成瞬时压力。
- 涉及账号密码、Cookie 等敏感信息请妥善保管，不要提交到公开仓库或泄露给他人。
