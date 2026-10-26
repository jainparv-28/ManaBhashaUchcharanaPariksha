/* app.js -- dropdown of internally stored guru audios, live learner
   recording (Record / Play / Stop), then /api/evaluate and the same
   waveform + error-band rendering as before. */

const ERROR_COLORS = {
  aspiration_error: "#e63946",
  anunasika_error: "#f4a261",
  dvitva_error: "#9c6ade",
  conjunct_error: "#457b9d",
  substitution: "#6c757d",
  missing: "#111318",
  extra: "#2a9d8f",
};
const ERROR_LABELS = {
  aspiration_error: "Aspiration (alpaprana/mahaprana)",
  anunasika_error: "Anunasika (nasalisation)",
  dvitva_error: "Dvitva / gemination",
  conjunct_error: "Sanyukta / conjunct",
  substitution: "Substitution",
  missing: "Missing (guru akshara not said)",
  extra: "Extra (learner added something)",
};
const MAX_RECORD_SECONDS = 180;

const form = document.getElementById("eval-form");
const statusEl = document.getElementById("status");
const resultsPanel = document.getElementById("results-panel");
const submitBtn = document.getElementById("submit-btn");
const itemSelect = document.getElementById("item_select");
const itemDetail = document.getElementById("item-detail");
const guruSelectAudio = document.getElementById("guru-select-audio");
const refTextEl = document.getElementById("ref-text");
const recBtn = document.getElementById("rec-btn");
const playBtn = document.getElementById("play-btn");
const stopBtn = document.getElementById("stop-btn");
const recTimerEl = document.getElementById("rec-timer");
const recAudio = document.getElementById("rec-audio");

let items = {};
let mediaRecorder = null;
let recStream = null;
let recChunks = [];
let recordedBlob = null;
let recording = false;
let busy = false;
let timerId = null;
let recStartedAt = 0;

/* ---------------- helpers ---------------- */
function showStatus(kind, msg) {
  statusEl.hidden = false;
  statusEl.className = "status" + (kind === "error" ? " error" : "");
  statusEl.textContent = msg;
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

function extFor(type) {
  type = (type || "").toLowerCase();
  if (type.includes("webm")) return ".webm";
  if (type.includes("ogg")) return ".ogg";
  if (type.includes("mp4") || type.includes("aac")) return ".m4a";
  if (type.includes("wav")) return ".wav";
  return ".webm";
}

function pickMimeType() {
  if (!window.MediaRecorder) return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function updateButtons() {
  const hasItem = !!itemSelect.value;
  const playing = !recAudio.paused && !recAudio.ended && !!recordedBlob;
  recBtn.disabled = !hasItem || recording || busy;
  recBtn.textContent = recordedBlob ? "● Re-record" : "● Record";
  playBtn.disabled = !recordedBlob || recording || playing || busy;
  stopBtn.disabled = !(recording || playing);
  submitBtn.disabled = !hasItem || !recordedBlob || recording || busy;
  recBtn.classList.toggle("active", recording);
}

/* ---------------- items dropdown ---------------- */
async function loadItems() {
  try {
    const res = await fetch("/api/items");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load items");
    for (const it of data.items) {
      items[it.id] = it;
      const opt = document.createElement("option");
      opt.value = it.id;
      opt.textContent = it.label;
      itemSelect.appendChild(opt);
    }
  } catch (err) {
    showStatus("error", "Error loading guru items: " + err.message);
  }
}

itemSelect.addEventListener("change", () => {
  guruSelectAudio.pause();
  clearRecording();
  resultsPanel.hidden = true;
  statusEl.hidden = true;

  const it = items[itemSelect.value];
  if (!it) {
    itemDetail.hidden = true;
    guruSelectAudio.removeAttribute("src");
    guruSelectAudio.load();
    updateButtons();
    return;
  }
  itemDetail.hidden = false;
  refTextEl.textContent = it.text;
  refTextEl.lang = it.lang === "te" ? "te" : "sa";
  if (it.audio_url) {
    guruSelectAudio.hidden = false;
    guruSelectAudio.src = it.audio_url;
    guruSelectAudio.load();
  } else {
    guruSelectAudio.hidden = true;
    guruSelectAudio.removeAttribute("src");
  }
  updateButtons();
});

/* ---------------- recording ---------------- */
function releaseStream() {
  if (recStream) { recStream.getTracks().forEach((t) => t.stop()); recStream = null; }
}
function startTimer() {
  recStartedAt = Date.now();
  recTimerEl.textContent = "00:00";
  timerId = setInterval(() => {
    const sec = (Date.now() - recStartedAt) / 1000;
    recTimerEl.textContent = fmtTime(sec);
    if (sec >= MAX_RECORD_SECONDS) stopAny();
  }, 250);
}
function stopTimer() { if (timerId) { clearInterval(timerId); timerId = null; } }

function clearRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.onstop = null;
    try { mediaRecorder.stop(); } catch (e) {}
  }
  releaseStream();
  stopTimer();
  recording = false;
  recChunks = [];
  recordedBlob = null;
  recAudio.pause();
  recAudio.removeAttribute("src");
  recAudio.load();
  recTimerEl.textContent = "00:00";
  updateButtons();
}

async function startRecording() {
  if (!itemSelect.value) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showStatus("error", "Live recording isn't supported in this browser (it also needs HTTPS or localhost).");
    return;
  }
  guruSelectAudio.pause();
  clearRecording();
  statusEl.hidden = true;
  try {
    recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    showStatus("error", "Microphone unavailable or permission denied: " + err.message);
    return;
  }
  const mime = pickMimeType();
  recChunks = [];
  mediaRecorder = mime ? new MediaRecorder(recStream, { mimeType: mime }) : new MediaRecorder(recStream);
  mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) recChunks.push(e.data); };
  mediaRecorder.onstop = () => {
    const type = mediaRecorder.mimeType || mime || "audio/webm";
    recordedBlob = new Blob(recChunks, { type });
    recAudio.src = URL.createObjectURL(recordedBlob);
    releaseStream();
    stopTimer();
    recording = false;
    updateButtons();
  };
  mediaRecorder.start();
  recording = true;
  startTimer();
  updateButtons();
}

function stopAny() {
  if (recording && mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();            // onstop finalises the blob
  } else {
    recAudio.pause();
    recAudio.currentTime = 0;
    updateButtons();
  }
}

recBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopAny);
playBtn.addEventListener("click", () => { if (recordedBlob) recAudio.play(); });
["play", "pause", "ended"].forEach((ev) => recAudio.addEventListener(ev, updateButtons));

/* ---------------- evaluate ---------------- */
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!itemSelect.value || !recordedBlob) return;

  busy = true;
  updateButtons();
  resultsPanel.hidden = true;
  showStatus("info", "Transcribing and scoring the learner's recording -- this can take a little while...");

  try {
    const fd = new FormData();
    fd.append("item_id", itemSelect.value);
    fd.append("learner_audio", recordedBlob, "learner" + extFor(recordedBlob.type));
    const res = await fetch("/api/evaluate", { method: "POST", body: fd });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("Server error (" + res.status + ")"));

    statusEl.hidden = true;
    await renderResults(data);
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showStatus("error", "Error: " + err.message);
  } finally {
    busy = false;
    updateButtons();
  }
});

/* ---------------- results rendering ---------------- */
async function renderResults(data) {
  resultsPanel.hidden = false;

  const flagsEl = document.getElementById("flags");
  flagsEl.innerHTML = "";
  if (data.asr_flagged) {
    flagsEl.innerHTML += `<div class="flag warn">🚩 ${escapeHtml(data.asr_flag_reason || "ASR quality flag")} -- treat this score as unverified and spot-check the audio manually.</div>`;
  }
  if (data.used_transliteration_fallback) {
    flagsEl.innerHTML += `<div class="flag warn">⚠️ ASR output was romanized and auto-transliterated back to native script -- treat this report as lower-confidence.</div>`;
  }
  if (!data.timing_available) {
    flagsEl.innerHTML += `<div class="flag warn">ℹ️ Word-level timing wasn't available from the ASR backend -- errors are listed below without timestamps.</div>`;
  }

  document.getElementById("score-overall").textContent = data.overall_score;
  document.getElementById("grade-label").textContent = data.grade;
  document.getElementById("score-r1").textContent = data.rubric1.score;
  document.getElementById("score-r2").textContent = data.rubric2.score;
  document.getElementById("score-r3").textContent = data.rubric3.score;

  const legendEl = document.getElementById("legend");
  const typesPresent = new Set(data.timed_errors.map((e) => e.type));
  legendEl.innerHTML = [...typesPresent].map(
    (t) => `<span class="swatch"><i style="background:${ERROR_COLORS[t] || "#888"}"></i>${ERROR_LABELS[t] || t}</span>`
  ).join("");

  const learnerAudioEl = document.getElementById("learner-audio-el");
  learnerAudioEl.src = data.learner_audio_url;
  const learnerCanvas = document.getElementById("learner-canvas");
  await drawWaveformWithErrors(learnerCanvas, data.learner_audio_url, data.timed_errors, learnerAudioEl, data.duration);

  const guruSection = document.getElementById("guru-audio-section");
  if (data.guru_audio_url) {
    guruSection.hidden = false;
    const guruAudioEl = document.getElementById("guru-audio-el");
    guruAudioEl.src = data.guru_audio_url;
    const guruCanvas = document.getElementById("guru-canvas");
    await drawWaveformWithErrors(guruCanvas, data.guru_audio_url, [], guruAudioEl, null);
  } else {
    guruSection.hidden = true;
  }

  const tbody = document.querySelector("#error-table tbody");
  tbody.innerHTML = "";
  const sorted = [...data.timed_errors].sort((a, b) => (a.start ?? 1e9) - (b.start ?? 1e9));
  for (const err of sorted) {
    const tr = document.createElement("tr");
    const timeLabel = err.start != null
      ? `${err.start.toFixed(2)}s${err.approximate ? " ~" : ""} - ${err.end != null ? err.end.toFixed(2) + "s" : "?"}`
      : "—";
    tr.innerHTML = `
      <td>${timeLabel}</td>
      <td><span class="swatch"><i style="background:${ERROR_COLORS[err.type] || "#888"}"></i>${ERROR_LABELS[err.type] || err.type}</span></td>
      <td>${escapeHtml(err.guru_akshara || "-")}</td>
      <td>${escapeHtml(err.learner_akshara || "-")}</td>
      <td>${escapeHtml(err.note || "")}</td>`;
    if (err.start != null) {
      tr.addEventListener("click", () => {
        learnerAudioEl.currentTime = err.start;
        learnerAudioEl.play();
      });
    }
    tbody.appendChild(tr);
  }
}

/* Waveform + error bands. State is kept per canvas so that re-evaluating
   doesn't stack up event listeners or keep growing the canvas height. */
const waveformState = new WeakMap();

function drawWave(canvas, playheadTime) {
  const s = waveformState.get(canvas);
  if (!s) return;
  const { ctx, cssWidth, cssHeight, channelData, duration, errors } = s;
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  if (duration > 0) {
    for (const err of errors) {
      if (err.start == null || err.end == null) continue;
      const x1 = (err.start / duration) * cssWidth;
      const x2 = Math.max(x1 + 2, (err.end / duration) * cssWidth);
      ctx.fillStyle = (ERROR_COLORS[err.type] || "#888") + "55";
      ctx.fillRect(x1, 0, x2 - x1, cssHeight);
      ctx.strokeStyle = ERROR_COLORS[err.type] || "#888";
      ctx.lineWidth = 1;
      ctx.strokeRect(x1, 0, x2 - x1, cssHeight);
    }
  }

  ctx.strokeStyle = "#8ecae6";
  ctx.lineWidth = 1;
  if (channelData) {
    const mid = cssHeight / 2;
    const samplesPerPx = Math.max(1, Math.floor(channelData.length / cssWidth));
    ctx.beginPath();
    for (let x = 0; x < cssWidth; x++) {
      let min = 1.0, max = -1.0;
      const start = x * samplesPerPx;
      for (let i = 0; i < samplesPerPx; i++) {
        const v = channelData[start + i] || 0;
        if (v < min) min = v;
        if (v > max) max = v;
      }
      ctx.moveTo(x, mid + min * mid * 0.9);
      ctx.lineTo(x, mid + max * mid * 0.9);
    }
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.moveTo(0, cssHeight / 2);
    ctx.lineTo(cssWidth, cssHeight / 2);
    ctx.stroke();
  }

  if (duration > 0 && playheadTime != null) {
    const x = (playheadTime / duration) * cssWidth;
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, cssHeight);
    ctx.stroke();
  }

  ctx.fillStyle = "#9aa0ac";
  ctx.font = "10px sans-serif";
  if (duration > 0) {
    const tickEvery = duration > 20 ? 5 : (duration > 8 ? 2 : 1);
    for (let t = 0; t <= duration; t += tickEvery) {
      const x = (t / duration) * cssWidth;
      ctx.fillText(t.toFixed(0) + "s", Math.min(x + 2, cssWidth - 22), cssHeight - 4);
    }
  }
}

async function drawWaveformWithErrors(canvas, url, errors, audioEl, fallbackDuration) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  if (!canvas.dataset.h) canvas.dataset.h = canvas.getAttribute("height") || "140";
  const cssHeight = parseInt(canvas.dataset.h, 10);
  const cssWidth = canvas.clientWidth || canvas.parentElement.clientWidth || 800;
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  canvas.style.height = cssHeight + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  let channelData = null;
  let duration = fallbackDuration || 0;
  try {
    const resp = await fetch(url);
    const buf = await resp.arrayBuffer();
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    const actx = new AudioCtx();
    const audioBuffer = await actx.decodeAudioData(buf);
    channelData = audioBuffer.getChannelData(0);
    duration = audioBuffer.duration;
    actx.close();
  } catch (e) {
    console.warn("Could not decode audio for waveform, drawing flat placeholder:", e);
  }

  waveformState.set(canvas, { ctx, cssWidth, cssHeight, channelData, duration, errors });
  drawWave(canvas, 0);

  if (canvas.dataset.wired) return;      // attach listeners only once per canvas
  canvas.dataset.wired = "1";

  function tick() {
    if (!audioEl.paused) {
      drawWave(canvas, audioEl.currentTime);
      requestAnimationFrame(tick);
    }
  }
  audioEl.addEventListener("play", () => requestAnimationFrame(tick));
  audioEl.addEventListener("seeked", () => drawWave(canvas, audioEl.currentTime));
  audioEl.addEventListener("pause", () => drawWave(canvas, audioEl.currentTime));

  canvas.addEventListener("click", (ev) => {
    const s = waveformState.get(canvas);
    if (!s || s.duration <= 0) return;
    const rect = canvas.getBoundingClientRect();
    const frac = (ev.clientX - rect.left) / rect.width;
    audioEl.currentTime = Math.max(0, Math.min(s.duration, frac * s.duration));
    audioEl.play();
  });

  const tooltip = canvas.id === "learner-canvas" ? document.getElementById("learner-tooltip") : null;
  if (tooltip) {
    canvas.addEventListener("mousemove", (ev) => {
      const s = waveformState.get(canvas);
      if (!s || s.duration <= 0) return;
      const rect = canvas.getBoundingClientRect();
      const t = ((ev.clientX - rect.left) / rect.width) * s.duration;
      const hit = s.errors.find((x) => x.start != null && x.end != null && t >= x.start && t <= x.end);
      if (hit) {
        tooltip.hidden = false;
        tooltip.style.left = Math.min(ev.clientX - rect.left + 8, rect.width - 270) + "px";
        tooltip.style.top = "8px";
        tooltip.innerHTML = `<strong>${ERROR_LABELS[hit.type] || hit.type}</strong><br>
          Guru: ${escapeHtml(hit.guru_akshara || "-")} &rarr; Learner: ${escapeHtml(hit.learner_akshara || "-")}<br>
          ${escapeHtml(hit.note || "")}`;
      } else {
        tooltip.hidden = true;
      }
    });
    canvas.addEventListener("mouseleave", () => { tooltip.hidden = true; });
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------------- init ---------------- */
loadItems();
updateButtons();