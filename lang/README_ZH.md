# WorkshopDL — Python Edition

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)
![Platform](https://img.shields.io/badge/平台-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/许可证-MIT-orange)

**跨平台 Steam Workshop 模组下载器，提供简洁的图形界面。**  
灵感来自 imwaitingnow 的原版 [WorkshopDL](https://github.com/imwaitingnow/WorkshopDL)。

</div>

---

## 🌐 其他语言版本

| 语言 | 文件 |
|---|---|
| 🇬🇧 English | [README.md](README.md) |
| 🇷🇺 Русский | [README_RU.md](README_RU.md) |
| 🇩🇪 Deutsch | [README_DE.md](README_DE.md) |
| 🇨🇳 中文 | [README_ZH.md](README_ZH.md) ← 当前页面 |

> 想添加您的语言？请参阅下方[翻译](#-翻译)部分。

---

## ✨ 功能特性

- **⬇ 下载模组** — 通过 SteamCMD 下载单个模组或整个列表
- **📦 导入 Steam 合集** — 粘贴合集链接，所有模组自动添加
- **🔍 自动识别 Game ID** — 只需粘贴 Mod ID，Game ID 会自动填写
- **🔄 更新检查** — 扫描本地模组文件夹，显示哪些模组已过时
- **⏸ 暂停与恢复** — 中途停止下载，下次启动时继续
- **🔘 启用 / 禁用模组** — 无需删除即可切换模组（将文件夹重命名为 `.disabled`）
- **📋 游戏历史** — 记住所有曾下载过模组的游戏
- **📁 一键打开文件夹** — 直接从表格中打开模组或游戏文件夹
- **💾 大小列** — 显示每个模组占用的磁盘空间
- **🌐 本地化** — 通过简单的 JSON 文件实现完整的界面翻译
- **🖥 跨平台** — Windows、Linux、macOS

---

## 📦 运行要求

```
Python 3.8+
PyQt5
requests
```

安装依赖：
```bash
pip install PyQt5 requests
```

---

## 🚀 快速开始

1. 克隆或下载本仓库
2. 安装依赖（见上方）
3. 运行：
   ```bash
   python workshopdl.py
   ```
4. 进入 **设置** → 点击 **⬇ 自动下载 SteamCMD**
5. 在 **下载** 标签页中输入 Mod ID — Game ID 将自动检测
6. 点击 **⬇ 下载**

---

## 🗂 项目结构

```
WorkshopDL/
├── workshopdl.py        # 主程序
├── lang_en.json         # 英文本地化（默认）
├── lang_ru.json         # 俄文本地化
├── lang/                # 社区语言文件（可选）
│   ├── lang_de.json
│   └── lang_zh.json
├── Modules/             # 运行时数据（自动创建）
│   ├── queue.json       # 暂停/恢复队列
│   ├── history.json     # 游戏历史
│   └── mod_paths.json   # 已保存的模组文件夹路径
├── steamcmd/            # SteamCMD 安装目录（自动创建）
└── WorkshopDL.ini       # 用户设置
```

---

## 🔄 更新检查

**🔄 检查更新** 标签页可扫描任意本地模组文件夹
（例如：`C:\games\SovietRepublic\media_soviet\workshop_wip`）。

该文件夹必须包含以数字命名的子文件夹——每个模组一个：
```
workshop_wip/
├── 1797996358/
├── 1807300910/
└── 2031421793.disabled   ← 已禁用的模组
```

WorkshopDL 将本地文件夹的修改时间与 Steam API 的 `time_updated` 字段进行比较，
并为每个模组标注状态：

| 图标 | 含义 |
|---|---|
| 🔴 | 已过时 — 服务器有更新版本 |
| 🟢 | 已是最新 |
| 🔘 | 已禁用（文件夹带有 `.disabled` 后缀） |
| ⚪ | 未知 — Steam API 未返回数据 |

---

## 🔘 启用 / 禁用模组

点击表格中的 **⏸ / ▶** 按钮来切换模组状态。  
程序只是重命名文件夹：

```
1797996358          →   1797996358.disabled    （已禁用）
1797996358.disabled →   1797996358             （已启用）
```

不会删除任何文件。

---

## 🌐 翻译

所有界面字符串均存储在单个 JSON 文件中。创建新翻译的步骤：

1. 复制 `lang_en.json` 并重命名，例如 `lang_fr.json`
2. 翻译**值**（每行的右侧）— 不要修改键名
3. 在 **设置 → 语言** 中浏览到该文件，点击 **✅ 应用**

### 贡献翻译

要与所有用户共享您的翻译：
- 将 `lang_XX.json` 添加到本仓库的 `lang/` 文件夹中
- 提交 Pull Request

---

## ⚙ 设置说明

| 设置项 | 说明 |
|---|---|
| 匿名模式 | 无需 Steam 账号下载（大多数模组支持） |
| Steam 账号 / 密码 | 仅在关闭匿名模式时需要 |
| SteamCMD 路径 | `steamcmd` 可执行文件的路径 — 或自动下载 |
| 语言 | 本地化 `.json` 文件的路径 |
| 模组文件夹 | 更新检查的默认文件夹 |

---

## 🛠 SteamCMD

WorkshopDL 使用 [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)
下载模组。无需手动安装——进入 **设置**，点击 **⬇ 自动下载 SteamCMD** 即可。

首次运行时，SteamCMD 会下载自身的引擎文件（约 40 MB），
这只发生一次，过程会显示在设置日志中。

| 平台 | 可执行文件 | 压缩包 |
|---|---|---|
| Windows | `steamcmd.exe` | `.zip` |
| Linux | `steamcmd.sh` | `.tar.gz` |
| macOS | `steamcmd` | `.tar.gz` |

---

## 📄 许可证

MIT — 随意使用，注明出处不胜感激。

---

<div align="center">
用 ☕ 和 PyQt5 制作
</div>
