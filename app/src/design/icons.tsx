// Roo Voice icon set — ported 1:1 from the design system's icons.jsx
// (thin 2px line icons, Lucide-style).
import React from "react";

interface IconProps {
  size?: number;
  sw?: number;
  style?: React.CSSProperties;
}

const I = (paths: React.ReactNode, opts: { fill?: boolean } = {}) =>
  (props: IconProps = {}) => (
    <svg width={props.size || 20} height={props.size || 20} viewBox="0 0 24 24"
      fill={opts.fill ? "currentColor" : "none"}
      stroke={opts.fill ? "none" : "currentColor"} strokeWidth={props.sw || 2}
      strokeLinecap="round" strokeLinejoin="round"
      style={{ display: "block", ...props.style }}>{paths}</svg>
  );

export const Wave = I(<><path d="M2 12h2.5l2-7 3.5 15 3-11 2 6H22" /></>);
export const Ear = I(<><path d="M6 8.5a6 6 0 0 1 12 0c0 3.5-2.5 4.5-2.5 7.5a3.5 3.5 0 0 1-7 0" /><path d="M9 9a3 3 0 0 1 5 2" /></>);
export const Layers = I(<><path d="m12 2 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5" /><path d="m3 17 9 5 9-5" /></>);
export const Mic = I(<><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="22" /></>);
export const Settings = I(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" /></>);
export const Plus = I(<><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></>);
export const Download = I(<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></>);
export const Lock = I(<><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>);
export const Sparkle = I(<><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="M12 7c1 3 2 4 5 5-3 1-4 2-5 5-1-3-2-4-5-5 3-1 4-2 5-5Z" /></>);
export const Play = I(<path d="M8 5v14l11-7z" />, { fill: true });
export const Trash = I(<><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></>);
export const Clock = I(<><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" /></>);
export const Copy = I(<><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>);
export const Chevron = I(<polyline points="9 18 15 12 9 6" />);
export const GripV = I(<><circle cx="9" cy="6" r="1" /><circle cx="9" cy="12" r="1" /><circle cx="9" cy="18" r="1" /><circle cx="15" cy="6" r="1" /><circle cx="15" cy="12" r="1" /><circle cx="15" cy="18" r="1" /></>);
export const SkipBack = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5a1 1 0 0 1 2 0v5.2l9.5-5.5A1 1 0 0 1 19 5.5v13a1 1 0 0 1-1.5.9L8 13.8V19a1 1 0 0 1-2 0Z" /></svg>
);
