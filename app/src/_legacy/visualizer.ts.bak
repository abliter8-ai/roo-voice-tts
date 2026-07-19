/** Aura-style live visualizer (IP-178 centerpiece).
 *
 * Own GLSL — LiveKit's Aura is the STYLE reference only. A radial energy field
 * in brand red (#FF093A) with three states:
 *   idle       slow breathing glow
 *   generating rotating conic sweep, noise agitated
 *   speaking   radius + shimmer driven by live playback analysis (RMS + bands)
 * Falls back to a 2D radial-bar renderer when WebGL2 is unavailable.
 */

export type VizState = "idle" | "generating" | "speaking";

const FRAG = `#version 300 es
precision highp float;
out vec4 frag;
uniform vec2 u_res;
uniform float u_time;
uniform float u_state;    // 0 idle, 1 generating, 2 speaking
uniform float u_level;    // smoothed RMS 0..1
uniform vec3 u_bands;     // low / mid / high 0..1

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x),
             mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * noise(p);
    p = p * 2.03 + 11.7;
    a *= 0.5;
  }
  return v;
}

void main() {
  vec2 p = (gl_FragCoord.xy * 2.0 - u_res) / min(u_res.x, u_res.y);
  float r = length(p);
  float ang = atan(p.y, p.x);

  float idle = 1.0 - smoothstep(0.0, 1.0, abs(u_state - 0.0));
  float gen  = 1.0 - smoothstep(0.0, 1.0, abs(u_state - 1.0));
  float spk  = 1.0 - smoothstep(0.0, 1.0, abs(u_state - 2.0));

  // breathing base radius; speaking pushes it with the live level
  float breathe = 0.02 * sin(u_time * 1.4);
  float ring = 0.52 + breathe + spk * (u_level * 0.16 + u_bands.x * 0.05);

  // fbm displacement around the ring — more agitated while generating/speaking.
  // Noise is sampled on the unit-circle embedding (cos,sin) so there is no seam
  // at the atan wrap.
  float agitation = 0.5 + gen * 1.6 + spk * (0.8 + u_bands.z * 1.4);
  vec2 circ = vec2(cos(ang), sin(ang)) * 1.45;
  float n = fbm(circ + vec2(u_time * 0.22, u_time * (0.3 + 0.22 * agitation)));
  float wobble = (n - 0.5) * (0.05 + 0.06 * agitation);
  float d = abs(r - (ring + wobble));

  // core energy band
  float band = exp(-d * d * 380.0);
  // inner glow filling the disc
  float glow = exp(-r * r * 2.4) * (0.22 + spk * u_level * 0.7 + gen * 0.12);
  // generating: rotating conic sweep
  float sweep = gen * pow(max(0.0, 0.5 + 0.5 * cos(ang - u_time * 2.6)), 6.0)
                * exp(-abs(r - ring) * 9.0) * 0.9;
  // speaking: high-band shimmer spokes
  float spokes = spk * u_bands.y * pow(abs(sin(ang * 9.0 + u_time * 3.0)), 8.0)
                 * exp(-d * 26.0) * 0.5;

  float e = band * (0.85 + 0.35 * sin(u_time * 0.9)) + glow + sweep + spokes;
  e *= (0.85 + idle * 0.0 + gen * 0.25 + spk * 0.45);

  vec3 red = vec3(1.0, 0.035, 0.227);            // #FF093A
  vec3 col = red * e + vec3(1.0) * band * 0.22 * (spk * u_level + gen * 0.3);

  // soft circular vignette so the canvas edge never shows
  col *= smoothstep(1.05, 0.85, r);
  frag = vec4(col, 1.0);
}`;

const VERT = `#version 300 es
void main() {
  vec2 v = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(v * 2.0 - 1.0, 0.0, 1.0);
}`;

export class Visualizer {
  private canvas: HTMLCanvasElement;
  private gl: WebGL2RenderingContext | null = null;
  private ctx2d: CanvasRenderingContext2D | null = null;
  private uniforms: Record<string, WebGLUniformLocation | null> = {};
  private analyser: AnalyserNode | null = null;
  private freq = new Uint8Array(0);
  private wave = new Uint8Array(0);
  private state: VizState = "idle";
  private stateF = 0;
  private level = 0;
  private bands: [number, number, number] = [0, 0, 0];
  private t0 = performance.now();

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2");
    if (gl) {
      this.gl = gl;
      const prog = gl.createProgram()!;
      for (const [type, src] of [[gl.VERTEX_SHADER, VERT], [gl.FRAGMENT_SHADER, FRAG]] as const) {
        const sh = gl.createShader(type)!;
        gl.shaderSource(sh, src);
        gl.compileShader(sh);
        if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
          console.error("shader:", gl.getShaderInfoLog(sh));
          this.gl = null;
          break;
        }
        gl.attachShader(prog, sh);
      }
      if (this.gl) {
        gl.linkProgram(prog);
        gl.useProgram(prog);
        for (const u of ["u_res", "u_time", "u_state", "u_level", "u_bands"]) {
          this.uniforms[u] = gl.getUniformLocation(prog, u);
        }
      }
    }
    if (!this.gl) this.ctx2d = canvas.getContext("2d");
    requestAnimationFrame(() => this.frame());
  }

  setState(s: VizState) { this.state = s; }

  attachAnalyser(a: AnalyserNode | null) {
    this.analyser = a;
    if (a) {
      this.freq = new Uint8Array(a.frequencyBinCount);
      this.wave = new Uint8Array(a.fftSize);
    }
  }

  private analyse() {
    if (!this.analyser) {
      this.level += (0 - this.level) * 0.08;
      return;
    }
    this.analyser.getByteTimeDomainData(this.wave);
    this.analyser.getByteFrequencyData(this.freq);
    let sum = 0;
    for (let i = 0; i < this.wave.length; i++) {
      const v = (this.wave[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.min(1, Math.sqrt(sum / this.wave.length) * 3.2);
    this.level += (rms - this.level) * 0.25;
    // 24k content, analyser nyquist depends on context rate; use proportional bins
    const n = this.freq.length;
    const seg = (a: number, b: number) => {
      let s = 0;
      const i0 = Math.floor(a * n), i1 = Math.max(i0 + 1, Math.floor(b * n));
      for (let i = i0; i < i1; i++) s += this.freq[i];
      return Math.min(1, s / ((i1 - i0) * 200));
    };
    const target: [number, number, number] = [seg(0, 0.05), seg(0.05, 0.25), seg(0.25, 0.7)];
    for (let i = 0; i < 3; i++) this.bands[i] += (target[i] - this.bands[i]) * 0.3;
  }

  private frame() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.floor(this.canvas.clientWidth * dpr);
    const h = Math.floor(this.canvas.clientHeight * dpr);
    if (w && h && (this.canvas.width !== w || this.canvas.height !== h)) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.analyse();
    const targetF = this.state === "idle" ? 0 : this.state === "generating" ? 1 : 2;
    this.stateF += (targetF - this.stateF) * 0.08;
    const t = (performance.now() - this.t0) / 1000;

    if (this.gl) {
      const gl = this.gl;
      gl.viewport(0, 0, w, h);
      gl.uniform2f(this.uniforms.u_res, w, h);
      gl.uniform1f(this.uniforms.u_time, t);
      gl.uniform1f(this.uniforms.u_state, this.stateF);
      gl.uniform1f(this.uniforms.u_level, this.level);
      gl.uniform3f(this.uniforms.u_bands, ...this.bands);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    } else if (this.ctx2d) {
      this.fallback2d(this.ctx2d, w, h, t);
    }
    requestAnimationFrame(() => this.frame());
  }

  private fallback2d(c: CanvasRenderingContext2D, w: number, h: number, t: number) {
    c.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) * (0.26 + 0.05 * this.level);
    const bars = 96;
    c.strokeStyle = "#FF093A";
    c.lineWidth = Math.max(2, w / 300);
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2 + (this.state === "generating" ? t * 1.4 : 0);
      const amp = this.state === "speaking"
        ? this.level * 0.6 + this.bands[1] * 0.4
        : this.state === "generating" ? 0.25 + 0.15 * Math.sin(t * 3 + i) : 0.1 + 0.05 * Math.sin(t + i);
      const len = base * 0.18 + base * amp * (0.4 + 0.6 * Math.abs(Math.sin(i * 1.7 + t)));
      c.globalAlpha = 0.35 + 0.65 * amp;
      c.beginPath();
      c.moveTo(cx + Math.cos(a) * base, cy + Math.sin(a) * base);
      c.lineTo(cx + Math.cos(a) * (base + len), cy + Math.sin(a) * (base + len));
      c.stroke();
    }
    c.globalAlpha = 1;
  }
}
