const test = require('node:test');
const assert = require('node:assert/strict');
const VoiceSession = require('../utils/session');
const PCMPlayback = require('../utils/playback');

function fixture() {
  const events = {};
  const recorder = { start(options) { this.options = options; }, stop() { this.stops = (this.stops || 0) + 1; } };
  ['Start', 'FrameRecorded', 'Stop', 'Error', 'InterruptionBegin'].forEach(name => {
    recorder['on' + name] = listener => { events[name] = listener; };
    recorder['off' + name] = () => { delete events[name]; };
  });
  const sockets = [];
  const sources = [];
  const buffers = [];
  const context = {
    currentTime: 1, destination: {}, resume() {}, close() { this.closed = true; },
    createBuffer(channels, length, rate) {
      const samples = new Float32Array(length);
      buffers.push(samples);
      return { duration: length / rate, getChannelData: () => samples };
    },
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start(time) { this.time = time; }, stop() { this.stopped = true; } };
      sources.push(source);
      return source;
    }
  };
  const api = {
    getRecorderManager: () => recorder,
    authorize: options => options.success(),
    createWebAudioContext: () => context,
    base64ToArrayBuffer: base64 => Uint8Array.from(Buffer.from(base64, 'base64')).buffer,
    connectSocket() {
      const socket = { sent: [], send(options) { this.sent.push(options.data); if (options.complete) options.complete(); }, close() { this.closed = true; } };
      ['Open', 'Message', 'Error', 'Close'].forEach(name => { socket['on' + name] = listener => { socket[name] = listener; }; });
      sockets.push(socket);
      return socket;
    }
  };
  const state = {};
  const callbacks = {
    status: (status, text) => Object.assign(state, { status, text }),
    connection: text => { state.connection = text; },
    ready: () => { state.ready = true; },
    stopped: () => { state.ready = false; },
    settled: () => { state.settled = true; },
    message: message => { state.message = message; }
  };
  const session = new VoiceSession(api, { websocketUrl: 'ws://localhost/ws', inputSampleRate: 16000, outputSampleRate: 24000, connectionTimeout: 1000 }, callbacks);
  return { session, api, state, sockets, recorder, events, context, sources, buffers };
}

test('waits for backend readiness and sends raw microphone PCM', async () => {
  const f = fixture();
  await f.session.start();
  const socket = f.sockets[0];
  socket.Open();
  assert.equal(f.recorder.options, undefined);
  socket.Message({ data: JSON.stringify({ type: 'session_ready' }) });
  assert.equal(f.recorder.options.format, 'PCM');
  assert.equal(f.recorder.options.sampleRate, 16000);
  f.events.Start();
  const pcm = new Int16Array([100, -100]).buffer;
  f.events.FrameRecorded({ frameBuffer: pcm });
  assert.equal(socket.sent[1], pcm);
  assert.equal(f.session.pendingBytes, 0);
  f.session.stop();
  f.events.Stop();
  assert.ok(socket.closed);
});

test('decodes little-endian PCM at 24 kHz, queues and interrupts audio', () => {
  const f = fixture();
  const playback = new PCMPlayback(f.api, 24000);
  playback.open();
  const bytes = Buffer.from([0, 128, 0, 0, 255, 127]);
  playback.play(bytes.toString('base64'));
  playback.play(bytes.toString('base64'));
  assert.equal(f.buffers[0][0], -1);
  assert.equal(f.buffers[0][1], 0);
  assert.equal(f.buffers[0][2], 32767 / 32768);
  assert.ok(f.sources[1].time >= f.sources[0].time + 3 / 24000);
  playback.stop();
  assert.ok(f.sources.every(source => source.stopped));
  assert.equal(playback.sources.size, 0);
  playback.close();
});

test('cancel during authorization never opens socket or microphone', async () => {
  const f = fixture();
  let authorize;
  f.api.authorize = options => { authorize = options; };
  const starting = f.session.start();
  f.session.stop();
  authorize.success();
  await starting;
  assert.equal(f.sockets.length, 0);
  assert.equal(f.recorder.options, undefined);
});

test('old socket callbacks cannot affect a new conversation', async () => {
  const f = fixture();
  await f.session.start();
  const old = f.sockets[0];
  f.session.stop();
  await f.session.start();
  old.Message({ data: JSON.stringify({ type: 'session_ready' }) });
  old.Close();
  assert.equal(f.recorder.options, undefined);
  assert.ok(f.session.active);
  f.session.stop();
});

test('recording failure closes socket and leaves a useful error', async () => {
  const f = fixture();
  await f.session.start();
  f.sockets[0].Message({ data: JSON.stringify({ type: 'session_ready' }) });
  f.events.Error({ errMsg: 'PCM not supported' });
  assert.equal(f.state.status, 'error');
  assert.equal(f.state.connection, 'PCM not supported');
  assert.ok(f.sockets[0].closed);
  assert.ok(f.context.closed);
  assert.equal(f.session.active, false);
});

test('stop during recorder startup stops a late start and ignores final frames', async () => {
  const f = fixture();
  await f.session.start();
  const socket = f.sockets[0];
  socket.Message({ data: JSON.stringify({ type: 'session_ready' }) });
  f.session.stop();
  f.events.Start();
  f.events.FrameRecorded({ frameBuffer: new ArrayBuffer(4) });
  f.events.Stop();
  assert.equal(f.recorder.stops, 2);
  assert.equal(socket.sent.length, 1);
  assert.equal(f.state.ready, false);
  assert.equal(f.session.recording, false);
});

test('backend speech detection cancels scheduled playback', async () => {
  const f = fixture();
  await f.session.start();
  f.sockets[0].Message({ data: JSON.stringify({ type: 'assistant_audio', audio: 'AAA=' }) });
  assert.equal(f.sources.length, 1);
  f.sockets[0].Message({ data: JSON.stringify({ type: 'speech_started' }) });
  assert.ok(f.sources[0].stopped);
  f.session.stop();
});

test('invalid playback clock reports a useful error', () => {
  const f = fixture();
  const playback = new PCMPlayback(f.api, 24000);
  playback.open();
  f.context.currentTime = NaN;
  assert.throws(() => playback.play('AAA='), /时钟无效/);
  playback.close();
});

test('microphone stays active and sends unchanged PCM during assistant playback', async () => {
  const f = fixture();
  await f.session.start();
  const socket = f.sockets[0];
  socket.Open();
  socket.Message({ data: JSON.stringify({ type: 'session_ready' }) });
  f.events.Start();
  socket.Message({ data: JSON.stringify({ type: 'assistant_audio', audio: 'AAA=' }) });
  assert.equal(socket.sent.length, 1);
  const microphone = new Int16Array([100, -100]).buffer;
  f.events.FrameRecorded({ frameBuffer: microphone });
  assert.strictEqual(socket.sent[1], microphone);
  assert.equal(f.session.recording, true);
  socket.Message({ data: JSON.stringify({ type: 'speech_started' }) });
  assert.ok(f.sources[0].stopped);
  assert.equal(socket.sent.length, 2);
  f.session.stop();
});
