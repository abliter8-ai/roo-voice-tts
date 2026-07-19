/** Roo Voice v2 — app shell from the Claude Design kit (SidebarNav + titlebar
 * + Roo headshot underlay), wired to the real engine: live health in the
 * titlebar badge, real download progress strip, real history feeding the
 * screens. */
import React from "react";
import { SidebarNav, Badge } from "./design/components";
import { Wave, Ear, Layers, Settings, Lock } from "./design/icons";
import { GenerateScreen } from "./screens/GenerateScreen";
import { ListenScreen } from "./screens/ListenScreen";
import { StudioScreen, composerCount } from "./screens/StudioScreen";
import { connect, fetchHealth, listHistory, HealthState, HistEntry } from "./engine";
import appIcon from "./assets/app-icon.png";
import headshot from "./assets/roo-headshot.png";

type Mode = "gen" | "listen" | "studio";

export default function App() {
  const [mode, setMode] = React.useState<Mode>("gen");
  const [health, setHealth] = React.useState<HealthState>({ status: "connecting", detail: "" });
  const [clips, setClips] = React.useState<HistEntry[]>([]);
  const [currentId, setCurrentId] = React.useState<string | null>(null);

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
      <button style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 12px", background: "transparent", border: "none", borderRadius: "var(--radius-md)", color: "var(--text-secondary)", cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 500 }}>
        <span style={{ display: "inline-flex" }}><Settings size={17} /></span> Settings
      </button>
    </div>
  );

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
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
