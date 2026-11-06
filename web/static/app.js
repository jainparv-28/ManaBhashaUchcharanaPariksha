/* app.js -- verse picker, live recorder with level meter, silence check,
   evaluation with loading overlay, friendly error panel, and a rich results view. */

const ERROR_COLORS = {
  aspiration_error: "#e63946", anunasika_error: "#f4a261", dvitva_error: "#9c6ade",
  conjunct_error: "#457b9d", vowel_length_error: "#f2cc8f", vowel_error: "#e07a5f",
  visarga_error: "#81b29a", substitution: "#8d99ae", missing: "#b0b7c3", extra: "#2a9d8f",
};
const ERROR_LABELS = {
  aspiration_error: "Aspiration", anunasika_error: "Anunasika", dvitva_error: "Dvitva / gemination",
  conjunct_error: "Sanyukta / conjunct", vowel_length_error: "Vowel length", vowel_error: "Wrong vowel",
  visarga_error: "Visarga (ः)", substitution: "Substitution", missing: "Missing", extra: "Extra",
};
const MAX_RECORD_SECONDS = 180;
const LOADING_MESSAGES = ["Uploading recording…", "Transcribing the speech…", "Aligning syllables…",
                          "Checking aspiration, nasals and conjuncts…", "Scoring the rubrics…"];

const $ = (id) => document.getElementById(id);
const form = $("eval-form"), statusEl = $("status"), resultsPanel = $("results-panel");
const submitBtn = $("submit-btn"), itemSelect = $("item_select"), itemDetail = $("item-detail");
const guruSelectAudio = $("guru-select-audio"), refTextEl = $("ref-text");
const recBtn = $("rec-btn"), playBtn = $("play-btn"), stopBtn = $("stop-btn");
const recTimerEl = $("rec-timer"), recStateEl = $("rec-state"), recAudio = $("rec-audio");
const meter = $("meter");

let items = {}, mediaRecorder = null, recStream = null, recChunks = [], recordedBlob = null;
let recording = false, busy = false, timerId = null, recStartedAt = 0;
let meterCtx = null, analyser = null, meterRAF = null, loadingTimer = null;
let activeFilters = new Set(), lastErrors = [], lastLearnerAudio = null;

/* ---------------- theme ---------------- */
(function initTheme() {
  const saved = localStorage.getItem("theme");
  const prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  document.documentElement.dataset.theme = saved || (prefersLight ? "light" : "dark");
})();
$("theme-btn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
  for (const c of [$("learner-canvas"), $("guru-canvas")]) drawWave(c, 0);
});

/* ---------------- helpers ---------------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function toast(msg, kind = "info", ms = 4500) {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), ms);
}
function showStatus(kind, msg) {
  statusEl.hidden = false;
  if (kind === "error") {
    statusEl.className = "status error";
    statusEl.innerHTML = `<div class="err-title">⚠️ Couldn't evaluate this recording</div>
      <div class="err-msg">${escapeHtml(String(msg).replace(/^Error:\s*/, ""))}</div>
      <ul class="err-tips">
        <li>Recite the verse shown above in its own language.</li>
        <li>Speak clearly, close to the microphone, in a quiet place.</li>
        <li>Record the whole verse, then press Evaluate again.</li>
      </ul>`;
  } else {
    statusEl.className = "status";
    statusEl.textContent = msg;
  }
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
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]
    .find((t) => MediaRecorder.isTypeSupported(t)) || "";
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function scoreColor(s) { return s >= 90 ? "var(--good)" : s >= 75 ? "var(--ok)" : s >= 60 ? "var(--warn)" : "var(--bad)"; }

function setStep(n) {
  document.querySelectorAll("#steps li").forEach((li) => {
    const k = +li.dataset.step;
    li.classList.toggle("done", k < n);
    li.classList.toggle("active", k === n);
  });
}

function updateButtons() {
  const hasItem = !!itemSelect.value;
  const playing = !recAudio.paused && !recAudio.ended && !!recordedBlob;
  recBtn.disabled = !hasItem || busy;
  recBtn.classList.toggle("active", recording);
  recBtn.setAttribute("aria-label", recording ? "Stop recording" : "Record");
  playBtn.disabled = !recordedBlob || recording || playing || busy;
  stopBtn.disabled = !(recording || playing);
  submitBtn.disabled = !hasItem || !recordedBlob || recording || busy;

  if (recording) { recStateEl.textContent = "● Recording… press the button to stop"; recStateEl.className = "rec-state live"; }
  else if (recordedBlob) { recStateEl.textContent = "Recording ready — play it back or evaluate"; recStateEl.className = "rec-state"; }
  else if (hasItem) { recStateEl.textContent = "Press the microphone to start"; recStateEl.className = "rec-state"; }
  else { recStateEl.textContent = "Select a verse to begin"; recStateEl.className = "rec-state"; }

  if (!hasItem) setStep(1);
  else if (!recordedBlob) setStep(2);
  else if (resultsPanel.hidden) setStep(3);
}

/* ---------------- verse dropdown ---------------- */
async function loadItems() {
  try {
    const res = await fetch("/api/items");
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load items");
    for (const it of data.items) {
      items[it.id] = it;
      const opt = document.createElement("option");
      opt.value = it.id; opt.textContent = it.label;
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
    guruSelectAudio.removeAttribute("src"); guruSelectAudio.load();
    updateButtons();
    return;
  }
  itemDetail.hidden = false;
  refTextEl.textContent = it.text;
  refTextEl.lang = it.lang === "te" ? "te" : "sa";
  $("lang-badge").textContent = it.language || (it.lang === "te" ? "Telugu" : "Sanskrit");
  if (it.audio_url) {
    guruSelectAudio.hidden = false; $("no-audio-note").hidden = true;
    guruSelectAudio.src = it.audio_url; guruSelectAudio.load();
  } else {
    guruSelectAudio.hidden = true; $("no-audio-note").hidden = false;
    guruSelectAudio.removeAttribute("src");
  }
  updateButtons();
});

/* ---------------- level meter ---------------- */
function sizeMeter() {
  const dpr = window.devicePixelRatio || 1;
  const w = meter.clientWidth || 600, h = 64;
  meter.width = w * dpr; meter.height = h * dpr;
  const ctx = meter.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}
function drawIdleMeter() {
  const { ctx, w, h } = sizeMeter();
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = cssVar("--border"); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
}
function startMeter(stream) {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    meterCtx = new AC();
    const src = meterCtx.createMediaStreamSource(stream);
    analyser = meterCtx.createAnalyser(); analyser.fftSize = 1024;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    const { ctx, w, h } = sizeMeter();
    const loop = () => {
      analyser.getByteTimeDomainData(buf);
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = cssVar("--bad"); ctx.lineWidth = 2; ctx.beginPath();
      for (let i = 0; i < buf.length; i++) {
        const x = (i / (buf.length - 1)) * w, y = (buf[i] / 255) * h;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
      meterRAF = requestAnimationFrame(loop);
    };
    loop();
  } catch (e) { drawIdleMeter(); }
}
function stopMeter() {
  if (meterRAF) cancelAnimationFrame(meterRAF);
  meterRAF = null;
  if (meterCtx) { try { meterCtx.close(); } catch (e) {} meterCtx = null; }
  drawIdleMeter();
}

/* ---------------- recording ---------------- */
function releaseStream() { if (recStream) { recStream.getTracks().forEach((t) => t.stop()); recStream = null; } }
function startTimer() {
  recStartedAt = Date.now(); recTimerEl.textContent = "00:00";
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
  releaseStream(); stopTimer(); stopMeter();
  recording = false; recChunks = []; recordedBlob = null;
  recAudio.pause(); recAudio.removeAttribute("src"); recAudio.load();
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
    recStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true }
    });
  } catch (err) {
    showStatus("error", "Microphone unavailable or permission denied: " + err.message);
    toast("Microphone permission denied", "error");
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
    releaseStream(); stopTimer(); stopMeter();
    recording = false;
    updateButtons();
  };
  mediaRecorder.start();
  recording = true;
  startMeter(recStream);
  startTimer();
  updateButtons();
}

function stopAny() {
  if (recording && mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  } else {
    recAudio.pause(); recAudio.currentTime = 0;
    updateButtons();
  }
}

recBtn.addEventListener("click", () => { recording ? stopAny() : startRecording(); });
stopBtn.addEventListener("click", stopAny);
playBtn.addEventListener("click", () => { if (recordedBlob) recAudio.play(); });
["play", "pause", "ended"].forEach((ev) => recAudio.addEventListener(ev, updateButtons));
recAudio.addEventListener("timeupdate", () => {
  if (!recording && !recAudio.paused) recTimerEl.textContent = fmtTime(recAudio.currentTime);
});
window.addEventListener("resize", () => { if (!recording) drawIdleMeter(); });

async function analyzeRecording(blob) {
  try {
    const buf = await blob.arrayBuffer();
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();
    let audio;
    try { audio = await ctx.decodeAudioData(buf); } finally { ctx.close(); }
    const d = audio.getChannelData(0);
    const frame = Math.max(1, Math.floor(audio.sampleRate * 0.02));
    let active = 0, frames = 0, peak = 0;
    for (let i = 0; i + frame <= d.length; i += frame) {
      let s = 0;
      for (let j = 0; j < frame; j++) { const v = d[i + j]; s += v * v; const a = Math.abs(v); if (a > peak) peak = a; }
      frames++;
      if (Math.sqrt(s / frame) > 0.01) active++;
    }
    return { duration: audio.duration, peak, activeRatio: frames ? active / frames : 0 };
  } catch (e) { return null; }
}

/* ---------------- loading overlay ---------------- */
function showLoading() {
  let i = 0;
  $("loading-msg").textContent = LOADING_MESSAGES[0];
  $("loading").hidden = false;
  loadingTimer = setInterval(() => {
    i = Math.min(i + 1, LOADING_MESSAGES.length - 1);
    $("loading-msg").textContent = LOADING_MESSAGES[i];
  }, 1800);
}
function hideLoading() { $("loading").hidden = true; if (loadingTimer) { clearInterval(loadingTimer); loadingTimer = null; } }

/* ---------------- evaluate ---------------- */
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!itemSelect.value || !recordedBlob) return;
  busy = true; updateButtons();

  const stats = await analyzeRecording(recordedBlob);
  if (stats) {
    let problem = null;
    if (stats.duration < 1.5) problem = "The recording is too short -- please record the full recitation.";
    else if (stats.peak < 0.02) problem = "The recording is silent -- the microphone captured no sound.";
    else if (stats.activeRatio < 0.08) problem = "Almost no speech was detected. Speak closer to the microphone.";
    if (problem) {
      showStatus("error", problem); toast(problem, "error");
      busy = false; updateButtons();
      return;
    }
  }

  resultsPanel.hidden = true;
  statusEl.hidden = true;
  setStep(3);
  showLoading();

  try {
    const fd = new FormData();
    fd.append("item_id", itemSelect.value);
    fd.append("learner_audio", recordedBlob, "learner" + extFor(recordedBlob.type));
    const res = await fetch("/api/evaluate", { method: "POST", body: fd });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("Server error (" + res.status + ")"));
    hideLoading();
    await renderResults(data);
    setStep(5);   // all steps done
    resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    toast("Evaluation complete", "ok", 2500);
  } catch (err) {
    hideLoading();
    showStatus("error", err.message);
    statusEl.scrollIntoView({ behavior: "smooth", block: "center" });
    toast(err.message, "error", 7000);
    setStep(3);
  } finally {
    busy = false; updateButtons();
  }
});

$("again-btn").addEventListener("click", () => {
  clearRecording();
  resultsPanel.hidden = true;
  $("record-card").scrollIntoView({ behavior: "smooth", block: "start" });
});

/* ---------------- results ---------------- */
function animateScore(el, score) {
  const target = Number(score) || 0, start = performance.now(), dur = 900;
  const step = (t) => {
    const p = Math.min((t - start) / dur, 1);
    el.textContent = (target * p).toFixed(target % 1 ? 1 : 0);
    if (p < 1) requestAnimationFrame(step); else el.textContent = String(score);
  };
  requestAnimationFrame(step);
}
function setBar(id, valId, score) {
  const bar = $(id);
  bar.style.width = "0%";
  requestAnimationFrame(() => { bar.style.width = Math.max(0, Math.min(100, score)) + "%"; });
  bar.style.background = scoreColor(score);
  $(valId).textContent = score;
}

async function renderResults(data) {
  resultsPanel.hidden = false;

  const flagsEl = $("flags");
  const flags = [];
  const rel = data.reliability || "high";
  flags.push(`<div class="flag rel-${rel}">Result reliability: <strong>${rel.toUpperCase()}</strong></div>`);
  if (data.score_valid === false)
    flags.push(`<div class="flag bad">⛔ This score is NOT reliable -- the recording does not match the selected text well enough.</div>`);
  if (data.asr_flagged)
    flags.push(`<div class="flag warn">🚩 ${escapeHtml(data.asr_flag_reason || "ASR quality flag")} -- spot-check the audio manually.</div>`);
  if (data.used_transliteration_fallback)
    flags.push(`<div class="flag warn">⚠️ ASR output was romanized and auto-transliterated -- lower confidence.</div>`);
  if (!data.timing_available)
    flags.push(`<div class="flag warn">ℹ️ Word-level timing wasn't available -- errors are listed without timestamps.</div>`);
  (data.quality_warnings || []).forEach((w) => flags.push(`<div class="flag warn">⚠️ ${escapeHtml(w)}</div>`));
  flagsEl.innerHTML = flags.join("");

  const overall = Number(data.overall_score) || 0;
  const ring = $("ring-fg");
  ring.style.strokeDashoffset = 339.292;
  ring.style.stroke = scoreColor(overall);
  requestAnimationFrame(() => { ring.style.strokeDashoffset = 339.292 * (1 - Math.max(0, Math.min(100, overall)) / 100); });
  animateScore($("score-overall"), data.overall_score);
  $("grade-label").textContent = data.grade;
  setBar("bar-r1", "score-r1", data.rubric1.score);
  setBar("bar-r2", "score-r2", data.rubric2.score);
  setBar("bar-r3", "score-r3", data.rubric3.score);

  $("practice").innerHTML = (data.practice_points || []).map((p) => `
    <div class="practice-item">
      <div class="p-head"><span>${escapeHtml(p.category)}</span><span class="p-count">${p.count}</span></div>
      <div class="p-ex">${escapeHtml(p.examples.join("   ·   "))}</div>
      <div class="p-adv">${escapeHtml(p.advice)}</div>
    </div>`).join("") || `<div class="practice-empty">✓ No problem areas found.</div>`;

  $("guru-text-out").textContent = data.guru_text || "";
  $("learner-text-out").textContent = data.learner_text || "";

  lastErrors = data.timed_errors || [];
  activeFilters = new Set(lastErrors.map((e) => e.type));
  $("legend").innerHTML = [...activeFilters].map(
    (t) => `<span class="swatch"><i style="background:${ERROR_COLORS[t] || "#888"}"></i>${ERROR_LABELS[t] || t}</span>`).join("");
  buildFilters();

  const learnerAudioEl = $("learner-audio-el");
  lastLearnerAudio = learnerAudioEl;
  learnerAudioEl.src = data.learner_audio_url;
  buildTable();
  await drawWaveformWithErrors($("learner-canvas"), data.learner_audio_url, lastErrors, learnerAudioEl, data.duration);

  const guruSection = $("guru-audio-section");
  if (data.guru_audio_url) {
    guruSection.hidden = false;
    const g = $("guru-audio-el");
    g.src = data.guru_audio_url;
    await drawWaveformWithErrors($("guru-canvas"), data.guru_audio_url, [], g, null);
  } else {
    guruSection.hidden = true;
  }
}

function buildFilters() {
  const types = [...new Set(lastErrors.map((e) => e.type))];
  $("err-filters").innerHTML = types.map((t) => {
    const n = lastErrors.filter((e) => e.type === t).length;
    return `<button type="button" class="chip ${activeFilters.has(t) ? "" : "off"}" data-type="${t}">
      <i style="background:${ERROR_COLORS[t] || "#888"}"></i>${ERROR_LABELS[t] || t} (${n})</button>`;
  }).join("");
  $("err-filters").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    const t = c.dataset.type;
    activeFilters.has(t) ? activeFilters.delete(t) : activeFilters.add(t);
    c.classList.toggle("off", !activeFilters.has(t));
    buildTable();
  }));
}

function buildTable() {
  const tbody = document.querySelector("#error-table tbody");
  tbody.innerHTML = "";
  const rows = lastErrors.filter((e) => activeFilters.has(e.type))
    .sort((a, b) => (a.start ?? 1e9) - (b.start ?? 1e9));
  $("err-count").textContent = lastErrors.length ? `${rows.length} of ${lastErrors.length} shown` : "";
  if (!rows.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="5">${lastErrors.length ? "No errors match the filter." : "🎉 No errors detected."}</td></tr>`;
    return;
  }
  for (const err of rows) {
    const tr = document.createElement("tr");
    const timeLabel = err.start != null
      ? `${err.start.toFixed(2)}s${err.approximate ? " ~" : ""} – ${err.end != null ? err.end.toFixed(2) + "s" : "?"}` : "—";
    const unsure = err.uncertain ? ` <em title="The recogniser was unsure about this word">(uncertain)</em>` : "";
    tr.innerHTML = `
      <td>${timeLabel}</td>
      <td><span class="swatch"><i style="background:${ERROR_COLORS[err.type] || "#888"}"></i>${ERROR_LABELS[err.type] || err.type}</span></td>
      <td>${escapeHtml(err.guru_akshara || "-")}</td>
      <td>${escapeHtml(err.learner_akshara || "-")}</td>
      <td>${escapeHtml(err.note || "")}${unsure}</td>`;
    if (err.start != null) {
      tr.classList.add("clickable");
      tr.addEventListener("click", () => {
        if (!lastLearnerAudio) return;
        lastLearnerAudio.currentTime = err.start;
        lastLearnerAudio.play();
      });
    }
    tbody.appendChild(tr);
  }
}

/* ---------------- waveform with error bands ---------------- */
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
      const col = ERROR_COLORS[err.type] || "#888";
      ctx.fillStyle = col + "55"; ctx.fillRect(x1, 0, x2 - x1, cssHeight);
      ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.strokeRect(x1, 0, x2 - x1, cssHeight);
    }
  }

  ctx.strokeStyle = cssVar("--wave"); ctx.lineWidth = 1;
  const mid = cssHeight / 2;
  ctx.beginPath();
  if (channelData) {
    const spp = Math.max(1, Math.floor(channelData.length / cssWidth));
    for (let x = 0; x < cssWidth; x++) {
      let min = 1, max = -1;
      const st = x * spp;
      for (let i = 0; i < spp; i++) { const v = channelData[st + i] || 0; if (v < min) min = v; if (v > max) max = v; }
      ctx.moveTo(x, mid + min * mid * 0.9); ctx.lineTo(x, mid + max * mid * 0.9);
    }
  } else { ctx.moveTo(0, mid); ctx.lineTo(cssWidth, mid); }
  ctx.stroke();

  if (duration > 0 && playheadTime != null) {
    const x = (playheadTime / duration) * cssWidth;
    ctx.strokeStyle = cssVar("--text"); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cssHeight); ctx.stroke();
  }

  ctx.fillStyle = cssVar("--muted"); ctx.font = "10px sans-serif";
  if (duration > 0) {
    const every = duration > 20 ? 5 : (duration > 8 ? 2 : 1);
    for (let t = 0; t <= duration; t += every) {
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
  canvas.width = cssWidth * dpr; canvas.height = cssHeight * dpr;
  canvas.style.height = cssHeight + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  let channelData = null, duration = fallbackDuration || 0;
  try {
    const resp = await fetch(url);
    const buf = await resp.arrayBuffer();
    const AC = window.AudioContext || window.webkitAudioContext;
    const actx = new AC();
    const ab = await actx.decodeAudioData(buf);
    channelData = ab.getChannelData(0); duration = ab.duration;
    actx.close();
  } catch (e) { console.warn("Could not decode audio for waveform:", e); }

  waveformState.set(canvas, { ctx, cssWidth, cssHeight, channelData, duration, errors });
  drawWave(canvas, 0);

  if (canvas.dataset.wired) return;
  canvas.dataset.wired = "1";

  function tick() { if (!audioEl.paused) { drawWave(canvas, audioEl.currentTime); requestAnimationFrame(tick); } }
  audioEl.addEventListener("play", () => requestAnimationFrame(tick));
  audioEl.addEventListener("seeked", () => drawWave(canvas, audioEl.currentTime));
  audioEl.addEventListener("pause", () => drawWave(canvas, audioEl.currentTime));

  canvas.addEventListener("click", (ev) => {
    const s = waveformState.get(canvas);
    if (!s || s.duration <= 0) return;
    const rect = canvas.getBoundingClientRect();
    audioEl.currentTime = Math.max(0, Math.min(s.duration, ((ev.clientX - rect.left) / rect.width) * s.duration));
    audioEl.play();
  });

  const tooltip = canvas.id === "learner-canvas" ? $("learner-tooltip") : null;
  if (tooltip) {
    canvas.addEventListener("mousemove", (ev) => {
      const s = waveformState.get(canvas);
      if (!s || s.duration <= 0) return;
      const rect = canvas.getBoundingClientRect();
      const t = ((ev.clientX - rect.left) / rect.width) * s.duration;
      const hit = s.errors.find((x) => x.start != null && x.end != null && t >= x.start && t <= x.end);
      if (hit) {
        tooltip.hidden = false;
        tooltip.style.left = Math.max(0, Math.min(ev.clientX - rect.left + 8, rect.width - 280)) + "px";
        tooltip.style.top = "8px";
        tooltip.innerHTML = `<strong>${ERROR_LABELS[hit.type] || hit.type}</strong><br>
          Guru: ${escapeHtml(hit.guru_akshara || "-")} &rarr; Learner: ${escapeHtml(hit.learner_akshara || "-")}<br>
          ${escapeHtml(hit.note || "")}`;
      } else { tooltip.hidden = true; }
    });
    canvas.addEventListener("mouseleave", () => { tooltip.hidden = true; });
  }
}

/* ---------------- init ---------------- */
loadItems();
updateButtons();
drawIdleMeter();