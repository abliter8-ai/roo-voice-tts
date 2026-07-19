/** Compose editor (IP-178): join history clips into one piece.
 *
 * Reorder, per-clip trailing gap, optional 50 ms equal-power crossfade,
 * preview through the visualizer's analyser, export as 16-bit WAV rendered
 * with OfflineAudioContext at the engine's native 24 kHz.
 */

export interface ComposeItem {
  id: string;
  text: string;
  buffer: AudioBuffer;
  gapMs: number;
}

const SR = 24000;
const XFADE_S = 0.05;

export class Composer {
  items: ComposeItem[] = [];
  crossfade = false;
  onChange: () => void = () => {};

  add(id: string, text: string, buffer: AudioBuffer) {
    if (this.items.some((i) => i.id === id)) return;
    this.items.push({ id, text, buffer, gapMs: 200 });
    this.onChange();
  }

  remove(idx: number) {
    this.items.splice(idx, 1);
    this.onChange();
  }

  move(idx: number, dir: -1 | 1) {
    const j = idx + dir;
    if (j < 0 || j >= this.items.length) return;
    [this.items[idx], this.items[j]] = [this.items[j], this.items[idx]];
    this.onChange();
  }

  totalSeconds(): number {
    let t = 0;
    this.items.forEach((it, i) => {
      t += it.buffer.duration;
      if (i < this.items.length - 1) t += it.gapMs / 1000;
      if (this.crossfade && i < this.items.length - 1) t -= XFADE_S;
    });
    return Math.max(0, t);
  }

  /** Schedule the sequence into any BaseAudioContext; returns total length s. */
  schedule(ctx: BaseAudioContext, dest: AudioNode, startAt = 0): number {
    let t = startAt;
    this.items.forEach((it, i) => {
      const src = ctx.createBufferSource();
      src.buffer = it.buffer;
      const g = ctx.createGain();
      src.connect(g);
      g.connect(dest);
      const xf = this.crossfade && this.items.length > 1 ? XFADE_S : 0;
      if (xf && i > 0) {
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(1, t + xf);
      }
      if (xf && i < this.items.length - 1) {
        const end = t + it.buffer.duration;
        g.gain.setValueAtTime(1, end - xf);
        g.gain.linearRampToValueAtTime(0, end);
      }
      src.start(t);
      t += it.buffer.duration;
      if (i < this.items.length - 1) {
        t += it.gapMs / 1000;
        if (xf) t -= xf;
      }
    });
    return t - startAt;
  }

  async renderWav(): Promise<Blob> {
    const secs = this.totalSeconds();
    const ctx = new OfflineAudioContext(1, Math.ceil(secs * SR) + SR, SR);
    this.schedule(ctx, ctx.destination);
    const rendered = await ctx.startRendering();
    return encodeWav(rendered);
  }
}

function encodeWav(buf: AudioBuffer): Blob {
  const ch = buf.getChannelData(0);
  // trim trailing render padding silence
  let end = ch.length;
  while (end > 0 && Math.abs(ch[end - 1]) < 1e-4) end--;
  end = Math.min(ch.length, end + SR / 10);
  const pcm = new Int16Array(end);
  for (let i = 0; i < end; i++) {
    pcm[i] = Math.max(-32768, Math.min(32767, Math.round(ch[i] * 32767)));
  }
  const bytes = pcm.byteLength;
  const head = new ArrayBuffer(44);
  const v = new DataView(head);
  const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + bytes, true); w(8, "WAVE");
  w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, SR, true);
  v.setUint32(28, SR * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, bytes, true);
  return new Blob([head, pcm.buffer], { type: "audio/wav" });
}
