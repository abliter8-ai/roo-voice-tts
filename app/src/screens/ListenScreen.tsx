/** ListenScreen — the design's immersive playback moment, wired to real audio.
 * Sonar rings are CSS (the design's gif asset, recreated); the waveform shows
 * REAL peaks from the decoded clip; transport is the shared player. */
import React from "react";
import { PlayButton, IconButton, Badge, Avatar, Waveform } from "../design/components";
import { Download, SkipBack } from "../design/icons";
import { HistEntry, player, getPeaks, fmtDur, saveClip } from "../engine";

export function ListenScreen({ clip }: { clip: HistEntry | null }) {
  const [playing, setPlaying] = React.useState(player.playing && player.clipId === clip?.id);
  const [progress, setProgress] = React.useState(0);
  const [peaks, setPeaks] = React.useState<number[] | undefined>(undefined);

  React.useEffect(() => {
    if (!clip) return;
    setPeaks(undefined);
    getPeaks(clip.id, 96).then(setPeaks).catch(() => setPeaks(undefined));
  }, [clip?.id]);

  React.useEffect(() => player.onProgress((p, isPlaying) => {
    if (player.clipId === clip?.id) {
      setProgress(p);
      setPlaying(isPlaying);
    } else {
      setPlaying(false);
    }
  }), [clip?.id]);

  if (!clip) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100%", padding: 48 }}>
        <Avatar size={116} />
        <h2 style={{ fontFamily: "var(--font-display)", fontSize: 34, color: "var(--white)", margin: "22px 0 6px", textTransform: "uppercase", fontWeight: 400 }}>Nothing here yet</h2>
        <p style={{ fontFamily: "var(--font-sans)", fontSize: 15, color: "var(--text-muted)" }}>Generate something and I'll say it out loud.</p>
      </div>
    );
  }

  const title = clip.title || (clip.text.length > 34 ? clip.text.slice(0, 34) + "…" : clip.text);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100%", padding: "48px 40px", position: "relative" }}>
      {/* Sonar presence — CSS rings recreate the design's sonar gif */}
      <div style={{ position: "relative", width: 220, height: 220, marginBottom: 32, display: "grid", placeItems: "center" }}>
        {[0, 1, 2].map((i) => (
          <span key={i} style={{
            position: "absolute", inset: 0, borderRadius: 999,
            border: "1.5px solid var(--roo-red)",
            opacity: playing ? undefined : 0.15,
            animation: playing ? `rooSonar 2.4s linear ${i * 0.8}s infinite` : "none",
            transform: playing ? undefined : `scale(${0.55 + i * 0.18})`,
          }} />
        ))}
        <Avatar size={116} speaking={playing} />
      </div>

      <Badge variant="red" dot={playing}>{playing ? "Speaking" : "Ready"}</Badge>
      <h2 style={{ fontFamily: "var(--font-display)", fontSize: 34, letterSpacing: ".02em", color: "var(--white)", margin: "16px 0 6px", textTransform: "uppercase", textAlign: "center", fontWeight: 400 }}>{title}</h2>
      <p style={{ fontFamily: "var(--font-sans)", fontSize: 16, color: "var(--text-secondary)", maxWidth: 520, textAlign: "center", lineHeight: 1.6, margin: "0 0 36px", textWrap: "pretty" } as React.CSSProperties}>
        “{clip.text}”
      </p>

      {/* Transport */}
      <div style={{ width: "100%", maxWidth: 620 }}>
        <div style={{ marginBottom: 14 }}>
          <Waveform bars={96} height={64} progress={progress} playing={playing} heights={peaks} />
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>{fmtDur(progress * clip.duration_s)}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>{fmtDur(clip.duration_s)}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 22 }}>
          <IconButton label="Restart" variant="ghost" size="lg" onClick={() => player.play(clip.id)}><SkipBack /></IconButton>
          <PlayButton playing={playing} size={64} onClick={() => player.toggle(clip.id)} />
          <IconButton label="Save clip" variant="ghost" size="lg"
            onClick={() => saveClip(clip.id, `${title.replace(/[^\w -]+/g, "").trim() || "roo-clip"}.wav`)}>
            <Download size={19} />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
