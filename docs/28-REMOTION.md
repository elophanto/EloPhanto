# 28 — Remotion (Video Creation)

EloPhanto can create videos programmatically using [Remotion](https://remotion.dev),
a React-based framework that renders real MP4 videos from code.

## How It Works

When a user asks to create a video, the skill system automatically recommends
the `remotion-best-practices` skill. The agent reads Remotion's best practices
and 37 rule files covering animations, 3D, maps, charts, captions, voiceover,
and more — then scaffolds, builds, and renders the video.

```
User: "Create a video of a travel route on a map with 3D landmarks"

Agent flow:
1. skill_read("remotion-best-practices")  → loads main SKILL.md
2. Reads rules/maps.md, rules/3d.md, rules/animations.md
3. mkdir project → npm init → npm install remotion @remotion/cli @remotion/media
4. Creates src/index.ts, src/Root.tsx, src/TravelRoute.tsx
5. Writes React components (map animation, 3D landmarks, transitions)
6. npx remotion render src/index.ts TravelRoute out/travel-video.mp4
```

> **Note**: The agent uses manual project setup (npm init + npm install) instead of
> `npx create-video` because create-video requires interactive prompts that cannot
> run in a non-interactive shell.

## Skill Structure

```
skills/remotion-best-practices/
├── SKILL.md                         ← main skill (triggers + workflow + rule index)
└── rules/                           ← 37 detailed guides
    ├── 3d.md                        ← Three.js and React Three Fiber
    ├── animations.md                ← Fundamental animation patterns
    ├── assets.md                    ← Importing images, videos, audio, fonts
    ├── audio.md                     ← Audio: trimming, volume, speed, pitch
    ├── audio-visualization.md       ← Spectrum bars, waveforms, bass-reactive
    ├── calculate-metadata.md        ← Dynamic duration, dimensions, props
    ├── charts.md                    ← Bar, pie, line, stock chart animations
    ├── compositions.md              ← Defining compositions and stills
    ├── display-captions.md          ← Rendering captions on video
    ├── fonts.md                     ← Google Fonts and local fonts
    ├── images.md                    ← Embedding images
    ├── light-leaks.md               ← Light leak overlay effects
    ├── lottie.md                    ← Lottie animations
    ├── maps.md                      ← Mapbox maps with animation
    ├── parameters.md                ← Parameterizable videos with Zod
    ├── sequencing.md                ← Delay, trim, sequence patterns
    ├── subtitles.md                 ← Captions and subtitle rendering
    ├── tailwind.md                  ← TailwindCSS in Remotion
    ├── text-animations.md           ← Typography animation patterns
    ├── timing.md                    ← Interpolation: linear, easing, spring
    ├── transitions.md               ← Scene transition patterns
    ├── transparent-videos.md        ← Rendering with transparency
    ├── trimming.md                  ← Cut beginning or end of animations
    ├── videos.md                    ← Embedding videos: trim, loop, speed
    ├── voiceover.md                 ← AI voiceover via ElevenLabs TTS
    └── ... (37 files total)
```

## Triggers

The skill matches queries containing: video, remotion, mp4, render video,
animated video, promo video, motion graphics, voiceover, subtitles, chart
animation, 3d video, text animation, etc.

## Using with Swarm

For complex video projects, the agent can delegate to a swarm coding agent:

```
User: "Create a product launch promo video with my logo and music"

Agent:
1. Reads remotion-best-practices skill
2. swarm_spawn(task="Create Remotion video: product launch promo with logo
   overlay, music track, text animations, and transitions. Render to MP4.")
3. Swarm agent works in isolated branch, creates PR when done
```

## Prerequisites

- **Node.js 22+** (already available for EloPhanto's browser bridge)
- **Chrome/Chromium** (used by Remotion's renderer — already available)
- No additional setup needed — the agent scaffolds via `npm init` + `npm install`

## Example Queries

| User says | Agent does |
|-----------|-----------|
| "Create a video for my product" | Scaffold + build promo video with text/images |
| "Make an animated chart of sales data" | Load charts.md, build animated data viz |
| "Video with travel route on map" | Load maps.md + 3d.md, animate Mapbox route |
| "Add captions to my video" | Load subtitles.md, render with captions |
| "Create a video with voiceover" | Load voiceover.md, integrate ElevenLabs TTS |
| "Make a text animation intro" | Load text-animations.md + timing.md |

## Attribution

Remotion skill rules sourced from [remotion-dev/remotion](https://github.com/remotion-dev/remotion)
(MIT License). The rules are Remotion's official AI agent guides.
