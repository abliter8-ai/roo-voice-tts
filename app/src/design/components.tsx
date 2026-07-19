/* Roo Voice design-system components — ported 1:1 (JSX→TSX) from the Claude
 * Design project "Roo Voice TTS Design System" (be6ff667). One deliberate
 * extension: Waveform accepts real per-bar `heights` computed from decoded
 * audio, replacing the seeded placeholder bars when provided. */
import React from "react";

type CSS = React.CSSProperties;

/* ---------------- Badge ---------------- */
export function Badge({ variant = "neutral", size = "md", dot = false, children, style = {}, ...rest }: {
  variant?: "neutral" | "red" | "solid" | "outline"; size?: "sm" | "md"; dot?: boolean;
  children?: React.ReactNode; style?: CSS;
} & React.HTMLAttributes<HTMLSpanElement>) {
  const variants: Record<string, CSS> = {
    neutral: { background: "var(--n-800)", color: "var(--text-secondary)", border: "1px solid var(--border-default)" },
    red: { background: "var(--red-veil)", color: "var(--roo-red)", border: "1px solid var(--roo-red-muted)" },
    solid: { background: "var(--accent)", color: "var(--accent-fg)", border: "1px solid transparent" },
    outline: { background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border-input)" },
  };
  const v = variants[variant] || variants.neutral;
  const sizes: Record<string, CSS & { fontSize: number }> = {
    sm: { fontSize: 10, padding: "2px 7px", height: 18 },
    md: { fontSize: 11, padding: "3px 9px", height: 21 },
  };
  const s = sizes[size] || sizes.md;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5, height: s.height, padding: s.padding,
      borderRadius: "var(--radius-pill)", fontFamily: "var(--font-sans)", fontSize: s.fontSize,
      fontWeight: 500, letterSpacing: "var(--tracking-wide)", textTransform: "uppercase",
      lineHeight: 1, whiteSpace: "nowrap", ...v, ...style,
    }} {...rest}>
      {dot && <span style={{ width: 5, height: 5, borderRadius: 999, background: "currentColor" }} />}
      {children}
    </span>
  );
}

/* ---------------- Button ---------------- */
export function Button({ variant = "primary", size = "md", disabled = false, fullWidth = false,
  leftIcon = null, rightIcon = null, children, style = {}, ...rest }: {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger";
  size?: "sm" | "md" | "lg"; disabled?: boolean; fullWidth?: boolean;
  leftIcon?: React.ReactNode; rightIcon?: React.ReactNode; children?: React.ReactNode; style?: CSS;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const sizes: Record<string, { height: string; padding: string; fontSize: string; gap: string; radius: string }> = {
    sm: { height: "var(--control-sm)", padding: "0 12px", fontSize: "13px", gap: "6px", radius: "var(--radius-sm)" },
    md: { height: "var(--control-md)", padding: "0 16px", fontSize: "14px", gap: "8px", radius: "var(--radius-md)" },
    lg: { height: "var(--control-lg)", padding: "0 22px", fontSize: "15px", gap: "8px", radius: "var(--radius-md)" },
  };
  const s = sizes[size] || sizes.md;
  const variants: Record<string, CSS> = {
    primary: { background: "var(--accent)", color: "var(--accent-fg)", border: "1px solid transparent", boxShadow: "0 1px 0 rgba(255,255,255,0.08) inset" },
    secondary: { background: "var(--surface-active)", color: "var(--text-primary)", border: "1px solid var(--border-default)" },
    outline: { background: "transparent", color: "var(--text-primary)", border: "1px solid var(--border-input)" },
    ghost: { background: "transparent", color: "var(--text-secondary)", border: "1px solid transparent" },
    danger: { background: "transparent", color: "var(--roo-red)", border: "1px solid var(--roo-red-muted)" },
  };
  const v = variants[variant] || variants.primary;
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);
  const hoverStyle: CSS = !disabled && hover ? ({
    primary: { background: active ? "var(--accent-press)" : "var(--accent-hover)" },
    secondary: { background: "var(--surface-input)", borderColor: "var(--border-strong)" },
    outline: { background: "var(--surface-hover)", borderColor: "var(--border-strong)" },
    ghost: { background: "var(--surface-hover)", color: "var(--text-primary)" },
    danger: { background: "var(--red-veil)", borderColor: "var(--roo-red)" },
  } as Record<string, CSS>)[variant] : {};
  return (
    <button disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setActive(false); }}
      onMouseDown={() => setActive(true)} onMouseUp={() => setActive(false)}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        gap: s.gap, height: s.height, padding: s.padding, borderRadius: s.radius,
        fontFamily: "var(--font-sans)", fontSize: s.fontSize, fontWeight: 500,
        letterSpacing: "-0.005em", lineHeight: 1, whiteSpace: "nowrap",
        width: fullWidth ? "100%" : "auto",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
        transform: active && !disabled ? "scale(0.98)" : "scale(1)",
        transition: "var(--transition-colors), transform var(--dur-fast) var(--ease-out)",
        ...v, ...hoverStyle, ...style,
      }} {...rest}>
      {leftIcon && <span style={{ display: "inline-flex", width: "1em", height: "1em" }}>{leftIcon}</span>}
      {children}
      {rightIcon && <span style={{ display: "inline-flex", width: "1em", height: "1em" }}>{rightIcon}</span>}
    </button>
  );
}

/* ---------------- IconButton ---------------- */
export function IconButton({ variant = "ghost", size = "md", disabled = false, active = false,
  label, children, style = {}, ...rest }: {
  variant?: "ghost" | "surface" | "accent"; size?: "sm" | "md" | "lg"; disabled?: boolean;
  active?: boolean; label?: string; children?: React.ReactNode; style?: CSS;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const dim = ({ sm: 28, md: 34, lg: 40 } as Record<string, number>)[size] || 34;
  const icon = ({ sm: 15, md: 17, lg: 19 } as Record<string, number>)[size] || 17;
  const variants: Record<string, CSS> = {
    ghost: { background: "transparent", color: "var(--text-muted)", border: "1px solid transparent" },
    surface: { background: "var(--surface-input)", color: "var(--text-secondary)", border: "1px solid var(--border-default)" },
    accent: { background: "var(--accent)", color: "var(--accent-fg)", border: "1px solid transparent" },
  };
  const v = variants[variant] || variants.ghost;
  const [hover, setHover] = React.useState(false);
  const hoverStyle: CSS = !disabled && hover ? ({
    ghost: { background: "var(--surface-hover)", color: "var(--text-primary)" },
    surface: { background: "var(--surface-active)", color: "var(--text-primary)" },
    accent: { background: "var(--accent-hover)" },
  } as Record<string, CSS>)[variant] : {};
  const activeStyle: CSS = active ? { background: "var(--red-veil)", color: "var(--roo-red)" } : {};
  return (
    <button aria-label={label} title={label} disabled={disabled}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: dim, height: dim, borderRadius: "var(--radius-md)",
        cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1,
        transition: "var(--transition-colors)", flexShrink: 0,
        ...v, ...hoverStyle, ...activeStyle, ...style,
      }} {...rest}>
      <span style={{ display: "inline-flex", width: icon, height: icon }}>{children}</span>
    </button>
  );
}

/* ---------------- Card ---------------- */
export function Card({ title, subtitle, header, footer, padding = 20, interactive = false,
  glow = false, children, style = {}, ...rest }: {
  title?: React.ReactNode; subtitle?: React.ReactNode; header?: React.ReactNode; footer?: React.ReactNode;
  padding?: number; interactive?: boolean; glow?: boolean; children?: React.ReactNode; style?: CSS;
} & React.HTMLAttributes<HTMLDivElement>) {
  const [hover, setHover] = React.useState(false);
  return (
    <div
      onMouseEnter={() => interactive && setHover(true)}
      onMouseLeave={() => interactive && setHover(false)}
      style={{
        background: "var(--surface-card)",
        border: `1px solid ${hover ? "var(--border-strong)" : "var(--border-default)"}`,
        borderRadius: "var(--radius-lg)",
        boxShadow: glow ? "var(--shadow-red)" : "var(--shadow-md)",
        overflow: "hidden", transition: "var(--transition-colors)",
        cursor: interactive ? "pointer" : "default", ...style,
      }} {...rest}>
      {(title || subtitle || header) && (
        <div style={{ padding: `${padding}px ${padding}px 0` }}>
          {header || (<>
            {title && <div style={{ fontFamily: "var(--font-sans)", fontSize: 20, fontWeight: 600, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>{title}</div>}
            {subtitle && <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, color: "var(--text-muted)", marginTop: 4, lineHeight: "var(--lh-snug)" }}>{subtitle}</div>}
          </>)}
        </div>
      )}
      <div style={{ padding }}>{children}</div>
      {footer && <div style={{ padding: `0 ${padding}px ${padding}px` }}>{footer}</div>}
    </div>
  );
}

/* ---------------- Input ---------------- */
export function Input({ size = "md", disabled = false, invalid = false, leftIcon = null,
  rightSlot = null, style = {}, ...rest }: {
  size?: "sm" | "md" | "lg"; disabled?: boolean; invalid?: boolean;
  leftIcon?: React.ReactNode; rightSlot?: React.ReactNode; style?: CSS;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">) {
  const heights: Record<string, string> = { sm: "var(--control-sm)", md: "var(--control-md)", lg: "var(--control-lg)" };
  const [focus, setFocus] = React.useState(false);
  return (
    <div style={{ position: "relative", display: "flex", alignItems: "center", width: "100%" }}>
      {leftIcon && (
        <span style={{ position: "absolute", left: 12, width: 16, height: 16, color: "var(--text-muted)", display: "inline-flex", pointerEvents: "none" }}>{leftIcon}</span>
      )}
      <input disabled={disabled}
        onFocus={(e) => { setFocus(true); rest.onFocus?.(e); }}
        onBlur={(e) => { setFocus(false); rest.onBlur?.(e); }}
        style={{
          width: "100%", height: heights[size] || heights.md,
          padding: leftIcon ? "0 14px 0 36px" : "0 14px",
          paddingRight: rightSlot ? 44 : 14,
          background: "var(--surface-input)",
          border: `1px solid ${invalid ? "var(--roo-red)" : focus ? "var(--border-strong)" : "var(--border-input)"}`,
          borderRadius: "var(--radius-md)",
          color: "var(--text-primary)", fontFamily: "var(--font-sans)", fontSize: "14px",
          outline: "none",
          boxShadow: focus ? (invalid ? "0 0 0 3px var(--red-veil)" : "0 0 0 3px rgba(255,255,255,0.06)") : "none",
          transition: "var(--transition-colors)",
          opacity: disabled ? 0.5 : 1, cursor: disabled ? "not-allowed" : "text",
          ...style,
        }} {...rest} />
      {rightSlot && <span style={{ position: "absolute", right: 8, display: "inline-flex" }}>{rightSlot}</span>}
    </div>
  );
}

/* ---------------- Textarea ---------------- */
export function Textarea({ placeholder = "Jot down some thoughts…", rows = 4, disabled = false,
  value, defaultValue, onChange, style = {}, ...rest }: {
  placeholder?: string; rows?: number; disabled?: boolean; value?: string; defaultValue?: string;
  onChange?: React.ChangeEventHandler<HTMLTextAreaElement>; style?: CSS;
} & React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const [focus, setFocus] = React.useState(false);
  return (
    <div style={{ position: "relative", width: "100%" }}>
      <textarea rows={rows} placeholder={placeholder} disabled={disabled}
        value={value} defaultValue={defaultValue} onChange={onChange}
        onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        style={{
          width: "100%", resize: "none", display: "block",
          padding: "18px 52px 18px 20px",
          minHeight: rows * 26 + 36,
          background: "var(--surface-card)",
          border: `1px solid ${focus ? "var(--border-strong)" : "var(--border-input)"}`,
          borderRadius: "var(--radius-lg)",
          color: "var(--text-primary)", fontFamily: "var(--font-sans)",
          fontSize: "16px", lineHeight: "var(--lh-normal)",
          outline: "none",
          boxShadow: focus ? "0 0 0 3px rgba(255,255,255,0.05)" : "none",
          transition: "var(--transition-colors)",
          opacity: disabled ? 0.5 : 1,
          ...style,
        }} {...rest} />
    </div>
  );
}

/* ---------------- SidebarNav ---------------- */
export interface SideNavItem { value: string; label: string; icon?: React.ReactNode; trailing?: React.ReactNode; }
export function SidebarNav({ items = [], value, defaultValue, onChange, header, footer, style = {} }: {
  items: SideNavItem[]; value?: string; defaultValue?: string; onChange?: (v: string) => void;
  header?: React.ReactNode; footer?: React.ReactNode; style?: CSS;
}) {
  const first = defaultValue ?? items[0]?.value;
  const [internal, setInternal] = React.useState(first);
  const active = value != null ? value : internal;
  const select = (v: string) => { if (value == null) setInternal(v); onChange?.(v); };
  return (
    <nav style={{
      display: "flex", flexDirection: "column", width: "var(--sidebar-w)", height: "100%",
      background: "var(--n-900)", borderRight: "1px solid var(--border-default)", flexShrink: 0, ...style,
    }}>
      {header && <div style={{ padding: "20px 18px" }}>{header}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "4px 12px", flex: 1 }}>
        {items.map((it) => <SideItem key={it.value} item={it} active={it.value === active} onClick={() => select(it.value)} />)}
      </div>
      {footer && <div style={{ padding: 12, borderTop: "1px solid var(--border-subtle)" }}>{footer}</div>}
    </nav>
  );
}
function SideItem({ item, active, onClick }: { item: SideNavItem; active: boolean; onClick: () => void }) {
  const [hover, setHover] = React.useState(false);
  return (
    <button type="button" onClick={onClick}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "9px 12px",
        background: active ? "var(--red-veil)" : hover ? "var(--surface-hover)" : "transparent",
        color: active ? "var(--roo-red)" : hover ? "var(--text-primary)" : "var(--text-secondary)",
        border: "none", borderRadius: "var(--radius-md)", cursor: "pointer",
        fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 500,
        textAlign: "left", transition: "var(--transition-colors)",
      }}>
      {item.icon && <span style={{ display: "inline-flex", width: 18, height: 18, flexShrink: 0 }}>{item.icon}</span>}
      <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
      {item.trailing}
    </button>
  );
}

/* ---------------- Waveform ---------------- */
function placeholderHeights(count: number, seed = 7): number[] {
  const out: number[] = [];
  let s = seed;
  for (let i = 0; i < count; i++) {
    s = (s * 9301 + 49297) % 233280;
    const r = s / 233280;
    const env = Math.sin((i / count) * Math.PI);
    out.push(0.18 + (0.35 + r * 0.65) * env);
  }
  return out;
}
export function Waveform({ bars = 64, progress = 0, playing = false, height = 72,
  color = "var(--n-500)", playedColor = "var(--roo-red)", seed = 7, heights, style = {}, ...rest }: {
  bars?: number; progress?: number; playing?: boolean; height?: number;
  color?: string; playedColor?: string; seed?: number;
  /** Real per-bar amplitudes (0..1) from decoded audio; overrides the seeded bars. */
  heights?: number[]; style?: CSS;
} & React.HTMLAttributes<HTMLDivElement>) {
  const hs = React.useMemo(
    () => heights && heights.length ? heights : placeholderHeights(bars, seed),
    [heights, bars, seed]);
  const n = hs.length;
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setTick((t) => t + 1), 120);
    return () => clearInterval(id);
  }, [playing]);
  const playedIdx = Math.round(progress * n);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 3, height, width: "100%", ...style }} {...rest}>
      {hs.map((h, i) => {
        const isPlayed = i < playedIdx;
        const jitter = playing && Math.abs(i - playedIdx) < 6 ? (Math.sin(tick + i) * 0.12) : 0;
        return (
          <span key={i} style={{
            flex: 1, minWidth: 2, maxWidth: 5,
            height: `${Math.min(1, Math.max(0.06, h + jitter)) * 100}%`,
            borderRadius: 999, background: isPlayed ? playedColor : color,
            transition: "height 120ms linear, background-color var(--dur-base) var(--ease-out)",
          }} />
        );
      })}
    </div>
  );
}

/* ---------------- PlayButton ---------------- */
export function PlayButton({ playing = false, size = 56, variant = "accent", onClick, label, style = {}, ...rest }: {
  playing?: boolean; size?: number; variant?: "accent" | "surface"; onClick?: () => void; label?: string; style?: CSS;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick">) {
  const [hover, setHover] = React.useState(false);
  const variants: Record<string, CSS> = {
    accent: { background: hover ? "var(--accent-hover)" : "var(--accent)", color: "var(--accent-fg)", border: "none" },
    surface: { background: hover ? "var(--surface-active)" : "var(--surface-input)", color: "var(--text-primary)", border: "1px solid var(--border-default)" },
  };
  const v = variants[variant] || variants.accent;
  const ico = Math.round(size * 0.36);
  return (
    <button type="button" aria-label={label || (playing ? "Pause" : "Play")} onClick={onClick}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: size, height: size, borderRadius: 999, cursor: "pointer", flexShrink: 0,
        boxShadow: variant === "accent" ? (hover ? "var(--glow-red-sm)" : "var(--shadow-md)") : "none",
        transition: "var(--transition-colors), transform var(--dur-fast) var(--ease-out)",
        transform: hover ? "scale(1.03)" : "scale(1)", ...v, ...style,
      }} {...rest}>
      {playing ? (
        <svg width={ico} height={ico} viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
      ) : (
        <svg width={ico} height={ico} viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.53.85l10-6.5a1 1 0 0 0 0-1.7l-10-6.5A1 1 0 0 0 8 5.5Z" /></svg>
      )}
    </button>
  );
}

/* ---------------- Avatar ---------------- */
import headshot from "../assets/roo-headshot.png";
export function Avatar({ src = headshot, size = 48, ring = false, speaking = false, alt = "Roo", style = {}, ...rest }: {
  src?: string; size?: number; ring?: boolean; speaking?: boolean; alt?: string; style?: CSS;
} & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span style={{ position: "relative", display: "inline-flex", flexShrink: 0, ...style }} {...rest}>
      {speaking && (
        <span style={{
          position: "absolute", inset: -4, borderRadius: 999, border: "2px solid var(--roo-red)",
          animation: "rooPulse 1.6s var(--ease-in-out) infinite",
        }} />
      )}
      <img src={src} alt={alt} width={size} height={size}
        style={{
          width: size, height: size, borderRadius: 999, objectFit: "cover", objectPosition: "50% 30%",
          display: "block", background: "var(--n-850)",
          border: ring || speaking ? "2px solid var(--roo-red)" : "2px solid var(--border-strong)",
          boxShadow: speaking ? "var(--glow-red-sm)" : "none",
        }} />
    </span>
  );
}

/* ---------------- ClipCard ---------------- */
export function ClipCard({ title = "Untitled clip", duration = "0:12", text, playing = false, progress = 0,
  selected = false, onToggle, seed = 3, heights, style = {}, ...rest }: {
  title?: string; duration?: string; text?: string; playing?: boolean; progress?: number;
  selected?: boolean; onToggle?: () => void; seed?: number; heights?: number[]; style?: CSS;
} & React.HTMLAttributes<HTMLDivElement>) {
  const [hover, setHover] = React.useState(false);
  return (
    <div onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{
        display: "flex", alignItems: "center", gap: 16, padding: 14,
        background: selected ? "var(--red-veil)" : "var(--surface-card)",
        border: `1px solid ${selected ? "var(--roo-red-muted)" : hover ? "var(--border-strong)" : "var(--border-default)"}`,
        borderRadius: "var(--radius-md)", transition: "var(--transition-colors)", ...style,
      }} {...rest}>
      <PlayButton playing={playing} size={40} variant={selected || playing ? "accent" : "surface"} onClick={onToggle} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
          <span style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 500, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{title}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)", flexShrink: 0 }}>{duration}</span>
        </div>
        {text && <div style={{ fontFamily: "var(--font-sans)", fontSize: 12, color: "var(--text-muted)", marginBottom: 8, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{text}</div>}
        <Waveform bars={44} height={28} progress={playing ? progress : 0} playing={playing} seed={seed} heights={heights} color="var(--n-600)" />
      </div>
    </div>
  );
}
