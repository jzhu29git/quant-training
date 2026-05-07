# 接单群本地监控 MVP

这个工具用于最小化验证：手动打开企业微信接单群窗口后，本地复制当前可见消息文字，识别报价和任务关键词，命中后推送到飞书 webhook，并写入本地日志。

## 先验证规则

```powershell
python tools/order_monitor/order_monitor.py --dry-run-text "Need data analysis assignment, budget RMB 1500, due tonight"
```

## 安装 Python 依赖

```powershell
python -m pip install -r tools/order_monitor/requirements-order-monitor.txt
```

默认优先使用 `clipboard_drag`：在配置区域内拖拽选中文字、复制到剪贴板，再读取文本。若复制不可用，可以把 `source` 改成 `ocr`。

注意：`clipboard_drag` 会短暂占用鼠标和剪贴板。默认会在复制后恢复原剪贴板文本。

OCR 需要安装 Tesseract OCR。如果系统没有 `tesseract.exe`，请安装 Windows 版 Tesseract，并在 `config.json` 里设置：

```json
"ocr": {
  "language": "chi_sim+eng",
  "tesseract_cmd": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
}
```

## 配置

复制示例配置：

```powershell
Copy-Item tools/order_monitor/config.example.json tools/order_monitor/config.json
```

然后把飞书自定义机器人 webhook 填到：

```json
"notifications": {
  "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/...",
  "log_file": "tools/order_monitor/order_hits.log"
}
```

当前默认规则：

- 报价阈值：1000
- 任务关键词：data analysis, quiz, assignment, statistics, python, excel 等
- 排除关键词：不要、已接、结束、满了

默认只有当前窗口标题包含 `企业微信`、`WeCom` 或 `WeChat Work` 时才扫描，避免误扫浏览器或其他软件。

## 扫描一次

先手动打开企业微信接单群，并确保目标消息在屏幕上可见：

```powershell
python tools/order_monitor/order_monitor.py --config tools/order_monitor/config.json --once
```

## 持续扫描

```powershell
python tools/order_monitor/order_monitor.py --config tools/order_monitor/config.json --loop
```

按 `Ctrl+C` 停止。

## 缩小扫描区域

如果全屏 OCR 太慢或误报多，可以在 `config.json` 设置区域：

```json
"capture": {
  "region": [100, 100, 1100, 900]
}
```

格式是 `[左, 上, 右, 下]`，单位是屏幕像素。

如果企业微信窗口铺满屏幕，建议只圈右侧聊天消息区，不要包含左侧会话列表、顶部菜单和底部输入框。
