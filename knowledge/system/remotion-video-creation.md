---
created: '2026-02-26'
scope: system
tags: video, remotion, animation, react, media, capabilities, design
title: Remotion Video Creation Capability
updated: '2026-03-11'
---

# Remotion Video Creation

## Overview

EloPhanto can create, edit, and render videos programmatically using Remotion — a React-based
video creation framework. Outputs MP4 to `/tmp/elophanto/<project-name>/out/video.mp4`.

---

## Design System — Premium Dark-Theme Videos

**Always use this design system.** Do not default to generic blue. These are production values
derived from Vercel/Geist, GitHub Unwrapped, and Linear — the gold standard for 2025 dark video.

### Color Palette

```
Background (primary):   #0A0A0A   — deepest layer, never pure black
Background (cards):     #111111   — panels, slides, card surfaces
Background (elevated):  #171717   — tooltips, highlighted sections
Border (default):       1px solid #292929
Border (subtle):        1px solid rgba(255,255,255,0.08)

Text (primary):         #EDEDED
Text (secondary):       #A1A1A1
Text (muted):           #737373
```

**Pick ONE hero accent per video** — use it on CTAs, highlights, and glow spots only:

| Accent | Hex | Mood |
|--------|-----|------|
| Violet (default) | `#8B5CF6` | Modern SaaS, AI, creative tech |
| Cyan | `#06B6D4` | Clean, technical, data |
| Blue | `#0070F3` | Professional, enterprise |
| Emerald | `#10B981` | Growth, finance, health |
| Amber | `#F59E0B` | Energy, local business, construction |

### Glow Effect Recipe (the "Linear Look")

Every scene should have a subtle glow spot — it makes flat dark backgrounds feel alive:

```tsx
// Background glow — place at corner or center behind key element
const glowStyle = {
  position: 'absolute' as const,
  width: 600,
  height: 600,
  borderRadius: '50%',
  background: 'radial-gradient(circle, rgba(139,92,246,0.18) 0%, transparent 70%)',
  top: -100,
  right: -100,
  pointerEvents: 'none' as const,
};

// Glassmorphism card — for feature cards, stats, comparison boxes
const glassCard = {
  background: 'rgba(255,255,255,0.03)',
  border: '1px solid rgba(255,255,255,0.08)',
  backdropFilter: 'blur(6px)',
  borderRadius: 16,
  padding: 40,
};
```

### Background Gradients (use instead of flat black for hero/outro scenes)

```
Navy Depth (B2B):     linear-gradient(135deg, #141E30 0%, #243B55 100%)
Deep AI:              linear-gradient(135deg, #000428 0%, #004E92 100%)
Violet Night:         linear-gradient(135deg, #1a0533 0%, #0f0f1a 50%, #0a1628 100%)
Warm Dark (local biz):linear-gradient(135deg, #1a0a00 0%, #2d1500 50%, #1a0a00 100%)
```

---

## Typography

**Always use Geist Sans** — load it via CDN in `@font-face`. Inter is the fallback.

```tsx
// In Root.tsx or a global style, add to <style>:
const fontCss = `
  @font-face {
    font-family: 'Geist';
    src: url('https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/Geist-Regular.woff2') format('woff2');
    font-weight: 400;
  }
  @font-face {
    font-family: 'Geist';
    src: url('https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/Geist-Medium.woff2') format('woff2');
    font-weight: 500;
  }
  @font-face {
    font-family: 'Geist';
    src: url('https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/Geist-SemiBold.woff2') format('woff2');
    font-weight: 600;
  }
  @font-face {
    font-family: 'Geist';
    src: url('https://cdn.jsdelivr.net/npm/geist@1.3.0/dist/fonts/geist-sans/Geist-Bold.woff2') format('woff2');
    font-weight: 700;
  }
`;
```

**Font sizing scale:**

| Use | Size | Weight | Letter-spacing |
|-----|------|--------|----------------|
| Hero headline | 96–120px | 700 | -5px to -7px |
| Scene title | 64–80px | 600 | -3px to -4px |
| Section heading | 40–48px | 600 | -1.5px |
| Body / bullets | 28–32px | 400 | 0 |
| Labels / captions | 18–22px | 400–500 | 0 |

**Rule:** Negative letter-spacing on all headings — this is what separates premium from amateur.

---

## Animation Timing — The Most Important Section

### Slow down. People need time to read.

**Scene durations:**

| Scene type | Duration (frames @ 30fps) | Duration (seconds) |
|------------|--------------------------|-------------------|
| Title / intro | 90–120 | 3–4s |
| Feature/bullet slide (4 items) | 210–270 | 7–9s |
| Comparison / before-after | 240–300 | 8–10s |
| Stats / data slide | 180–240 | 6–8s |
| CTA / outro | 150–210 | 5–7s |
| **Default minimum per scene** | **150** | **5s** |

Crossfade transitions between scenes: 10–15 frames (0.33–0.5s).

### Spring Config

**Always use `spring()` with `damping: 200`** for professional, smooth motion:

```tsx
import { spring, useCurrentFrame, useVideoConfig } from 'remotion';

// In component:
const { fps } = useVideoConfig();
const frame = useCurrentFrame();

// Smooth entrance — no bounce
const progress = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 30 });

// Slight bounce — for emphasis
const pop = spring({ frame, fps, config: { damping: 12, stiffness: 200 } });
```

### Standard Animation Primitives

```tsx
import { interpolate, Easing } from 'remotion';

// Fade in with delay (delayFrames = frame number to start)
function fadeIn(frame: number, delayFrames = 0, durationFrames = 18): number {
  return interpolate(frame, [delayFrames, delayFrames + durationFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
}

// Slide up from below
function slideUp(frame: number, delayFrames = 0, px = 40): number {
  const progress = interpolate(frame, [delayFrames, delayFrames + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  return interpolate(progress, [0, 1], [px, 0]);
}
```

### Stagger Pattern for Lists/Cards

```tsx
// Stagger items by 0.5 seconds (15 frames) each
const items = ['Item 1', 'Item 2', 'Item 3', 'Item 4'];
const STAGGER = 15; // frames

items.map((item, i) => {
  const delayFrames = i * STAGGER;
  const opacity = fadeIn(frame, delayFrames);
  const y = slideUp(frame, delayFrames);
  return <div style={{ opacity, transform: `translateY(${y}px)` }}>{item}</div>;
});
```

---

## Scene Architecture (Copy-Paste Template)

### Slide Structure — Standard 4-Scene Video

```tsx
// Root.tsx
import { Composition } from 'remotion';
import { MyVideo } from './MyVideo';

export const Root = () => (
  <Composition
    id="MyVideo"
    component={MyVideo}
    durationInFrames={750}  // 25 seconds at 30fps
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{ businessName: 'Acme Corp' }}
  />
);
```

```tsx
// MyVideo.tsx — scene sequencing
import { AbsoluteFill, Sequence } from 'remotion';

export const MyVideo: React.FC<{ businessName: string }> = ({ businessName }) => (
  <AbsoluteFill style={{ backgroundColor: '#0A0A0A', fontFamily: 'Geist, Inter, system-ui' }}>
    {/* Scene 1: Intro — 4 seconds */}
    <Sequence from={0} durationInFrames={120}>
      <IntroScene businessName={businessName} />
    </Sequence>

    {/* Scene 2: Problems — 8 seconds */}
    <Sequence from={120} durationInFrames={240}>
      <ProblemsScene />
    </Sequence>

    {/* Scene 3: Solution — 8 seconds */}
    <Sequence from={360} durationInFrames={240}>
      <SolutionScene />
    </Sequence>

    {/* Scene 4: CTA — 5 seconds */}
    <Sequence from={600} durationInFrames={150}>
      <CtaScene businessName={businessName} />
    </Sequence>
  </AbsoluteFill>
);
```

### Reusable GlowBackground Component

```tsx
const GlowBackground: React.FC<{
  accentColor?: string;
  glowX?: number;
  glowY?: number;
}> = ({ accentColor = '#8B5CF6', glowX = -100, glowY = -100 }) => (
  <AbsoluteFill style={{ pointerEvents: 'none' }}>
    <div style={{
      position: 'absolute',
      width: 700,
      height: 700,
      borderRadius: '50%',
      background: `radial-gradient(circle, ${accentColor}30 0%, transparent 70%)`,
      top: glowY,
      left: glowX,
    }} />
  </AbsoluteFill>
);
```

### Glass Card Component

```tsx
const GlassCard: React.FC<React.PropsWithChildren<{ style?: React.CSSProperties }>> = ({
  children,
  style,
}) => (
  <div style={{
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 16,
    padding: 48,
    ...style,
  }}>
    {children}
  </div>
);
```

### Pulsing CTA Button

```tsx
const PulsingCTA: React.FC<{ label: string; accentColor?: string }> = ({
  label,
  accentColor = '#8B5CF6',
}) => {
  const frame = useCurrentFrame();
  const pulse = 1 + Math.sin(frame * 0.12) * 0.03;
  return (
    <div style={{
      padding: '28px 72px',
      background: accentColor,
      borderRadius: 12,
      fontSize: 42,
      fontWeight: 700,
      color: '#fff',
      letterSpacing: '-0.5px',
      transform: `scale(${pulse})`,
      boxShadow: `0 0 60px ${accentColor}60`,
    }}>
      {label}
    </div>
  );
};
```

---

## Workflow

1. Load `remotion-best-practices` skill before writing any code
2. Scaffold project: `mkdir -p /tmp/elophanto/<name> && cd /tmp/elophanto/<name> && npm init -y`
3. Install: `npm install remotion @remotion/cli @remotion/media react react-dom typescript @types/react`
4. Create `tsconfig.json`, `src/index.ts`, `src/Root.tsx`, `src/MyVideo.tsx`
5. Render: `npx remotion render src/index.ts <CompositionId> out/video.mp4 --timeout=120000`
6. Serve + screenshot: `python3 -m http.server 8080 &` then `browser_navigate http://localhost:8080/out/video.mp4`

---

## Dependencies

**Required:**
- `remotion`, `@remotion/cli`, `@remotion/media`, `react`, `react-dom`, `typescript`, `@types/react`

**Optional:**
- `@react-three/fiber`, `@react-three/drei` — 3D content
- `@remotion/lottie` — Lottie animations
- `@remotion/light-leaks` — cinematic light leak overlays
- `mapbox-gl` — animated maps

---

## Output Spec

- **Format:** MP4 (H.264)
- **Resolution:** 1920×1080 (widescreen) or 1080×1080 (square/social)
- **Frame rate:** 30 fps
- **Location:** `/tmp/elophanto/<project>/out/video.mp4`

---

## Quality Checklist

Before rendering, verify:
- [ ] Background is `#0A0A0A` or a gradient (not flat `#000` or `#0f172a`)
- [ ] Font is Geist or Inter (not system-ui fallback as primary)
- [ ] Headings have negative letter-spacing
- [ ] Each scene is ≥150 frames (5 seconds)
- [ ] At least one glow spot per scene
- [ ] Spring damping ≥ 100 (no wild bounce on text)
- [ ] Staggered entrance for all lists/cards (≥12 frame delay between items)
- [ ] Single hero accent color used consistently

---

## Use Cases

- Marketing video audits for local businesses
- SaaS product explainers
- LinkedIn/Twitter social content
- Data viz / infographic videos
- Map animations (Mapbox)
- 3D product animations (Three.js)
- Audiograms / podcast clips

---

## Test History

| Date | Video | Duration | Size | Notes |
|------|-------|----------|------|-------|
| 2026-02-26 | Bouncing ball | 10s | 956 KB | Spring physics, squash-stretch |
| 2026-03-11 | Blue-collar video audit | 15s | 2.5 MB | 4-scene audit for plumbing biz in Columbus OH |
