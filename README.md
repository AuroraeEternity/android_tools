# Android Test Efficiency Tool

一套基于 **Flask + Vue 3** 的安卓测试效能工具，整合了 DoKit 常用能力，可在浏览器中完成设备管理、安装卸载、截图录屏、Monkey、日志导出、分辨率及性能监控等操作。

## 功能总览

| 模块 | 关键能力 |
| ---- | -------- |
| 设备 & 应用 | 设备自动发现、前台应用套取、包名自动补全、杀端重启、清数据、卸载、发送文本 |
| 文件 & 安装 | APK 上传安装、Python 脚本上传执行（返回 stdout/stderr） |
| 媒体工具 | 截屏 / 录屏（即时预览、复制链接、复制图片到剪贴板）、打开 URL |
| scrcpy 控制 | 一键打开 / 关闭 / 重新打开桌面 scrcpy（需本机已安装） |
| 崩溃 / ANR 捕获 | SSE 秒级捕获 FATAL EXCEPTION / ANR，堆栈展开查看 |
| 网络诊断 | 设备端 tcpdump 抓包、基于 tc netem 的弱网注入（需 Root） |
| 稳定性 | Monkey 测试（事件数/节流配置）、logcat 导出、JS 日志导出 |
| 分辨率 | 查看当前分辨率、应用预设分辨率、重置为原始值 |
| 性能监控 | 内存 / CPU / FPS / GPU Jank & 百分位曲线实时展示 |
| 埋点校验 | 维护 eventName 期望清单，一键校验是否命中并输出示例 |
| 日志监控 | SSE 实时 logcat，包含 JSON 埋点模式、关键字高亮、导出按钮 |

## 目录结构

```
backend/        Flask API（ADB 工具、REST 接口、文件目录）
frontend/       Vue 3 + Element Plus + Vite 前端
uploads/        临时存放上传的 APK/脚本/录屏
captures/       截图与录屏产物（自动生成）
logs/           导出的 logcat / JS 日志
run.sh          一键启动脚本（可选）
```

> 首次运行会自动创建 `uploads/`, `captures/`, `logs/` 目录。完成下载后建议定期清理。

## 环境要求

- Python 3.8+
- Node.js 16+
- ADB（已配置到 PATH）
- 至少一台开启 USB 调试的 Android 设备（USB/Wi-Fi 连接均可）

## 启动方式

### 一键启动

```bash
chmod +x run.sh
./run.sh
```
后端默认端口 `5000`，前端默认端口 `5173`。

### 手动启动

```bash
# Backend
cd backend
pip install -r requirements.txt
python app.py

# Frontend
cd frontend
npm install
npm run dev
```

## Web 端使用指南

1. 打开前端地址（`http://localhost:5173`），顶部选择设备，可随时刷新。  
2. **设备控制**：在左侧导航切换到“设备控制”，按顺序使用以下面板：  
   - *DevicePanel*：选择包名、清数据、卸载应用，可一键获取当前前台包名。  
   - *scrcpy 控制*：DevicePanel 底部的按钮会直接调用本机 scrcpy，支持启动 / 关闭 / 重新打开。  
   - *FileOps*：上传 APK 安装、上传 Python 脚本并立即执行。  
   - *MediaTools*：截图或录屏后会自动出现在历史列表，支持在线预览、下载、复制链接，截图还可以一键复制到剪贴板；同时提供打开 URL 功能。  
   - *StabilityPanel*：配置并启动 Monkey，导出 logcat / JS 日志。  
   - *CrashPanel*：启动 SSE 监听即可秒级捕获 FATAL/ANR，支持展开堆栈与历史查看。  
   - *NetworkPanel*：可在设备上执行 tcpdump 抓包（生成 pcap）并注入弱网参数（延迟/丢包/限速），部分功能需 Root。  
   - *ResolutionPanel*：应用预设分辨率或恢复原始值。  
   - *PerformancePanel*：输入包名后开始采集，曲线实时刷新，可随时停止/清空，并展示 GPU Jank 百分比及 90/95 百分位耗时。  
   - *EventAuditPanel*：管理埋点期望列表（支持完全匹配），可直接校验日志命中情况并显示样例。  
3. **日志监控**：切换到“日志监控”菜单，默认实时拉取 logcat，可输入关键字搜索/完全匹配，高亮 JSON 埋点并支持导出。  
4. 所有截图、录屏、日志文件都通过 `/api/files` 提供下载链接，可在浏览器直接点击。

## scrcpy 控制说明

- 请在本机提前安装官方 scrcpy，例如 macOS 可执行 `brew install scrcpy`，Windows 可下载 [官方发布包](https://github.com/Genymobile/scrcpy).
- DevicePanel 中的“启动 / 关闭 / 重新打开 scrcpy”按钮，会在服务器本机直接执行 `scrcpy -s <device_id>`，并不会再启动 Web 端流媒体。
- 如果 scrcpy 已经在运行，再次点击“启动”会提示已运行；如遇异常，可用“重新打开 scrcpy”快速重启进程。
- 该功能依赖本机桌面环境，部署在无图形界面的服务器时请改用原生 scrcpy + VNC 或自行扩展。

## 建议的自检流程

1. 连接设备并在“设备控制”中查看是否能获取前台包名。  
2. 上传一个小型 APK 并安装，随后卸载。  
3. 执行一次截图、录屏，验证能下载文件。  
4. 启动一次 Monkey 并导出 logcat/JS 日志。  
5. 启动性能监控，观察 Chart.js 曲线实时刷新。  
6. 在日志监控页搜索某个 eventName，确认高亮与导出功能正常。

如需扩展新的工具，只需在后端新增 ADB 封装与 API，然后在前端添加对应面板即可。欢迎根据团队需求二次开发。

