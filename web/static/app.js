/* app.js -- talks to /api/evaluate, then renders the learner's waveform
   with each pronunciation error drawn as a colored band at its exact
   (start, end) time interval, per report['timed_errors'] from the
   existing pipeline (src/pipeline.py -> src/alignment/timing.py). */

const ERROR_COLORS = {
  aspiration_error: "#e63946",   // red
  anunasika_error: "#f4a261",    // orange
  dvitva_error: "#9c6ade",       // purple
  conjunct_error: "#457b9d",     // blue
  substitution: "#6c757d",       // gray
  missing: "#111318",            // near-black (no real audio span -- gap)
  extra: "#2a9d8f",              // teal
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

const form = document.getElementById("eval-form");
const statusEl = document.getElementById("status");
const resultsPanel = document.getElementById("results-panel");
const submitBtn = document.getElementById("submit-btn");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  statusEl.hidden = false;
  statusEl.className = "status";
  statusEl.textContent = "Transcribing and scoring the learner's audio -- this can take a little while on first run (Whisper model load)...";
  submitBtn.disabled = true;
  resultsPanel.hidden = true;

  try {
    const fd = new FormData(form);
    const res = await fetch("/api/evaluate", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Server error");

    statusEl.hidden = true;
    await renderResults(data);
  } catch (err) {
    statusEl.className = "status error";
    statusEl.textContent = "Error: " + err.message;
  } finally {
    submitBtn.disabled = false;
  }
});

async function renderResults(data) {
  resultsPanel.hidden = false;

  // ---- flags (prompt-echo / transliteration warnings from the pipeline) ----
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
  if (!data.browser_playback_transcoded) {
    flagsEl.innerHTML += `<div class="flag warn">⚠️ Server-side ffmpeg wasn't found, so the audio is served in its original format -- playback/waveform may not work in Safari for .weba/.webm recordings. Install ffmpeg on the server to fix this.</div>`;
  }

  // ---- score cards ----
  document.getElementById("score-overall").textContent = data.overall_score;
  document.getElementById("grade-label").textContent = data.grade;
  document.getElementById("score-r1").textContent = data.rubric1.score;
  document.getElementById("score-r2").textContent = data.rubric2.score;
  document.getElementById("score-r3").textContent = data.rubric3.score;

  // ---- legend ----
  const legendEl = document.getElementById("legend");
  const typesPresent = new Set(data.timed_errors.map((e) => e.type));
  legendEl.innerHTML = [...typesPresent].map(
    (t) => `<span class="swatch"><i style="background:${ERROR_COLORS[t] || "#888"}"></i>${ERROR_LABELS[t] || t}</span>`
  ).join("");

  // ---- learner audio + waveform ----
  const learnerAudioEl = document.getElementById("learner-audio-el");
  learnerAudioEl.src = data.learner_audio_url;
  const learnerCanvas = document.getElementById("learner-canvas");
  await drawWaveformWithErrors(learnerCanvas, data.learner_audio_url, data.timed_errors, learnerAudioEl, data.duration);

  // ---- guru audio (optional, no error overlay -- it's the correct rendition) ----
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

  // ---- error table ----
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

/* Decodes the audio at `url`, draws a min/max waveform on `canvas`, then
   overlays a colored band for every entry in `errors` that has a known
   (start, end) interval. Wires up click-to-seek and a hover tooltip. */
async function drawWaveformWithErrors(canvas, url, errors, audioEl, fallbackDuration) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || canvas.parentElement.clientWidth || 800;
  const cssHeight = canvas.height;
  canvas.width = cssWidth * dpr;
  canvas.height = cssHeight * dpr;
  canvas.style.height = cssHeight + "px";
  ctx.scale(dpr, dpr);

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

  function draw(playheadTime) {
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    // error bands first (so waveform draws on top)
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

    // waveform
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
          const s = channelData[start + i] || 0;
          if (s < min) min = s;
          if (s > max) max = s;
        }
        ctx.moveTo(x, mid + min * mid * 0.9);
        ctx.lineTo(x, mid + max * mid * 0.9);
      }
      ctx.stroke();
    } else {
      // placeholder flat line if decoding failed (e.g. unsupported codec)
      ctx.beginPath();
      ctx.moveTo(0, cssHeight / 2);
      ctx.lineTo(cssWidth, cssHeight / 2);
      ctx.stroke();
    }

    // playhead
    if (duration > 0 && playheadTime != null) {
      const x = (playheadTime / duration) * cssWidth;
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, cssHeight);
      ctx.stroke();
    }

    // timestamp ticks
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

  draw(0);

  // sync playhead while playing
  function tick() {
    if (!audioEl.paused) {
      draw(audioEl.currentTime);
      requestAnimationFrame(tick);
    }
  }
  audioEl.addEventListener("play", () => requestAnimationFrame(tick));
  audioEl.addEventListener("seeked", () => draw(audioEl.currentTime));
  audioEl.addEventListener("pause", () => draw(audioEl.currentTime));

  // click-to-seek
  canvas.addEventListener("click", (ev) => {
    if (duration <= 0) return;
    const rect = canvas.getBoundingClientRect();
    const frac = (ev.clientX - rect.left) / rect.width;
    audioEl.currentTime = Math.max(0, Math.min(duration, frac * duration));
    audioEl.play();
  });

  // hover tooltip for error bands
  const tooltip = canvas.id === "learner-canvas" ? document.getElementById("learner-tooltip") : null;
  if (tooltip) {
    canvas.addEventListener("mousemove", (ev) => {
      const rect = canvas.getBoundingClientRect();
      const frac = (ev.clientX - rect.left) / rect.width;
      const t = frac * duration;
      const hit = errors.find((e) => e.start != null && e.end != null && t >= e.start && t <= e.end);
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

  window.addEventListener("resize", () => draw(audioEl.currentTime || 0));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}