/** GenerateScreen — the design's compose view wired to the real engine.
 *
 * Deviation from the design kit (recorded in IP-179): the Speed/Pitch/
 * Intensity sliders are omitted — the shipped model is deterministic
 * (greedy, temp 0) and has no such parameters; dead controls would lie.
 * The Voice card shows the real model facts instead.
 */
import React from "react";
import { Textarea, Input, Button, Card, Badge, Waveform } from "../design/components";
import { Sparkle } from "../design/icons";
import { generate, fetchProgress, HealthState } from "../engine";

export function GenerateScreen({ health, onGenerated }: {
  health: HealthState;
  onGenerated: (id: string) => void;
}) {
  const [text, setText] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [chunkInfo, setChunkInfo] = React.useState("");
  const ready = health.status === "ready";

  const go = async () => {
    if (!text.trim() || busy || !ready) return;
    setBusy(true);
    setError("");
    const poll = window.setInterval(async () => {
      try {
        const p = await fetchProgress();
        if (p.phase === "generating" && p.chunks > 1) setChunkInfo(`${p.chunk}/${p.chunks}`);
      } catch { /* engine busy */ }
    }, 350);
    try {
      const r = await generate(text.trim(), title.trim() || undefined);
      setText("");
      setTitle("");
      onGenerated(r.id);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      window.clearInterval(poll);
      setChunkInfo("");
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "40px 40px 64px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ fontFamily: "var(--font-display)", fontSize: 52, letterSpacing: ".02em", color: "var(--white)", margin: 0, lineHeight: 0.95, textTransform: "uppercase", fontWeight: 400 }}>
          Tell me what to say
        </h1>
      </div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 30, letterSpacing: ".03em", color: "var(--roo-red)", lineHeight: 0.95, textTransform: "uppercase", fontWeight: 400, margin: "6px 0 10px" }}>
        …and I'll tell you what to do
      </div>
      <p style={{ fontFamily: "var(--font-sans)", fontSize: 15, color: "var(--text-muted)", margin: "0 0 28px", maxWidth: 520, lineHeight: 1.55 }}>
        Jot it down and I'll speak it. Everything is computed right here on your machine — nothing leaves your device.
      </p>

      <div style={{ marginBottom: 16 }}>
        <Textarea placeholder="Jot down some thoughts…" rows={5} value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") go(); }} />
      </div>
      <div style={{ marginBottom: 24 }}>
        <Input placeholder="Give this idea a title…" value={title} maxLength={120}
          onChange={(e) => setTitle((e.target as HTMLInputElement).value)} />
      </div>

      <Card padding={22} style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--text-muted)" }}>Voice</span>
          <Badge variant="neutral">Roo · fine-tuned</Badge>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 28 }}>
          <VoiceFact label="Model" value={health.model?.replace(/\.gguf$/, "") || "—"} />
          <VoiceFact label="Decoding" value="Greedy · deterministic" />
          <VoiceFact label="Output" value="24 kHz WAV" />
        </div>
      </Card>

      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <Button size="lg" onClick={go} disabled={busy || !text.trim() || !ready} leftIcon={<Sparkle size={17} />}>
          {busy ? (chunkInfo ? `Generating ${chunkInfo}…` : "Generating…") : ready ? "Generate speech" : "Engine starting…"}
        </Button>
        {busy && (
          <div style={{ flex: 1, maxWidth: 260, opacity: 0.8 }}>
            <Waveform bars={48} height={30} playing progress={0.5} />
          </div>
        )}
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-disabled)" }}>⌘↵ to generate</span>
      </div>
      {error && (
        <div style={{ marginTop: 16, padding: "12px 14px", borderRadius: "var(--radius-md)", background: "var(--red-veil)", border: "1px solid var(--roo-red-muted)", color: "var(--roo-red)", fontFamily: "var(--font-mono)", fontSize: 12, wordBreak: "break-word" }}>
          {error}
        </div>
      )}
    </div>
  );
}

function VoiceFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontFamily: "var(--font-sans)", fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--text-secondary)" }}>{value}</div>
    </div>
  );
}
