# MyAIAgent

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## English

A modular, extensible AI agent built in Python bridging Telegram, Google Gemini, web capabilities, and WordPress publication.

### One-Click Installation (Recommended)

You can easily deploy MyAIAgent to a new machine using the automated setup scripts. The script will automatically check for dependencies, fetch the latest code, create an isolated virtual Python environment, and interactively help you configure your API keys through a professional web UI.

#### 🍎 macOS & 🐧 Linux
Copy and paste this command into your terminal:

```bash
bash <(curl -s https://raw.githubusercontent.com/nickyuanyaun/myaiagent/main/install.sh)
```

#### 🖥️ Windows
Copy and paste this line into an elevated **PowerShell** window:

```powershell
iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/nickyuanyaun/myaiagent/main/install.ps1'))
```

### Updating

If the developer releases new features, you can update your agent with a single command inside the `myaiagent` directory:

- **macOS & Linux**: `./update.sh`
- **Windows**: `.\update.ps1`

### Features
- **Intelligent Conversation**: Deeply integrated engine using Google Gemini.
- **Workflow Automation**: Support for recurring tasks (Cron) and actionable reminders.
- **Cross-user Messaging**: Route tasks and reminders to different Telegram IDs.
- **Content Pipeline**: Direct-to-draft automated WordPress blogging.
- **Media Support**: End-to-end image generation and web resource downloading.

---

<a name="中文"></a>
## 中文

一个基于 Python 的模块化、可扩展 AI 智能体，连接了 Telegram、Google Gemini、Web 能力以及 WordPress 发布平台。

### 一键安装 (推荐)

您可以使用自动化设置脚本轻松地将 MyAIAgent 部署到新机器上。脚本将自动检查依赖项、获取最新代码、创建隔离的虚拟 Python 环境，并通过专业的 Web 界面交互式地帮助您配置 API 密钥。

#### 🍎 macOS & 🐧 Linux
在您的终端中复制并粘贴此命令：

```bash
bash <(curl -s https://raw.githubusercontent.com/nickyuanyaun/myaiagent/main/install.sh)
```

#### 🖥️ Windows
在管理员模式的 **PowerShell** 窗口中复制并粘贴此行：

```powershell
iex ((New-Object System.Net.WebClient).DownloadString('https://raw.githubusercontent.com/nickyuanyaun/myaiagent/main/install.ps1'))
```

### 升级更新

如果开发者发布了新功能，您可以在 `myaiagent` 目录下通过简单的指令进行更新：

- **macOS & Linux**: `./update.sh`
- **Windows**: `.\update.ps1`

### 功能特性
- **智能对话**：深层集成的 Google Gemini 会话引擎。
- **流程自动化**：支持周期性任务 (Cron) 和可执行的定时指令。
- **跨用户消息**：支持将任务和提醒路由至不同的 Telegram 用户。
- **内容流水线**：端到端的 WordPress 自动博客草稿发布系统。
- **多媒体支持**：支持 AI 图片生成以及 Web 资源下载。
