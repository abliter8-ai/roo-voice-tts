/** Roo Voice — engine client + audio playback service.
 *
 * The transport half of the old vanilla frontend, extracted for the React UI:
 * port discovery (Tauri shell handoff, ?engine= fallback), health polling,
 * generation, history CRUD, decoded-audio cache with real waveform peaks,
 * and a single shared player with progress callbacks.
 */

export interface HealthState {
  status: "connecting" | "starting" | "downloading" | "loading" | "warming" | "ready" | "failed";
  detail: string;
  version?: string;
  model?: string;
  download?: { label: string; got: number; total: number } | null;
}

export interface HistEntry {
  id: string;
  text: string;
  title?: string;
  ts: number;
  duration_s: number;
  gen_s: number;
}

let base = "";
let enginePort: number | null = null;

export async function discoverPort(): Promise<number> {
  const tauri = (window as any).__TAURI__;
  if (tauri) {
    const invoke = tauri.core.invoke as (c: string) => Promise<number | null>;
    return new Promise((resolve) => {
      tauri.event.listen("engine-port", (e: { payload: number }) => resolve(e.payload));
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

export async function connect(): Promise<void> {
  enginePort = await discoverPort();
  base = `http://127.0.0.1:${enginePort}`;
}

export async function fetchHealth(): Promise<HealthState> {
  try {
    const r = await fetch(`${base}/healthz`);
    return (await r.json()) as HealthState;
  } catch {
    return { status: "connecting", detail: "" };
  }
}

export async function generate(text: string, title?: string): Promise<{ id: string; durationS: number; genS: number }> {
  const r = await fetch(`${base}/v1/audio/speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(title ? { input: text, title } : { input: text }),
  });
  if (!r.ok) throw new Error(((await r.json()) as { error?: string }).error ?? `HTTP ${r.status}`);
  await r.blob(); // wav also lands in history; the UI plays from there
  return {
    id: r.headers.get("X-History-Id") ?? "",
    durationS: parseFloat(r.headers.get("X-Duration-S") ?? "0"),
    genS: parseFloat(r.headers.get("X-Gen-S") ?? "0"),
  };
}

export async function fetchProgress(): Promise<{ phase: string; chunk: number; chunks: number }> {
  const r = await fetch(`${base}/progress`);
  return await r.json();
}

export async function listHistory(): Promise<HistEntry[]> {
  const r = await fetch(`${base}/history`);
  return (await r.json()) as HistEntry[];
}

export async function deleteClip(id: string): Promise<void> {
  await fetch(`${base}/history/${id}`, { method: "DELETE" });
}

export function wavUrl(id: string): string {
  return `${base}/history/${id}.wav`;
}

/* ---------------- decoded-audio cache + peaks ---------------- */

const ctx = new AudioContext();
const bufferCache = new Map<string, AudioBuffer>();
const peaksCache = new Map<string, number[]>();

export async function getBuffer(id: string): Promise<AudioBuffer> {
  const hit = bufferCache.get(id);
  if (hit) return hit;
  const blob = await (await fetch(wavUrl(id))).blob();
  const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
  bufferCache.set(id, buf);
  return buf;
}

/** Real per-bar amplitudes (0..1) for the Waveform component. */
export async function getPeaks(id: string, bars: number): Promise<number[]> {
  const key = `${id}:${bars}`;
  const hit = peaksCache.get(key);
  if (hit) return hit;
  const buf = await getBuffer(id);
  const ch = buf.getChannelData(0);
  const step = Math.floor(ch.length / bars) || 1;
  const peaks: number[] = [];
  let max = 0;
  for (let b = 0; b < bars; b++) {
    let sum = 0;
    const start = b * step;
    for (let i = start; i < start + step && i < ch.length; i += 4) sum += ch[i] * ch[i];
    const rms = Math.sqrt(sum / (step / 4));
    peaks.push(rms);
    if (rms > max) max = rms;
  }
  const norm = peaks.map((p) => Math.min(1, 0.1 + (max ? (p / max) * 0.9 : 0)));
  peaksCache.set(key, norm);
  return norm;
}

export function saveBlobAs(blob: Blob, name: string): void {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function saveClip(id: string, name: string): Promise<void> {
  saveBlobAs(await (await fetch(wavUrl(id))).blob(), name);
}

/* ---------------- shared player ---------------- */

type ProgressCb = (progress: number, playing: boolean) => void;

class Player {
  private source: AudioBufferSourceNode | null = null;
  private buffer: AudioBuffer | null = null;
  private startedAt = 0;
  private offset = 0;
  private raf = 0;
  clipId: string | null = null;
  playing = false;
  private listeners = new Set<ProgressCb>();

  onProgress(cb: ProgressCb): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private emit() {
    const p = this.progress();
    this.listeners.forEach((cb) => cb(p, this.playing));
  }

  progress(): number {
    if (!this.buffer) return 0;
    const t = this.playing ? this.offset + (ctx.currentTime - this.startedAt) : this.offset;
    return Math.min(1, t / this.buffer.duration);
  }

  async play(id: string, from = 0): Promise<void> {
    this.stop(false);
    if (ctx.state === "suspended") await ctx.resume();
    this.buffer = await getBuffer(id);
    this.clipId = id;
    this.offset = from * this.buffer.duration;
    const src = ctx.createBufferSource();
    src.buffer = this.buffer;
    src.connect(ctx.destination);
    src.onended = () => {
      if (this.source === src) {
        this.playing = false;
        this.offset = 0;
        this.emit();
        cancelAnimationFrame(this.raf);
      }
    };
    this.source = src;
    this.startedAt = ctx.currentTime;
    this.playing = true;
    src.start(0, this.offset);
    const loop = () => {
      this.emit();
      if (this.playing) this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  pause(): void {
    if (!this.playing || !this.source) return;
    this.offset = this.offset + (ctx.currentTime - this.startedAt);
    this.source.onended = null;
    this.source.stop();
    this.source = null;
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.emit();
  }

  async toggle(id: string): Promise<void> {
    if (this.clipId === id && this.playing) this.pause();
    else if (this.clipId === id && this.offset > 0) await this.play(id, this.progress());
    else await this.play(id);
  }

  stop(emit = true): void {
    if (this.source) {
      this.source.onended = null;
      try { this.source.stop(); } catch { /* already stopped */ }
      this.source = null;
    }
    this.playing = false;
    this.offset = 0;
    cancelAnimationFrame(this.raf);
    if (emit) this.emit();
  }
}

export const player = new Player();
export const audioCtx = ctx;

export function fmtDur(s: number): string {
  const t = Math.max(0, Math.round(s));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}
