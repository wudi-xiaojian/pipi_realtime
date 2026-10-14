class PCMPlayback {
  constructor(api, sampleRate) {
    this.api = api;
    this.sampleRate = sampleRate;
    this.context = null;
    this.sources = new Set();
    this.queueTime = 0;
  }

  open() {
    if (!this.api.createWebAudioContext) throw new Error('请更新微信后使用实时语音');
    this.context = this.api.createWebAudioContext();
    this.queueTime = 0;
    this.context.resume();
  }

  play(base64) {
    if (!this.context) return;
    const bytes = this.api.base64ToArrayBuffer(base64);
    if (!bytes.byteLength || bytes.byteLength % 2) throw new Error('收到无效的语音数据');
    const pcm = new DataView(bytes);
    const buffer = this.context.createBuffer(1, bytes.byteLength / 2, this.sampleRate);
    const samples = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) samples[i] = pcm.getInt16(i * 2, true) / 32768;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const now = this.context.currentTime;
    if (!Number.isFinite(now)) throw new Error('微信播放时钟无效，请重新开始对话');
    const start = Math.max(now + 0.02, this.queueTime);
    // 防止网络积压导致长时间播放过期回答。
    if (start - this.context.currentTime > 15) throw new Error('语音播放积压，请重新开始对话');
    this.queueTime = start + samples.length / this.sampleRate;
    this.sources.add(source);
    source.onended = () => { this.sources.delete(source); source.disconnect(); };
    source.start(start);
  }

  stop() {
    for (const source of this.sources) {
      source.onended = null;
      try { source.stop(); source.disconnect(); } catch (_) { /* 已结束 */ }
    }
    this.sources.clear();
    this.queueTime = this.context ? this.context.currentTime : 0;
  }

  close() {
    this.stop();
    if (this.context) this.context.close();
    this.context = null;
  }
}

module.exports = PCMPlayback;
