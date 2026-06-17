# DeepSeek Monitor

> DeepSeek API 余额监控悬浮窗

屏幕右下角的半透明悬浮窗，鼠标悬停展开完整信息卡片，移开自动折叠。支持多 API Key 监控，帮你实时掌握 DeepSeek 账户余额和 Token 使用量。

## 截图

```
折叠态：                              展开态：
┌─────────────────────┐              ┌──────────────────────────────────┐
│ root@DeepSeek:~$ ¥8.19│              │ ┌─ DEEPSEEK MONITOR v2.0 ────────┐   │
└─────────────────────┘              │ [20:31:42] 连接已建立             │
                                     │                                  │
                                     │ > ¥ 8.19                         │
                                     │ TOTAL BALANCE                    │
                                     │ - - - - - - - - - - - - - - - -  │
                                     │ API_KEYS:                        │
                                     │ ✓ 默认          ¥8.19            │
                                     │ - - - - - - - - - - - - - - - -  │
                                     │ TOKEN_USAGE:                     │
                                     │ prompt:              0           │
                                     │ completion:          0           │
                                     │ total:               0           │
                                     │ est_cost:     ¥0.0000            │
                                     │ - - - - - - - - - - - - - - - -  │
                                     │ last_sync: 10s ago       ONLINE  │
                                     │                       [SYNC]    │
                                     │ └───────────────────────────────┘ │
                                     │ [右键菜单] [双击配置] [拖拽移动]   │
                                     └──────────────────────────────────┘
```

## 功能

| 功能 | 操作 |
|------|------|
| 余额监控 | 自动定时刷新，折叠态直接显示余额 |
| 多 Key 支持 | 管理多个 API Key，合并显示总余额 |
| Token 统计 | 按日累计 prompt / completion tokens |
| 悬停展开 | 鼠标移入自动展开完整卡片 |
| 移开折叠 | 鼠标移走 0.35s 后自动折叠 |
| 拖拽移动 | 按住左键拖到任意位置，下次启动记住 |
| 右键菜单 | 刷新、管理 Key、切换间隔、退出 |
| 刷新间隔 | 15s / 30s / 60s / 120s 可选 |
| Ghost 窗口 | 不抢焦点、不在任务栏和 Alt+Tab 中显示 |

## 安装

### 方式一：下载 exe 直接运行

从 [Releases](../../releases) 页面下载 `DeepSeekMonitor.exe`，双击运行。

> Windows 可能会弹出 SmartScreen 警告，点「更多信息 → 仍要运行」即可。

### 方式二：Python 源码运行

```bash
git clone https://github.com/stn0402/DeepSeekMonitor.git
cd DeepSeekMonitor
pip install requests
python deepseek_monitor.py
```

### 打包说明

如需自行打包 exe：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name DeepSeekMonitor deepseek_monitor.py
```

## 使用

1. **首次运行**：自动弹出 API Key 配置窗口
2. **添加 Key**：右键菜单 → 管理 API Keys → 添加 DeepSeek API Key（以 `sk-` 开头）
3. **查看余额**：折叠态即可看到总余额
4. **查看详情**：鼠标移到悬浮窗上展开
5. **移动位置**：按住左键拖拽

## 配置

配置文件自动生成在 `%APPDATA%\DeepSeekMonitor\config.json`：

- `api_keys`：API Key 列表（标签+Key）
- `refresh_interval_seconds`：刷新间隔（默认 30 秒）
- `token_usage_daily`：按日累计的 Token 统计

## 系统要求

- Windows 10 / 11（64 位）
- 无需安装 Python 环境（exe 版）
- 纯本地运行，API Key 仅存在本地配置文件中

## 技术栈

- Python 3.14
- tkinter（GUI）
- requests（HTTP）
- PyInstaller（打包）

## License

MIT
