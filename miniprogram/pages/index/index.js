const config = require('../../config');
const VoiceSession = require('../../utils/session');

Page({
  data: {
    status: 'idle', statusText: '等待开始', connectionInfo: '尚未连接',
    running: false, connecting: false, stopping: false, messages: [], scrollTarget: ''
  },

  onLoad() {
    this.messageSequence = 0;
    this.currentMessages = { user: null, assistant: null };
    this.session = new VoiceSession(wx, config, {
      status: (status, statusText) => this.setData({ status, statusText }),
      connection: connectionInfo => this.setData({ connectionInfo }),
      ready: () => this.setData({ running: true, connecting: false }),
      stopped: () => {
        this.currentMessages = { user: null, assistant: null };
        this.setData({ running: false, connecting: false, stopping: true });
      },
      settled: () => this.setData({ stopping: false }),
      message: message => this.handleMessage(message)
    });
  },

  startConversation() {
    if (this.data.connecting || this.data.running || this.data.stopping) return;
    this.setData({ connecting: true });
    this.session.start();
  },

  stopConversation() {
    this.session.stop();
    this.setData({ status: 'idle', statusText: '等待开始', connectionInfo: '已停止' });
  },

  onHide() { this.stopConversation(); },
  onUnload() { this.session.destroy(); },
  openSettings() { wx.openSetting({}); },
  handleMessage(message) {
    const labels = {
      idle: '可以继续说话', listening: '正在听你说话…',
      thinking: '皮皮猴想一想…', speaking: '皮皮猴正在说话…'
    };
    if (message.type === 'state' && labels[message.state]) {
      if (this.data.running) this.setData({ status: message.state === 'idle' ? 'listening' : message.state, statusText: labels[message.state] });
    } else if (message.type === 'speech_started') {
      this.currentMessages.assistant = null;
      this.setData({ status: 'listening', statusText: labels.listening });
    } else if (message.type === 'speech_stopped') {
      this.setData({ status: 'thinking', statusText: labels.thinking });
    } else if (message.type === 'assistant_audio') {
      this.setData({ status: 'speaking', statusText: labels.speaking });
    } else if (message.type === 'response_done') {
      this.setData({ status: 'listening', statusText: labels.idle });
    } else if (message.type === 'user_transcript_delta' || message.type === 'user_transcript') {
      this.updateTranscript('user', message.text || '', message.type === 'user_transcript');
    } else if (message.type === 'assistant_transcript_delta' || message.type === 'assistant_transcript') {
      this.updateTranscript('assistant', message.text || '', message.type === 'assistant_transcript');
    }
  },

  updateTranscript(role, text, done) {
    if (!text && this.currentMessages[role] === null) return;
    let index = this.currentMessages[role];
    const messages = this.data.messages.slice();
    if (index === null) {
      index = messages.length;
      messages.push({ id: 'message-' + (++this.messageSequence), role, text: '' });
      this.currentMessages[role] = index;
    }
    messages[index] = Object.assign({}, messages[index], {
      text: done ? (text || messages[index].text) : messages[index].text + text
    });
    this.setData({ messages, scrollTarget: '' }, () => this.setData({ scrollTarget: 'conversation-end' }));
    if (done) this.currentMessages[role] = null;
  }
});
