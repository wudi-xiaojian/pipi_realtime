"use strict";


// ================================================================
// Configuration
// ================================================================

const INPUT_SAMPLE_RATE = 16000;
const OUTPUT_SAMPLE_RATE = 24000;

// Qwen input chunk.
// 40ms is a good balance between latency and overhead.
const AUDIO_CHUNK_MS = 40;

const INPUT_SAMPLES_PER_CHUNK =
    INPUT_SAMPLE_RATE *
    AUDIO_CHUNK_MS /
    1000;

// Smaller ScriptProcessor block.
// 4096 caused large input latency.
const PROCESSOR_BUFFER_SIZE = 1024;


// ================================================================
// DOM
// ================================================================

const startButton =
    document.getElementById("start-button");

const stopButton =
    document.getElementById("stop-button");

const statusDot =
    document.getElementById("status-dot");

const statusText =
    document.getElementById("status-text");

const conversation =
    document.getElementById("conversation");

const connectionInfo =
    document.getElementById("connection-info");


// ================================================================
// Runtime
// ================================================================

let websocket = null;

let audioContext = null;

let microphoneStream = null;

let microphoneSource = null;

let processor = null;

let isRunning = false;

let inputBuffer = new Float32Array(0);


// ================================================================
// Playback
// ================================================================

let playbackContext = null;

let playbackQueueTime = 0;

let scheduledSources = [];


// ================================================================
// Conversation
// ================================================================

let currentUserMessage = null;

let currentAssistantMessage = null;


// ================================================================
// UI
// ================================================================

function setStatus(
    state,
    text
) {

    statusText.textContent = text;

    statusDot.className =
        "status-dot " + state;
}


function setConnectionInfo(
    text
) {

    connectionInfo.textContent = text;
}


function addMessage(
    role,
    text
) {

    removeEmptyState();

    const message =
        document.createElement("div");

    message.className =
        `message ${role}`;

    const label =
        document.createElement("div");

    label.className =
        "message-label";

    label.textContent =
        role === "user"
            ? "小朋友"
            : "皮皮猴";

    const content =
        document.createElement("div");

    content.className =
        "message-content";

    content.textContent =
        text;

    message.appendChild(label);
    message.appendChild(content);

    conversation.appendChild(message);

    conversation.scrollTop =
        conversation.scrollHeight;

    return content;
}


function removeEmptyState() {

    const emptyState =
        conversation.querySelector(
            ".empty-state"
        );

    if (emptyState) {
        emptyState.remove();
    }
}


// ================================================================
// WebSocket
// ================================================================

function getWebSocketUrl() {

    const protocol =
        window.location.protocol === "https:"
            ? "wss:"
            : "ws:";

    return (
        `${protocol}//${window.location.host}/ws`
    );
}


function connectWebSocket() {

    return new Promise(
        (resolve, reject) => {

            const url =
                getWebSocketUrl();

            websocket =
                new WebSocket(url);

            websocket.binaryType =
                "arraybuffer";

            websocket.onopen =
                () => {

                    setConnectionInfo(
                        "浏览器 ↔ Python 已连接"
                    );

                    websocket.send(
                        JSON.stringify({
                            type: "start",
                        })
                    );

                    resolve();
                };


            websocket.onmessage =
                async (event) => {

                    await handleServerMessage(
                        event.data
                    );
                };


            websocket.onerror =
                (error) => {

                    console.error(
                        "WebSocket error:",
                        error
                    );

                    setConnectionInfo(
                        "WebSocket 连接错误"
                    );

                    reject(error);
                };


            websocket.onclose =
                () => {

                    setConnectionInfo(
                        "WebSocket 已断开"
                    );

                    if (isRunning) {

                        stopConversation(
                            false
                        );
                    }
                };
        }
    );
}


// ================================================================
// Server messages
// ================================================================

async function handleServerMessage(
    rawMessage
) {

    let message;

    try {

        message =
            JSON.parse(rawMessage);

    } catch (error) {

        console.error(
            "Invalid server message:",
            rawMessage
        );

        return;
    }


    switch (message.type) {

        // --------------------------------------------------------
        // Session
        // --------------------------------------------------------

        case "session_ready":

            setConnectionInfo(
                "Python ↔ Qwen Realtime 已连接"
            );

            setStatus(
                "listening",
                "可以说话了"
            );

            break;


        // --------------------------------------------------------
        // State
        // --------------------------------------------------------

        case "state":

            handleState(
                message.state
            );

            break;


        // --------------------------------------------------------
        // User started speaking
        // --------------------------------------------------------

        case "speech_started":

            // Critical for barge-in.
            stopPlayback();

            currentAssistantMessage = null;

            setStatus(
                "listening",
                "正在听你说话..."
            );

            break;


        // --------------------------------------------------------
        // User stopped speaking
        // --------------------------------------------------------

        case "speech_stopped":

            setStatus(
                "thinking",
                "皮皮猴想一想..."
            );

            break;


        // --------------------------------------------------------
        // Explicit playback cancel
        // --------------------------------------------------------

        case "playback_cancel":

            stopPlayback();

            break;


        // --------------------------------------------------------
        // User transcript
        // --------------------------------------------------------

        case "user_transcript_delta":

            appendUserTranscript(
                message.text || ""
            );

            break;


        case "user_transcript":

            finishUserTranscript(
                message.text || ""
            );

            break;


        // --------------------------------------------------------
        // Assistant audio
        // --------------------------------------------------------

        case "assistant_audio":

            if (message.audio) {

                playPCM24(
                    base64ToArrayBuffer(
                        message.audio
                    )
                );
            }

            break;


        // --------------------------------------------------------
        // Assistant transcript
        // --------------------------------------------------------

        case "assistant_transcript_delta":

            appendAssistantTranscript(
                message.text || ""
            );

            break;


        case "assistant_transcript":

            finishAssistantTranscript(
                message.text || ""
            );

            break;


        // --------------------------------------------------------
        // Response done
        // --------------------------------------------------------

        case "response_done":

            if (
                message.status ===
                "cancelled"
            ) {

                stopPlayback();
            }

            setStatus(
                "listening",
                "可以继续说话"
            );

            break;


        // --------------------------------------------------------
        // Error
        // --------------------------------------------------------

        case "error":

            console.error(
                "Server error:",
                message.message
            );

            setStatus(
                "error",
                "连接出现问题"
            );

            setConnectionInfo(
                message.message
            );

            break;


        // --------------------------------------------------------
        // Debug
        // --------------------------------------------------------

        case "debug_event":

            console.debug(
                "[Qwen]",
                message.event
            );

            break;


        default:

            console.debug(
                "Unknown server message:",
                message
            );
    }
}


// ================================================================
// State
// ================================================================

function handleState(
    state
) {

    switch (state) {

        case "idle":

            setStatus(
                "listening",
                "可以继续说话"
            );

            break;


        case "listening":

            setStatus(
                "listening",
                "正在听你说话..."
            );

            break;


        case "speaking":

            setStatus(
                "speaking",
                "皮皮猴正在说话..."
            );

            break;


        case "thinking":

            setStatus(
                "thinking",
                "皮皮猴想一想..."
            );

            break;
    }
}


// ================================================================
// User transcript
// ================================================================

function appendUserTranscript(
    text
) {

    removeEmptyState();

    if (!currentUserMessage) {

        currentUserMessage =
            addMessage(
                "user",
                ""
            );
    }

    currentUserMessage.textContent +=
        text;

    conversation.scrollTop =
        conversation.scrollHeight;
}


function finishUserTranscript(
    text
) {

    if (!currentUserMessage) {

        currentUserMessage =
            addMessage(
                "user",
                text
            );

    } else if (text) {

        currentUserMessage.textContent =
            text;
    }

    currentUserMessage = null;
}


// ================================================================
// Assistant transcript
// ================================================================

function appendAssistantTranscript(
    text
) {

    removeEmptyState();

    if (!currentAssistantMessage) {

        currentAssistantMessage =
            addMessage(
                "assistant",
                ""
            );
    }

    currentAssistantMessage.textContent +=
        text;

    conversation.scrollTop =
        conversation.scrollHeight;
}


function finishAssistantTranscript(
    text
) {

    if (!currentAssistantMessage) {

        currentAssistantMessage =
            addMessage(
                "assistant",
                text
            );

    } else if (text) {

        currentAssistantMessage.textContent =
            text;
    }

    currentAssistantMessage = null;
}


// ================================================================
// Microphone
// ================================================================

async function startMicrophone() {

    microphoneStream =
        await navigator.mediaDevices
            .getUserMedia(
                {
                    audio: {
                        channelCount: 1,
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true,
                    },
                }
            );


    audioContext =
        new AudioContext();


    await audioContext.resume();


    microphoneSource =
        audioContext.createMediaStreamSource(
            microphoneStream
        );


    processor =
        audioContext.createScriptProcessor(
            PROCESSOR_BUFFER_SIZE,
            1,
            1
        );


    inputBuffer =
        new Float32Array(0);


    processor.onaudioprocess =
        (event) => {

            if (!isRunning) {
                return;
            }

            const input =
                event.inputBuffer
                    .getChannelData(0);


            const copied =
                new Float32Array(
                    input.length
                );

            copied.set(input);


            inputBuffer =
                concatFloat32(
                    inputBuffer,
                    copied
                );


            while (
                inputBuffer.length >=
                INPUT_SAMPLES_PER_CHUNK
            ) {

                const chunk =
                    inputBuffer.slice(
                        0,
                        INPUT_SAMPLES_PER_CHUNK
                    );


                inputBuffer =
                    inputBuffer.slice(
                        INPUT_SAMPLES_PER_CHUNK
                    );


                const pcm16 =
                    downsampleAndConvertToPCM16(
                        chunk,
                        audioContext.sampleRate,
                        INPUT_SAMPLE_RATE
                    );


                sendAudio(
                    pcm16
                );
            }
        };


    microphoneSource.connect(
        processor
    );

    /*
     * ScriptProcessorNode needs to be connected
     * to keep processing alive.
     *
     * Use a zero-gain node so microphone audio
     * is not played back to the user.
     */

    const silentGain =
        audioContext.createGain();

    silentGain.gain.value = 0;

    processor.connect(
        silentGain
    );

    silentGain.connect(
        audioContext.destination
    );
}


// ================================================================
// Audio conversion
// ================================================================

function concatFloat32(
    a,
    b
) {

    const result =
        new Float32Array(
            a.length + b.length
        );

    result.set(a, 0);
    result.set(b, a.length);

    return result;
}


function downsampleAndConvertToPCM16(
    input,
    inputRate,
    outputRate
) {

    if (inputRate === outputRate) {

        return floatToPCM16(
            input
        );
    }


    const ratio =
        inputRate / outputRate;


    const outputLength =
        Math.floor(
            input.length / ratio
        );


    const output =
        new Int16Array(
            outputLength
        );


    let inputIndex = 0;


    for (
        let i = 0;
        i < outputLength;
        i++
    ) {

        const nextInputIndex =
            Math.floor(
                (i + 1) * ratio
            );


        let sum = 0;
        let count = 0;


        for (
            let j = inputIndex;
            j < nextInputIndex &&
            j < input.length;
            j++
        ) {

            sum += input[j];
            count++;
        }


        const sample =
            count > 0
                ? sum / count
                : 0;


        const clamped =
            Math.max(
                -1,
                Math.min(
                    1,
                    sample
                )
            );


        output[i] =
            clamped < 0
                ? clamped * 32768
                : clamped * 32767;


        inputIndex =
            nextInputIndex;
    }


    return output;
}


function floatToPCM16(
    input
) {

    const output =
        new Int16Array(
            input.length
        );


    for (
        let i = 0;
        i < input.length;
        i++
    ) {

        const sample =
            Math.max(
                -1,
                Math.min(
                    1,
                    input[i]
                )
            );


        output[i] =
            sample < 0
                ? sample * 32768
                : sample * 32767;
    }


    return output;
}


// ================================================================
// Send microphone audio
// ================================================================

function sendAudio(
    pcm16
) {

    if (
        !websocket ||
        websocket.readyState !==
        WebSocket.OPEN
    ) {

        return;
    }


    /*
     * Avoid building a huge browser-side
     * WebSocket send queue.
     */

    if (
        websocket.bufferedAmount >
        512 * 1024
    ) {

        return;
    }


    websocket.send(
        pcm16.buffer
    );
}


// ================================================================
// Playback initialization
// ================================================================

async function ensurePlaybackContext() {

    if (!playbackContext) {

        playbackContext =
            new AudioContext();
    }


    if (
        playbackContext.state ===
        "suspended"
    ) {

        await playbackContext.resume();
    }
}


// ================================================================
// PCM playback
// ================================================================

function playPCM24(
    arrayBuffer
) {

    if (!playbackContext) {
        return;
    }


    if (
        playbackContext.state ===
        "suspended"
    ) {
        return;
    }


    const int16 =
        new Int16Array(
            arrayBuffer
        );


    if (!int16.length) {
        return;
    }


    const float32 =
        new Float32Array(
            int16.length
        );


    for (
        let i = 0;
        i < int16.length;
        i++
    ) {

        float32[i] =
            int16[i] / 32768;
    }


    const audioBuffer =
        playbackContext.createBuffer(
            1,
            float32.length,
            OUTPUT_SAMPLE_RATE
        );


    audioBuffer
        .getChannelData(0)
        .set(float32);


    const source =
        playbackContext.createBufferSource();


    source.buffer =
        audioBuffer;


    source.connect(
        playbackContext.destination
    );


    const now =
        playbackContext.currentTime;


    if (
        playbackQueueTime <
        now
    ) {

        playbackQueueTime =
            now;
    }


    /*
     * Start almost immediately.
     *
     * Do not add a large artificial buffer.
     */

    const startTime =
        Math.max(
            now + 0.005,
            playbackQueueTime
        );


    playbackQueueTime =
        startTime +
        audioBuffer.duration;


    scheduledSources.push(
        source
    );


    source.onended =
        () => {

            const index =
                scheduledSources.indexOf(
                    source
                );

            if (index !== -1) {

                scheduledSources.splice(
                    index,
                    1
                );
            }
        };


    source.start(
        startTime
    );
}


// ================================================================
// Stop playback immediately
// ================================================================

function stopPlayback() {

    for (
        const source
        of scheduledSources
    ) {

        try {

            source.stop();

        } catch (error) {

            // Already stopped.
        }
    }


    scheduledSources = [];


    if (playbackContext) {

        playbackQueueTime =
            playbackContext.currentTime;
    }
}


// ================================================================
// Base64
// ================================================================

function base64ToArrayBuffer(
    base64
) {

    const binary =
        atob(base64);


    const bytes =
        new Uint8Array(
            binary.length
        );


    for (
        let i = 0;
        i < binary.length;
        i++
    ) {

        bytes[i] =
            binary.charCodeAt(i);
    }


    return bytes.buffer;
}


// ================================================================
// Start
// ================================================================

async function startConversation() {

    if (isRunning) {
        return;
    }


    try {

        setStatus(
            "thinking",
            "正在连接..."
        );


        setConnectionInfo(
            "正在连接 Python..."
        );


        /*
         * Initialize playback context while
         * we still have a user gesture.
         */

        playbackContext =
            new AudioContext();


        await playbackContext.resume();


        playbackQueueTime = 0;


        await connectWebSocket();


        await startMicrophone();


        isRunning = true;


        startButton.classList.add(
            "hidden"
        );


        stopButton.classList.remove(
            "hidden"
        );


        setStatus(
            "listening",
            "可以说话了"
        );

    } catch (error) {

        console.error(
            "Start failed:",
            error
        );


        setStatus(
            "error",
            "启动失败"
        );


        setConnectionInfo(
            error.message ||
            "无法启动实时语音"
        );


        cleanup();
    }
}


// ================================================================
// Stop
// ================================================================

function stopConversation(
    closeWebSocket = true
) {

    isRunning = false;


    if (websocket) {

        try {

            websocket.send(
                JSON.stringify({
                    type: "stop",
                })
            );

        } catch (error) {

            // Ignore.
        }
    }


    cleanup();


    if (
        closeWebSocket &&
        websocket
    ) {

        try {

            websocket.close();

        } catch (error) {

            // Ignore.
        }


        websocket = null;
    }


    startButton.classList.remove(
        "hidden"
    );


    stopButton.classList.add(
        "hidden"
    );


    setStatus(
        "idle",
        "等待开始"
    );


    setConnectionInfo(
        "已停止"
    );
}


// ================================================================
// Cleanup
// ================================================================

function cleanup() {

    stopPlayback();


    if (processor) {

        try {
            processor.disconnect();
        } catch (error) {
            // Ignore.
        }


        processor.onaudioprocess =
            null;


        processor = null;
    }


    if (microphoneSource) {

        try {
            microphoneSource.disconnect();
        } catch (error) {
            // Ignore.
        }


        microphoneSource = null;
    }


    if (microphoneStream) {

        for (
            const track
            of microphoneStream.getTracks()
        ) {

            track.stop();
        }


        microphoneStream = null;
    }


    if (audioContext) {

        try {
            audioContext.close();
        } catch (error) {
            // Ignore.
        }


        audioContext = null;
    }


    inputBuffer =
        new Float32Array(0);
}


// ================================================================
// Buttons
// ================================================================

startButton.addEventListener(
    "click",
    () => {

        startConversation();
    }
);


stopButton.addEventListener(
    "click",
    () => {

        stopConversation(true);
    }
);


// ================================================================
// Initial
// ================================================================

setStatus(
    "idle",
    "等待开始"
);


setConnectionInfo(
    "尚未连接"
);