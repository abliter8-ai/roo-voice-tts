/** Roo Voice v2 frontend (IP-178).
 *
 * Engine discovery: inside Tauri the shell hands us the sidecar port (invoke +
 * event); in a plain browser (Vite dev / Playwright iteration) we fall back to
 * `?engine=PORT` or 8321. Everything else talks HTTP to the engine.
 */
import { Visualizer } from "./visualizer";
import { Composer } from "./compose";

const $ = <T extends HTMLElement>(sel: string) => document.querySelector(sel) as T;

const els = {
  status: $("#status"),
  download: $("#download"),
  dlLabel: $(".dl-label"),
  dlFill: $<HTMLDivElement>(".dl-fill"),
  text: $<HTMLTextAreaElement>("#text"),
  generate: $<HTMLButtonElement>("#generate"),
  save: $<HTMLButtonElement>("#save"),
  meta: $("#meta"),
  error: $("#error"),
  hList: $("#h-list"),
  hCount: $("#h-count"),
  fModel: $("#f-model"),
  fEngine: $("#f-engine"),
};

const viz = new Visualizer($("#viz") as HTMLCanvasElement);

// ---------- engine discovery ----------
let enginePort: number | null = null;
let base = "";

async function discoverPort(): Promise<number> {
  const tauri = (window as any).__TAURI__;
  if (tauri) {
    const invoke = tauri.core.invoke as (c: string) => Promise<number | null>;
    return new Promise((resolve) => {
      tauri.event.listen("engine-port", (e: { payload: number }) => resolve(e.payload));
      tauri.event.listen("engine-error", (e: { payload: string }) => showFatal(e.payload));
      const tick = async () => {
        const p = await invoke("get_engine_port").catch(() => null);
        if (p) resolve(p);
        else setTimeout(tick, 400);
      };
      tick();
    });
  }
  const q = new URLSearchParams(location.search).get("engine");
  return q ? parseInt(q, 10) : 8321;
}

function showFatal(msg: string) {
  els.status.textContent = "failed";
  els.status.className = "status failed";
  els.error.hidden = false;
  els.error.textContent = msg;
}

// ---------- health / status ----------
let ready = false;

function fmtGB(n: number) { return (n / 1024 ** 3).toFixed(1); }

async function pollHealth() {
  try {
    const r = await fetch(`${base}/healthz`);
    const s = await r.json();
    const busy = els.status.classList.contains("generating") ||
                 els.status.classList.contains("speaking");
    ready = s.status === "ready";
    els.fModel.textContent = s.model || "—";
    els.fEngine.textContent = ready ? `v${s.version}` : s.status;
    els.generate.disabled = !ready || busy;
    if (!busy) {
      els.status.className = `status ${s.status}`;
      els.status.textContent =
        s.status === "ready" ? "ready" :
        s.status === "downloading" && s.download
          ? `downloading ${s.download.label} — ${fmtGB(s.download.got)} / ${fmtGB(s.download.total)} GB`
          : s.status === "failed" ? `failed — ${s.detail}` : `${s.status}…`;
    }
    if (s.status === "downloading" && s.download?.total) {
      els.download.hidden = false;
      els.dlLabel.textContent = `${s.download.label}: ${fmtGB(s.download.got)} / ${fmtGB(s.download.total)} GB`;
      els.dlFill.style.width = `${(100 * s.download.got) / s.download.total}%`;
    } else {
      els.download.hidden = true;
    }
    if (s.status === "failed") { els.error.hidden = false; els.error.textContent = s.detail; }
  } catch {
    els.fEngine.textContent = "connecting";
    els.generate.disabled = true;
  }
  setTimeout(pollHealth, ready ? 3000 : 700);
}

// ---------- audio playback with analysis ----------
let audioCtx: AudioContext | null = null;
let currentSource: AudioBufferSourceNode | null = null;
let lastWav: Blob | null = null;

async function playWav(blob: Blob, onDone?: () => void) {
  audioCtx ??= new AudioContext();
  if (audioCtx.state === "suspended") await audioCtx.resume();
  currentSource?.stop();
  const buf = await audioCtx.decodeAudioData(await blob.arrayBuffer());
  const src = audioCtx.createBufferSource();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  src.buffer = buf;
  src.connect(analyser);
  analyser.connect(audioCtx.destination);
  viz.attachAnalyser(analyser);
  viz.setState("speaking");
  setStatus("speaking", "speaking");
  currentSource = src;
  src.onended = () => {
    if (currentSource === src) {
      viz.setState("idle");
      viz.attachAnalyser(null);
      setStatus(ready ? "ready" : "starting", ready ? "ready" : "starting…");
      onDone?.();
    }
  };
  src.start();
}

function setStatus(cls: string, text: string) {
  els.status.className = `status ${cls}`;
  els.status.textContent = text;
}

// ---------- generation ----------
let progressTimer: number | undefined;

async function generate() {
  const text = els.text.value.trim();
  if (!text || !ready) return;
  els.generate.disabled = true;
  els.error.hidden = true;
  viz.setState("generating");
  setStatus("generating", "generating…");
  progressTimer = window.setInterval(async () => {
    try {
      const p = await (await fetch(`${base}/progress`)).json();
      if (p.phase === "generating" && p.chunks > 1) {
        setStatus("generating", `generating ${p.chunk}/${p.chunks}…`);
      }
    } catch { /* engine busy */ }
  }, 350);
  const t0 = performance.now();
  try {
    const r = await fetch(`${base}/v1/audio/speech`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input: text }),
    });
    if (!r.ok) throw new Error((await r.json()).error ?? `HTTP ${r.status}`);
    const dur = parseFloat(r.headers.get("X-Duration-S") ?? "0");
    const gen = (performance.now() - t0) / 1000;
    lastWav = await r.blob();
    els.save.disabled = false;
    els.meta.textContent =
      `${gen.toFixed(1)}s · ${dur.toFixed(1)}s audio · ${(dur / gen).toFixed(1)}x realtime`;
    await playWav(lastWav);
    await loadHistory();
  } catch (e) {
    viz.setState("idle");
    setStatus("failed", "error");
    els.error.hidden = false;
    els.error.textContent = String(e instanceof Error ? e.message : e);
  } finally {
    window.clearInterval(progressTimer);
    els.generate.disabled = !ready;
  }
}

function saveWav() {
  if (!lastWav) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(lastWav);
  a.download = `roo-voice-${Date.now()}.wav`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- history ----------
interface HistEntry { id: string; text: string; ts: number; duration_s: number; gen_s: number; }

async function loadHistory() {
  try {
    const items: HistEntry[] = await (await fetch(`${base}/history`)).json();
    els.hCount.textContent = items.length ? `${items.length} clips` : "";
    els.hList.innerHTML = "";
    if (!items.length) {
      els.hList.innerHTML = `<li class="h-empty">Nothing yet — your generations will appear here.</li>`;
      return;
    }
    for (const it of items) {
      const li = document.createElement("li");
      const date = new Date(it.ts * 1000).toLocaleString(undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      li.innerHTML = `
        <span class="h-text" title="${esc(it.text)}">${esc(it.text)}</span>
        <span class="h-dur">${it.duration_s.toFixed(1)}s · ${date}</span>`;
      const play = document.createElement("button");
      play.textContent = "Play";
      play.onclick = async () => {
        document.querySelectorAll("#h-list li").forEach(x => x.classList.remove("playing"));
        li.classList.add("playing");
        const wav = await (await fetch(`${base}/history/${it.id}.wav`)).blob();
        lastWav = wav;
        els.save.disabled = false;
        playWav(wav, () => li.classList.remove("playing"));
      };
      const add = document.createElement("button");
      add.textContent = "+";
      add.title = "Add to Compose";
      add.onclick = async () => {
        audioCtx ??= new AudioContext();
        const wav = await (await fetch(`${base}/history/${it.id}.wav`)).blob();
        const buf = await audioCtx.decodeAudioData(await wav.arrayBuffer());
        composer.add(it.id, it.text, buf);
      };
      const del = document.createElement("button");
      del.textContent = "✕";
      del.title = "Delete";
      del.onclick = async () => {
        await fetch(`${base}/history/${it.id}`, { method: "DELETE" });
        loadHistory();
      };
      li.append(play, add, del);
      els.hList.append(li);
    }
  } catch { /* engine not up yet */ }
}

// ---------- compose ----------
const composer = new Composer();
const cEls = {
  section: $("#compose"),
  list: $("#c-list"),
  total: $("#c-total"),
  crossfade: $<HTMLInputElement>("#c-crossfade"),
  preview: $<HTMLButtonElement>("#c-preview"),
  exportBtn: $<HTMLButtonElement>("#c-export"),
  clear: $<HTMLButtonElement>("#c-clear"),
};

function renderCompose() {
  cEls.section.hidden = composer.items.length === 0;
  cEls.total.textContent = `${composer.items.length} clips · ${composer.totalSeconds().toFixed(1)}s`;
  cEls.list.innerHTML = "";
  composer.items.forEach((it, idx) => {
    const li = document.createElement("li");
    const mk = (label: string, title: string, fn: () => void) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.title = title;
      b.onclick = fn;
      return b;
    };
    const num = document.createElement("span");
    num.className = "c-idx";
    num.textContent = String(idx + 1);
    const txt = document.createElement("span");
    txt.className = "h-text";
    txt.textContent = it.text;
    const gap = document.createElement("input");
    gap.className = "c-gap";
    gap.type = "number";
    gap.min = "0";
    gap.max = "5000";
    gap.step = "50";
    gap.value = String(it.gapMs);
    gap.title = "gap after clip (ms)";
    gap.onchange = () => {
      it.gapMs = Math.max(0, parseInt(gap.value || "0", 10));
      cEls.total.textContent = `${composer.items.length} clips · ${composer.totalSeconds().toFixed(1)}s`;
    };
    li.append(num, txt, gap,
      mk("↑", "Move up", () => composer.move(idx, -1)),
      mk("↓", "Move down", () => composer.move(idx, 1)),
      mk("✕", "Remove", () => composer.remove(idx)));
    cEls.list.append(li);
  });
}
composer.onChange = renderCompose;

cEls.crossfade.onchange = () => {
  composer.crossfade = cEls.crossfade.checked;
  renderCompose();
};
cEls.preview.onclick = async () => {
  if (!composer.items.length) return;
  audioCtx ??= new AudioContext();
  if (audioCtx.state === "suspended") await audioCtx.resume();
  currentSource?.stop();
  currentSource = null;
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  analyser.connect(audioCtx.destination);
  viz.attachAnalyser(analyser);
  viz.setState("speaking");
  setStatus("speaking", "playing composition");
  const len = composer.schedule(audioCtx, analyser, audioCtx.currentTime + 0.05);
  window.setTimeout(() => {
    viz.setState("idle");
    viz.attachAnalyser(null);
    setStatus(ready ? "ready" : "starting", ready ? "ready" : "starting…");
  }, (len + 0.2) * 1000);
};
cEls.exportBtn.onclick = async () => {
  if (!composer.items.length) return;
  const blob = await composer.renderWav();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `roo-voice-compose-${Date.now()}.wav`;
  a.click();
  URL.revokeObjectURL(a.href);
};
cEls.clear.onclick = () => {
  composer.items = [];
  renderCompose();
};

function esc(s: string) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

// ---------- boot ----------
els.generate.addEventListener("click", generate);
els.save.addEventListener("click", saveWav);
els.text.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") generate();
});

// ---------- self-update (Tauri only; no-op in browser dev) ----------
async function checkUpdate() {
  const tauri = (window as any).__TAURI__;
  if (!tauri?.updater) return;
  try {
    const update = await tauri.updater.check();
    if (!update) return;
    const pill = document.createElement("button");
    pill.className = "status update-pill";
    pill.textContent = `update ${update.version} — install & restart`;
    pill.onclick = async () => {
      pill.textContent = "downloading…";
      pill.disabled = true;
      await update.downloadAndInstall();
      await tauri.process.relaunch();
    };
    els.status.after(pill);
  } catch { /* offline or endpoint missing — silent */ }
}

(async () => {
  enginePort = await discoverPort();
  base = `http://127.0.0.1:${enginePort}`;
  pollHealth();
  loadHistory();
  checkUpdate();
})();
