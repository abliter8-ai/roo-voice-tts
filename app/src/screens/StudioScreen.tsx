/** StudioScreen — the design's timeline editor wired to the real Composer
 * (offline-rendered WAV export, verified in IP-178). Design deviations:
 * per-clip gap input (real shipped feature) added to track rows in the same
 * mono style; export badge says the honest 24 kHz. */
import React from "react";
import { ClipCard, Button, Card, Badge, IconButton, Waveform } from "../design/components";
import { Plus, Download, GripV, Trash, Layers } from "../design/icons";
import { Composer } from "../compose";
import { HistEntry, player, getBuffer, getPeaks, fmtDur, audioCtx, saveBlobAs } from "../engine";

const composer = new Composer();

export function StudioScreen({ clips }: { clips: HistEntry[] }) {
  const [, force] = React.useReducer((x: number) => x + 1, 0);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [activeProgress, setActiveProgress] = React.useState(0);
  const [previewing, setPreviewing] = React.useState(false);
  const [peaksById, setPeaksById] = React.useState<Record<string, number[]>>({});

  React.useEffect(() => {
    composer.onChange = force;
    return () => { composer.onChange = () => {}; };
  }, []);

  React.useEffect(() => player.onProgress((p, playing) => {
    setActiveProgress(p);
    if (!playing && activeId && player.clipId === activeId) setActiveId(null);
  }), [activeId]);

  React.useEffect(() => {
    clips.slice(0, 30).forEach((c) => {
      if (!peaksById[c.id]) {
        getPeaks(c.id, 44).then((pk) => setPeaksById((m) => ({ ...m, [c.id]: pk }))).catch(() => {});
      }
    });
  }, [clips]);

  const titleOf = (c: HistEntry) => c.title || (c.text.length > 30 ? c.text.slice(0, 30) + "…" : c.text);

  const add = async (c: HistEntry) => {
    const buf = await getBuffer(c.id);
    composer.add(c.id, titleOf(c), buf);
  };

  const preview = async () => {
    if (!composer.items.length) return;
    player.stop();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    setPreviewing(true);
    const len = composer.schedule(audioCtx, audioCtx.destination, audioCtx.currentTime + 0.05);
    window.setTimeout(() => setPreviewing(false), (len + 0.2) * 1000);
  };

  const exportWav = async () => {
    if (!composer.items.length) return;
    saveBlobAs(await composer.renderWav(), `roo-voice-studio-${new Date().toISOString().slice(0, 10)}.wav`);
  };

  const total = composer.totalSeconds();

  return (
    <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", height: "100%", minHeight: 0 }}>
      {/* Library */}
      <div style={{ borderRight: "1px solid var(--border-default)", display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ padding: "20px 20px 14px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>Clip library</span>
          <Badge variant="neutral">{clips.length}</Badge>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 16px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
          {clips.map((c) => (
            <div key={c.id} style={{ position: "relative" }}>
              <ClipCard title={titleOf(c)} duration={fmtDur(c.duration_s)} text={c.text}
                playing={activeId === c.id && player.playing} progress={activeId === c.id ? activeProgress : 0}
                heights={peaksById[c.id]}
                onToggle={() => { setActiveId(c.id); player.toggle(c.id); }}
                selected={!!composer.items.find((t) => t.id === c.id)} />
              <button onClick={() => add(c)} title="Add to timeline"
                style={{ position: "absolute", top: 10, right: 10, width: 24, height: 24, borderRadius: 6, display: "grid", placeItems: "center", background: "var(--surface-active)", border: "1px solid var(--border-default)", color: "var(--text-secondary)", cursor: "pointer" }}>
                <Plus size={13} />
              </button>
            </div>
          ))}
          {clips.length === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-disabled)", fontFamily: "var(--font-sans)", fontSize: 13 }}>
              Generate clips and they'll appear here.
            </div>
          )}
        </div>
      </div>

      {/* Timeline + export */}
      <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ padding: "20px 28px 12px", display: "flex", alignItems: "center", gap: 12 }}>
          <Layers size={18} style={{ color: "var(--roo-red)" }} />
          <span style={{ fontFamily: "var(--font-display)", fontSize: 26, letterSpacing: ".03em", color: "var(--white)", textTransform: "uppercase" }}>Studio</span>
          <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-secondary)" }}>{composer.items.length} clips · {fmtDur(total)}</span>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "8px 28px" }}>
          <Card padding={18} style={{ marginBottom: 18 }}>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--text-muted)", marginBottom: 14 }}>
              Assembled preview{previewing ? " — playing" : ""}
            </div>
            <Waveform bars={120} height={54} progress={previewing ? 0.5 : 0.28} playing={previewing} color="var(--n-600)" />
          </Card>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {composer.items.map((c, i) => (
              <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", background: "var(--surface-card)", border: "1px solid var(--border-default)", borderLeft: "3px solid var(--roo-red)", borderRadius: "var(--radius-md)" }}>
                <span style={{ color: "var(--text-disabled)", display: "inline-flex" }}><GripV size={16} /></span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)", width: 20 }}>{i + 1}</span>
                <span style={{ flex: 1, fontFamily: "var(--font-sans)", fontSize: 14, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.text}</span>
                <IconButton label="Move up" size="sm" disabled={i === 0} onClick={() => composer.move(i, -1)}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="18 15 12 9 6 15" /></svg>
                </IconButton>
                <IconButton label="Move down" size="sm" disabled={i === composer.items.length - 1} onClick={() => composer.move(i, 1)}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="6 9 12 15 18 9" /></svg>
                </IconButton>
                <label title="gap after clip (ms)" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
                  <input type="number" min={0} max={5000} step={50} value={c.gapMs}
                    onChange={(e) => { c.gapMs = Math.max(0, parseInt(e.target.value || "0", 10)); force(); }}
                    style={{ width: 58, background: "var(--surface-input)", color: "var(--text-secondary)", border: "1px solid var(--border-input)", borderRadius: "var(--radius-sm)", padding: "3px 6px", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }} />
                  ms
                </label>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>{fmtDur(c.buffer.duration)}</span>
                <IconButton label="Remove" size="sm" onClick={() => composer.remove(i)}><Trash size={15} /></IconButton>
              </div>
            ))}
            {composer.items.length === 0 && (
              <div style={{ padding: 40, textAlign: "center", border: "1px dashed var(--border-input)", borderRadius: "var(--radius-lg)", color: "var(--text-disabled)", fontFamily: "var(--font-sans)", fontSize: 14 }}>
                Add clips from the library to build your track.
              </div>
            )}
          </div>
        </div>

        {/* Export bar */}
        <div style={{ borderTop: "1px solid var(--border-default)", background: "var(--n-900)", padding: "16px 28px", display: "flex", alignItems: "center", gap: 16 }}>
          <div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>Total length</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 20, color: "var(--text-primary)" }}>{fmtDur(total)}</div>
          </div>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", cursor: "pointer" }}>
            <input type="checkbox" checked={composer.crossfade}
              onChange={(e) => { composer.crossfade = e.target.checked; force(); }}
              style={{ accentColor: "var(--roo-red)" }} />
            crossfade
          </label>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
            <Badge variant="neutral">WAV · 24kHz</Badge>
            <Button variant="secondary" onClick={preview} disabled={!composer.items.length}>Preview</Button>
            <Button variant="primary" leftIcon={<Download size={16} />} onClick={exportWav} disabled={!composer.items.length}>Export audio</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function composerCount(): number {
  return composer.items.length;
}
