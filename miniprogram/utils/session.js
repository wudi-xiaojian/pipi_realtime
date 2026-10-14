const PCMPlayback = require('./playback');

class VoiceSession {
  constructor(api, config, callbacks) {
    this.api = api;
    this.config = config;
    this.callbacks = callbacks;
    this.playback = new PCMPlayback(api, config.outputSampleRate);
    this.recorder = api.getRecorderManager();
    this.active = false;
    this.recording = false;
    this.recordPending = false;
    this.generation = 0;
    this.pendingBytes = 0;
    this.socket = null;
    this.timer = null;
    this.listeners = {
      Start: () => {
        this.recordPending = false;
        this.recording = true;
        if (!this.active) { this.recorder.stop(); return; }
        clearTimeout(this.timer);
        this.callbacks.status('listening', '可以说话了');
        this.callbacks.ready();
      },
      FrameRecorded: ({ frameBuffer }) => {
        if (!this.active || !this.recording || !this.socket || !frameBuffer.byteLength) return;
        if (this.pendingBytes > 256 * 1024) { this.fail('网络较慢，请重新开始对话'); return; }
        const generation = this.generation;
        this.pendingBytes += frameBuffer.byteLength;
        this.socket.send({
          data: frameBuffer,
          fail: () => { if (generation === this.generation) this.fail('语音发送失败'); },
          complete: () => { if (generation === this.generation) this.pendingBytes -= frameBuffer.byteLength; }
        });
      },
      Stop: () => {
        this.recording = false;
        this.recordPending = false;
        if (this.active) this.fail('录音已结束，请点击开始对话继续');
        this.callbacks.settled();
        if (this.destroyed) this.removeListeners();
      },
      Error: (error) => {
        this.recording = false;
        this.recordPending = false;
        if (this.active) this.fail(error.errMsg || '录音失败，请检查麦克风权限和微信版本');
        this.callbacks.settled();
        if (this.destroyed) this.removeListeners();
      },
      InterruptionBegin: () => { if (this.active) this.fail('录音被系统中断，请稍后重新开始'); }
    };
    Object.keys(this.listeners).forEach(name => this.recorder['on' + name](this.listeners[name]));
  }

  async start() {
    if (this.active || this.recording || this.recordPending) return;
    this.active = true;
    const generation = ++this.generation;
    this.callbacks.status('thinking', '正在连接…');
    try {
      await new Promise((resolve, reject) => this.api.authorize({ scope: 'scope.record', success: resolve, fail: reject }));
      if (!this.active || generation !== this.generation) return;
      this.playback.open();
      this.callbacks.connection('正在连接语音服务');
      const socket = this.api.connectSocket({
        url: this.config.websocketUrl,
        fail: () => { if (generation === this.generation) this.fail('无法建立连接，请检查服务地址'); }
      });
      if (!this.active || generation !== this.generation) { socket.close({}); return; }
      this.socket = socket;
      const current = () => this.active && generation === this.generation;
      this.timer = setTimeout(() => { if (current()) this.fail('语音服务连接超时'); }, this.config.connectionTimeout);
      socket.onOpen(() => {
        if (!current()) return;
        this.callbacks.connection('已连接，正在准备语音');
        socket.send({ data: JSON.stringify({ type: 'start' }), fail: () => { if (current()) this.fail('启动消息发送失败'); } });
      });
      socket.onMessage(({ data }) => {
        if (!current() || typeof data !== 'string') return;
        let message;
        try { message = JSON.parse(data); } catch (_) { this.fail('服务返回了无效消息'); return; }
        try { this.handle(message); } catch (error) { this.fail(error.message || '语音处理失败'); }
      });
      socket.onError(() => { if (current()) this.fail('连接失败，请检查网络和服务地址'); });
      socket.onClose(() => { if (current()) this.fail('连接已断开，请重新开始'); });
    } catch (error) {
      if (this.active && generation === this.generation) {
        this.fail(error.message || '无法录音，请在设置中允许麦克风权限');
      }
    }
  }

  handle(message) {
    if (message.type === 'session_ready') {
      if (this.recordPending || this.recording) return;
      this.callbacks.connection('语音服务已就绪');
      this.recordPending = true;
      // 必须使用大写 PCM。MP3/AAC 分片不能直接发送到现有 PCM16 后端。
      this.recorder.start({ duration: 600000, sampleRate: this.config.inputSampleRate,
        numberOfChannels: 1, format: 'PCM', frameSize: 2 });
    } else if (message.type === 'assistant_audio' && message.audio) {
      this.playback.play(message.audio);
    } else if (message.type === 'speech_started' || message.type === 'playback_cancel') {
      this.playback.stop();
    } else if (message.type === 'response_done' && message.status === 'cancelled') {
      this.playback.stop();
    } else if (message.type === 'error') {
      this.fail(message.message || '语音服务出现问题');
      return;
    }
    this.callbacks.message(message);
  }

  fail(message) {
    this.stop();
    this.callbacks.status('error', '对话已停止');
    this.callbacks.connection(message);
  }

  stop() {
    this.active = false;
    ++this.generation;
    clearTimeout(this.timer);
    this.timer = null;
    const socket = this.socket;
    this.socket = null;
    this.pendingBytes = 0;
    if (socket) {
      try {
        socket.send({ data: JSON.stringify({ type: 'stop' }), complete: () => socket.close({}) });
      } catch (_) { socket.close({}); }
    }
    this.playback.close();
    if (this.recording || this.recordPending) this.recorder.stop();
    this.callbacks.stopped();
    if (!this.recording && !this.recordPending) this.callbacks.settled();
  }

  destroy() {
    this.destroyed = true;
    this.stop();
    // 停止回调可能晚于页面销毁；旧页面不再接收更新。
    this.callbacks = { status() {}, connection() {}, ready() {}, message() {}, stopped() {}, settled() {} };
    if (!this.recording && !this.recordPending) this.removeListeners();
  }

  removeListeners() {
    Object.keys(this.listeners).forEach(name => this.recorder['off' + name](this.listeners[name]));
  }
}

module.exports = VoiceSession;
