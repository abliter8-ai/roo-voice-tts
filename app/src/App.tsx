/** Roo Voice v2 — app shell from the Claude Design kit (SidebarNav + titlebar
 * + Roo headshot underlay), wired to the real engine: live health in the
 * titlebar badge, real download progress strip, real history feeding the
 * screens. */
import React from "react";
import { SidebarNav, Badge, Button } from "./design/components";
import { Wave, Ear, Layers, Settings, Lock } from "./design/icons";
import { GenerateScreen } from "./screens/GenerateScreen";
import { ListenScreen } from "./screens/ListenScreen";
import { StudioScreen, composerCount } from "./screens/StudioScreen";
import { connect, fetchHealth, listHistory, saveDiagnostics, APP_VERSION, HealthState, HistEntry } from "./engine";
import appIcon from "./assets/app-icon.png";
import headshot from "./assets/roo-headshot.png";

type Mode = "gen" | "listen" | "studio";

export default function App() {
  const [mode, setMode] = React.useState<Mode>("gen");
  const [health, setHealth] = React.useState<HealthState>({ status: "connecting", detail: "" });
  const [clips, setClips] = React.useState<HistEntry[]>([]);
  const [currentId, setCurrentId] = React.useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      await connect();
      const refreshHistory = async () => {
        try { if (alive) setClips(await listHistory()); } catch { /* engine not up */ }
      };
      refreshHistory();
      const poll = async () => {
        const h = await fetchHealth();
        if (!alive) return;
        setHealth(h);
        setTimeout(poll, h.status === "ready" ? 3000 : 700);
      };
      poll();
      (window as any).__refreshHistory = refreshHistory;
    })();
    return () => { alive = false; };
  }, []);

  const onGenerated = async (id: string) => {
    setClips(await listHistory());
    setCurrentId(id);
    setMode("listen");
  };

  const current = clips.find((c) => c.id === currentId) ?? clips[0] ?? null;
  const studioCount = composerCount();

  const nav = [
    { value: "gen", label: "Generate", icon: <Wave /> },
    { value: "listen", label: "Listen", icon: <Ear /> },
    { value: "studio", label: "Studio", icon: <Layers />, trailing: studioCount ? <Badge variant="red" size="sm">{studioCount}</Badge> : null },
  ];

  const brand = (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <img src={appIcon} alt="" style={{ width: 38, height: 38, borderRadius: 10 }} />
      <div style={{ lineHeight: 1 }}>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 24, letterSpacing: ".03em", color: "var(--white)" }}>
          ROO<span style={{ color: "var(--roo-red)" }}>·</span>VOICE
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, color: "var(--text-muted)", letterSpacing: ".1em", marginTop: 3 }}>TTS v2.0</div>
      </div>
    </div>
  );

  const footer = (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderRadius: "var(--radius-md)", background: "var(--red-veil)", border: "1px solid var(--roo-red-muted)" }}>
        <span style={{ color: "var(--roo-red)", display: "inline-flex" }}><Lock size={14} /></span>
        <span style={{ fontFamily: "var(--font-sans)", fontSize: 12, color: "var(--text-secondary)" }}>On device · Private</span>
      </div>
      <button onClick={() => setSettingsOpen(true)}
        style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 12px", background: settingsOpen ? "var(--surface-hover)" : "transparent", border: "none", borderRadius: "var(--radius-md)", color: settingsOpen ? "var(--text-primary)" : "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 500 }}>
        <span style={{ display: "inline-flex" }}><Settings size={17} /></span> Settings
      </button>
    </div>
  );

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {settingsOpen && <SettingsPanel health={health} onClose={() => setSettingsOpen(false)} />}
      <SidebarNav items={nav} value={mode} onChange={(v) => setMode(v as Mode)} header={brand} footer={footer} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--n-950)", position: "relative" }}>
        {/* Roo watches — faint headshot underlay */}
        <img src={headshot} alt="" style={{
          position: "absolute", top: 0, right: 0, height: "100%", width: "auto", maxWidth: "90%",
          objectFit: "cover", objectPosition: "right 32%", opacity: 1, pointerEvents: "none",
          WebkitMaskImage: "linear-gradient(to left, rgba(0,0,0,1) 4%, rgba(0,0,0,0) 90%)",
          maskImage: "linear-gradient(to left, rgba(0,0,0,1) 4%, rgba(0,0,0,0) 90%)",
        }} />
        {/* titlebar */}
        <div style={{ height: 44, flexShrink: 0, borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", padding: "0 20px", gap: 14, position: "relative", zIndex: 1 }}>
          <div style={{ display: "flex", gap: 7 }}>
            <span style={{ width: 11, height: 11, borderRadius: 999, background: "var(--n-700)" }} />
            <span style={{ width: 11, height: 11, borderRadius: 999, background: "var(--n-700)" }} />
            <span style={{ width: 11, height: 11, borderRadius: 999, background: "var(--roo-red)" }} />
          </div>
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--text-muted)", marginLeft: 6 }}>
            {({ gen: "Generate", listen: "Listen", studio: "Studio" } as Record<Mode, string>)[mode]}
          </span>
          <div style={{ marginLeft: "auto" }}><HealthBadge health={health} /></div>
        </div>
        {/* download progress strip (honest bytes — first launch) */}
        {health.status === "downloading" && health.download?.total && (
          <div style={{ height: 3, flexShrink: 0, background: "var(--n-800)", position: "relative", zIndex: 1 }}>
            <div style={{ height: "100%", width: `${(100 * health.download.got) / health.download.total}%`, background: "var(--roo-red)", boxShadow: "var(--glow-red-sm)", transition: "width .3s" }} />
          </div>
        )}
        {/* screen */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", position: "relative", zIndex: 1 }}>
          {mode === "gen" && <GenerateScreen health={health} onGenerated={onGenerated} />}
          {mode === "listen" && <ListenScreen clip={current} />}
          {mode === "studio" && <StudioScreen clips={clips} />}
        </div>
      </div>
    </div>
  );
}

function SettingsPanel({ health, onClose }: { health: HealthState; onClose: () => void }) {
  const [saved, setSaved] = React.useState(false);
  const row = (label: string, value: React.ReactNode) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "10px 0", borderBottom: "1px solid var(--border-subtle)" }}>
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-secondary)", textAlign: "right", wordBreak: "break-word" }}>{value}</span>
    </div>
  );
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 40, background: "rgba(0,0,0,0.55)", backdropFilter: "blur(3px)", display: "flex", justifyContent: "flex-end" }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width: "min(420px, 90vw)", height: "100%", background: "var(--n-900)", borderLeft: "1px solid var(--border-default)",
        boxShadow: "var(--shadow-lg)", padding: "22px 24px", overflowY: "auto", display: "flex", flexDirection: "column", gap: 4,
      }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontFamily: "var(--font-display)", fontSize: 26, letterSpacing: ".03em", color: "var(--white)", textTransform: "uppercase" }}>Settings</span>
          <button onClick={onClose} aria-label="Close" style={{ marginLeft: "auto", background: "transparent", border: "1px solid var(--border-default)", borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", width: 28, height: 28, cursor: "pointer" }}>✕</button>
        </div>

        <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--text-muted)", margin: "12px 0 2px" }}>Engine</div>
        {row("Status", <Badge variant={health.status === "ready" ? "neutral" : "outline"} dot={health.status === "ready"}>{health.status}</Badge>)}
        {row("App version", APP_VERSION)}
        {row("Engine version", health.version || "—")}
        {row("Model", health.model?.replace(/\.gguf$/, "") || "—")}
        {row("Decoding", "Greedy · deterministic (temp 0)")}
        {row("Output", "24 kHz mono WAV")}

        <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--text-muted)", margin: "18px 0 2px" }}>Privacy</div>
        <p style={{ fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.55, margin: "6px 0" }}>
          Everything runs on this device. Your text and audio never leave the machine — the only network use is the one-time model download and update checks.
        </p>

        <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, letterSpacing: "var(--tracking-label)", textTransform: "uppercase", color: "var(--text-muted)", margin: "18px 0 8px" }}>Support</div>
        <Button variant="secondary" fullWidth onClick={async () => { await saveDiagnostics(); setSaved(true); setTimeout(() => setSaved(false), 2500); }}>
          {saved ? "Report saved ✓" : "Save diagnostics report"}
        </Button>
        <p style={{ fontFamily: "var(--font-sans)", fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5, margin: "8px 0 0" }}>
          A redacted JSON bundle (hardware, versions, timings, last error) to attach to a bug report.
        </p>

        <div style={{ marginTop: "auto", paddingTop: 20, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-disabled)", display: "flex", flexDirection: "column", gap: 6 }}>
          <a href="https://github.com/abliter8-ai/roo-voice-tts" target="_blank" rel="noreferrer">github.com/abliter8-ai/roo-voice-tts</a>
          <a href="https://huggingface.co/abliter8-ai/Roo-Voice-NeuTTS" target="_blank" rel="noreferrer">Voice model card</a>
        </div>
      </div>
    </div>
  );
}

function HealthBadge({ health }: { health: HealthState }) {
  const gb = (n: number) => (n / 1024 ** 3).toFixed(1);
  switch (health.status) {
    case "ready":
      return <Badge variant="neutral" dot>Model loaded · {health.model?.replace(/\.gguf$/, "") || "GGUF"}</Badge>;
    case "downloading":
      return <Badge variant="red" dot>Downloading {health.download ? `${gb(health.download.got)} / ${gb(health.download.total)} GB` : "model"}</Badge>;
    case "failed":
      return <Badge variant="red">Engine failed — see Generate</Badge>;
    case "connecting":
      return <Badge variant="outline">Connecting…</Badge>;
    default:
      return <Badge variant="outline" dot>{health.status}…</Badge>;
  }
}
