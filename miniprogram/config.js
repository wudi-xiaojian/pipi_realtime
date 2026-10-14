// 真机使用电脑的局域网 IP 或已配置合法域名的 wss 地址。
// 此处只填写自己的 Python 后端地址，不要填写模型 API Key。
module.exports = {
  websocketUrl: 'ws://192.168.1.109:8000/ws',
  inputSampleRate: 16000,
  outputSampleRate: 24000,
  connectionTimeout: 15000
};
