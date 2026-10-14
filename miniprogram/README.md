# 皮皮猴微信小程序

原生小程序，对接现有 FastAPI `/ws`，无需 npm 构建。网页端仍在 `web/`。

## 开发与连接

1. 在项目根目录安装 Python 依赖：`python -m pip install -r requirements.txt`。
2. 保持原有 `.env` 中的 Qwen 配置；启动后端：`python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`。
3. 微信开发者工具导入本目录，替换 `project.config.json` 中的 `appid` 为自己的小程序 AppID。游客模式仅用于查看项目，录音联调请使用自己的 AppID。
4. 修改 `config.js` 的 `websocketUrl`。工具本机调试可用 `ws://127.0.0.1:8000/ws`；手机不能用此地址，需使用手机可访问的电脑局域网 IP，电脑和手机连接同一 Wi-Fi，并允许防火墙入站。
5. 本地调试时，在工具的本地设置中临时开启“不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书”。正式项目保持域名校验开启。
6. 使用真机调试，允许麦克风权限，点击“开始对话”。连接收到 `session_ready` 后才开始录音。拒绝授权后可点击“麦克风权限设置”。

## 发布配置

- 将 Python 后端部署到手机可访问的服务器，通过有效 TLS 证书提供 `wss://你的域名/ws`，反向代理需支持 WebSocket Upgrade 和长连接。
- 在小程序管理后台配置对应的 socket 合法域名，更新 `config.js`。
- 按实际录音数据用途完善小程序用户隐私保护指引与平台要求的授权配置，再进行体验版真机测试。
- 模型 API Key 只保留在服务端 `.env`。当前 `/ws` 继承原项目的无鉴权设计；公开运营前应补充身份校验和使用限额。

## 音频协议与验证

输入使用 `RecorderManager`：大写 `format: 'PCM'`、16 kHz、单声道、2 KB 分帧，直接通过 WebSocket 发送 PCM16 二进制。输出将后端的 Base64 PCM16 按 24 kHz 转换为 WebAudio buffer 排队播放；说话打断与 `playback_cancel` 会清空队列。服务端音频采样率须与 `config.js` 一致。微信官方类型定义支持 PCM 及其录音分帧：
https://github.com/wechat-miniprogram/api-typings/blob/master/types/wx/lib.wx.api.d.ts

录音最长十分钟，达到限制后提示重新开始；切到后台、退出页面、系统录音中断或连接错误会结束对话。未自动重连，避免在用户无感知时恢复麦克风。

运行 `node --test miniprogram/tests/*.test.js`（从仓库根目录）检查音频转换、打断、连接取消及录音失败等逻辑。测试使用 API mock，不能代替微信真机验证。重点验证 iOS / Android 上 PCM 分帧、连续播放、拒绝授权、断网、快速结束再开始和后台切换。开发者工具的录音行为不能代表真机。
