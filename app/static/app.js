const WS_URL = "wss://agents.assemblyai.com/v1/ws";
const SAMPLE_RATE = 24000;

const $ = (selector) => document.querySelector(selector);
const transcript = $("#transcript");
const voiceButton = $("#voiceButton");
const connectionStatus = $("#connectionStatus");
const heroState = $("#heroState");
const voiceCta = $("#voiceCta");
const voiceHint = $("#voiceHint");
const demoPrompt = $("#demoPrompt");

let mode = "capture";
let ws = null;
let connected = false;
let sessionReady = false;
let sessionId = null;
let audioContext = null;
let mediaStream = null;
let mediaSource = null;
let worklet = null;
let silentGain = null;
let playbackCursor = 0;
let scheduledSources = new Set();
let pendingToolResults = [];
let lastEventType = null;
let partialBubble = null;

function setStatus(label, state = "offline") {
  connectionStatus.className = `status-pill ${state}`;
  connectionStatus.innerHTML = `<span class="status-dot"></span>${label}`;
}

function setUiConnected(value) {
  connected = value;
  voiceButton.classList.toggle("active", value);
  voiceCta.textContent = value ? "End voice session" : (
    mode === "capture" ? "Start expert interview" : "Ask captured expertise"
  );
  voiceHint.textContent = value
    ? "Speak naturally. Interruptions and turn-taking are live."
    : "Your API key stays on the server.";
  heroState.textContent = value
    ? (mode === "capture" ? "Compiling expertise in real time" : "Searching verified expert memory")
    : "Waiting for a voice session";
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function clearEmptyState() {
  const empty = transcript.querySelector(".empty-state");
  if (empty) empty.remove();
}

function addBubble(role, text, meta = "") {
  clearEmptyState();
  const row = document.createElement("div");
  row.className = `message ${role}`;
  row.innerHTML = `
    <div class="message-label">${role === "user" ? "EXPERT / USER" : role === "agent" ? "TACITOS" : "SYSTEM"}</div>
    <div class="message-body">${escapeHtml(text)}</div>
    ${meta ? `<div class="message-meta">${escapeHtml(meta)}</div>` : ""}
  `;
  transcript.appendChild(row);
  transcript.scrollTop = transcript.scrollHeight;
  return row;
}

function setPartial(text) {
  clearEmptyState();
  if (!partialBubble) {
    partialBubble = addBubble("user partial", text, "listening…");
  } else {
    partialBubble.querySelector(".message-body").textContent = text;
  }
}

function finalizePartial(text) {
  if (partialBubble) {
    partialBubble.remove();
    partialBubble = null;
  }
  if (text?.trim()) addBubble("user", text);
}

function toolBubble(name, result) {
  const summary = result?.status || (result?.rule?.id ? "captured" : "completed");
  addBubble("system", `${name.replaceAll("_", " ")} → ${summary}`, "tool call");
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const step = 0x8000;
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step));
  }
  return btoa(binary);
}

function base64ToInt16(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

async function ensureAudioContext() {
  if (!audioContext || audioContext.state === "closed") {
    audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    await audioContext.audioWorklet.addModule("/static/pcm-processor.js");
  }
  if (audioContext.state === "suspended") await audioContext.resume();
  return audioContext;
}

async function startMicrophone() {
  const ctx = await ensureAudioContext();
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  mediaSource = ctx.createMediaStreamSource(mediaStream);
  worklet = new AudioWorkletNode(ctx, "tacitos-pcm");
  silentGain = ctx.createGain();
  silentGain.gain.value = 0;

  worklet.port.onmessage = (event) => {
    if (!sessionReady || !ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: "input.audio",
      audio: arrayBufferToBase64(event.data),
    }));
  };

  mediaSource.connect(worklet);
  worklet.connect(silentGain);
  silentGain.connect(ctx.destination);
}

function stopMicrophone() {
  mediaStream?.getTracks().forEach((track) => track.stop());
  mediaStream = null;
  try { mediaSource?.disconnect(); } catch {}
  try { worklet?.disconnect(); } catch {}
  try { silentGain?.disconnect(); } catch {}
  mediaSource = null;
  worklet = null;
  silentGain = null;
}

function playAudio(base64) {
  if (!audioContext) return;
  const pcm = base64ToInt16(base64);
  const buffer = audioContext.createBuffer(1, pcm.length, SAMPLE_RATE);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < pcm.length; i += 1) data[i] = pcm[i] / 32768;

  const source = audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(audioContext.destination);
  playbackCursor = Math.max(playbackCursor, audioContext.currentTime + 0.02);
  source.start(playbackCursor);
  playbackCursor += buffer.duration;
  scheduledSources.add(source);
  source.onended = () => scheduledSources.delete(source);
}

function flushPlayback() {
  for (const source of scheduledSources) {
    try { source.stop(); } catch {}
  }
  scheduledSources.clear();
  if (audioContext) playbackCursor = audioContext.currentTime;
}

async function runTool(event) {
  try {
    const response = await fetch("/api/tool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: event.name,
        arguments: event.arguments || {},
        session_id: sessionId,
      }),
    });
    const payload = await response.json();
    const result = payload.ok ? payload.result : { status: "error", error: payload.error };
    pendingToolResults.push({ callId: event.call_id, result });
    toolBubble(event.name, result);
    await refreshDashboard();
    flushToolResultsIfIdle();
  } catch (error) {
    pendingToolResults.push({
      callId: event.call_id,
      result: { status: "error", error: String(error) },
    });
    flushToolResultsIfIdle();
  }
}

function flushToolResultsIfIdle() {
  if (lastEventType !== "reply.done" || !ws || ws.readyState !== WebSocket.OPEN) return;
  for (const pending of pendingToolResults) {
    ws.send(JSON.stringify({
      type: "tool.result",
      call_id: pending.callId,
      result: JSON.stringify(pending.result),
    }));
  }
  pendingToolResults = [];
}

async function connectVoice() {
  setStatus("Connecting", "connecting");
  heroState.textContent = "Opening AssemblyAI voice session";

  const [tokenResponse, configResponse] = await Promise.all([
    fetch("/api/voice-token"),
    fetch(`/api/voice-config?mode=${mode}`),
  ]);

  if (!tokenResponse.ok) {
    const error = await tokenResponse.json().catch(() => ({}));
    throw new Error(error.detail || "Could not mint AssemblyAI voice token.");
  }

  const { token } = await tokenResponse.json();
  const config = await configResponse.json();
  await ensureAudioContext();

  ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);

  ws.onopen = () => {
    ws.send(JSON.stringify(config));
  };

  ws.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    const type = event.type;
    lastEventType = type;

    if (type === "session.ready") {
      sessionId = event.session_id;
      sessionReady = true;
      setUiConnected(true);
      setStatus("Live", "online");
      demoPrompt.classList.add("dimmed");
      await startMicrophone();
      return;
    }

    if (type === "transcript.user.delta") {
      setPartial(event.text || "");
      return;
    }

    if (type === "transcript.user") {
      finalizePartial(event.text || "");
      return;
    }

    if (type === "transcript.agent") {
      addBubble("agent", event.text || "", event.interrupted ? "interrupted" : "");
      return;
    }

    if (type === "reply.audio") {
      playAudio(event.data || "");
      return;
    }

    if (type === "tool.call") {
      await runTool(event);
      return;
    }

    if (type === "reply.done") {
      if (event.status === "interrupted") {
        flushPlayback();
        pendingToolResults = [];
      } else {
        flushToolResultsIfIdle();
      }
      return;
    }

    if (type === "session.error") {
      addBubble("system", event.message || "AssemblyAI session error");
      setStatus("Error", "error");
    }
  };

  ws.onerror = () => {
    setStatus("Connection error", "error");
  };

  ws.onclose = () => {
    sessionReady = false;
    sessionId = null;
    stopMicrophone();
    flushPlayback();
    setUiConnected(false);
    setStatus("Offline", "offline");
    demoPrompt.classList.remove("dimmed");
  };
}

function disconnectVoice() {
  stopMicrophone();
  flushPlayback();
  sessionReady = false;
  if (ws && ws.readyState <= WebSocket.OPEN) ws.close();
  ws = null;
  setUiConnected(false);
  setStatus("Offline", "offline");
}

voiceButton.addEventListener("click", async () => {
  if (connected || (ws && ws.readyState === WebSocket.CONNECTING)) {
    disconnectVoice();
    return;
  }
  try {
    await connectVoice();
  } catch (error) {
    addBubble("system", error.message || String(error));
    setStatus("Setup needed", "error");
    heroState.textContent = "Check ASSEMBLYAI_API_KEY";
  }
});

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", async () => {
    mode = button.dataset.mode;
    document.querySelectorAll(".mode").forEach((item) => item.classList.toggle("active", item === button));

    voiceCta.textContent = connected
      ? "End voice session"
      : (mode === "capture" ? "Start expert interview" : "Ask captured expertise");

    demoPrompt.querySelector("p").textContent = mode === "capture"
      ? "“Normally I restart Pump B after an overload, but not if vibration was high and suction pressure was falling.”"
      : "“Pump B stopped after an overload. Vibration was high and suction pressure was falling. Should I restart it?”";

    if (ws && ws.readyState === WebSocket.OPEN && sessionReady) {
      const config = await fetch(`/api/voice-config?mode=${mode}`).then((r) => r.json());
      ws.send(JSON.stringify(config));
      addBubble("system", `Switched to ${mode === "capture" ? "Expert Capture" : "Apprentice Guidance"} mode`);
    }
  });
});

$("#refreshButton").addEventListener("click", refreshDashboard);

function renderRule(rule) {
  const conditions = Object.entries(rule.conditions || {})
    .map(([key, value]) => `<span>${escapeHtml(key.replaceAll("_", " "))}: <b>${escapeHtml(value)}</b></span>`)
    .join("");

  return `
    <article class="rule-card">
      <div class="rule-top">
        <strong>${escapeHtml(rule.id)}</strong>
        <small>${Math.round((rule.confidence || 0) * 100)}%</small>
      </div>
      <p>${escapeHtml(rule.action)}</p>
      <div class="chips">${conditions}</div>
      <footer>
        <span>${escapeHtml(rule.expert || "Unknown expert")}</span>
        <span>${escapeHtml(rule.topic)}</span>
      </footer>
    </article>
  `;
}

function renderConflict(conflict) {
  return `
    <article class="conflict-card ${conflict.status}">
      <div>
        <strong>${escapeHtml(conflict.id)}</strong>
        <span>${escapeHtml(conflict.status)}</span>
      </div>
      <p>${escapeHtml(conflict.reason)}</p>
      <small>${escapeHtml(conflict.topic)}</small>
    </article>
  `;
}

async function refreshDashboard() {
  try {
    const data = await fetch("/api/dashboard").then((response) => response.json());
    const stats = data.stats || {};
    $("#rulesMetric").textContent = stats.rules ?? 0;
    $("#expertsMetric").textContent = stats.experts ?? 0;
    $("#conflictsMetric").textContent = stats.open_conflicts ?? 0;
    $("#topicsMetric").textContent = stats.topics ?? 0;
    $("#ruleCountLabel").textContent = `${stats.rules ?? 0} total`;

    const primary = data.topics?.[0];
    const coverage = primary?.coverage_percent ?? 0;
    $("#coverageMetric").textContent = `${coverage}%`;
    $("#coverageBar").style.width = `${coverage}%`;
    $("#coverageNote").textContent = primary?.next_question || "Capture the first rule to start mapping expertise.";

    $("#ruleFeed").innerHTML = data.rules?.length
      ? data.rules.slice(0, 8).map(renderRule).join("")
      : '<p class="muted">No rules captured yet.</p>';

    const openConflicts = (data.conflicts || []).filter((item) => item.status === "open");
    $("#conflictFeed").innerHTML = openConflicts.length
      ? openConflicts.slice(0, 5).map(renderConflict).join("")
      : '<p class="muted">No open contradictions.</p>';
  } catch (error) {
    console.warn("Dashboard refresh failed", error);
  }
}

refreshDashboard();
setUiConnected(false);
