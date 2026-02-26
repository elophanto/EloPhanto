---
name: remotion-best-practices
description: Best practices for Remotion - Video creation in React. Use when asked to create, render, or edit videos programmatically.
metadata:
  tags: remotion, video, react, animation, composition
---

## Triggers

- video
- remotion
- create video
- render video
- animated video
- promo video
- explainer video
- mp4
- video clip
- motion graphics
- video animation
- react video
- text animation video
- video with music
- video with captions
- subtitles video
- voiceover video
- 3d video
- chart animation
- video transition
- video editing
- video render

## EloPhanto Workflow

When asked to create a video, follow this sequence:

1. **Read rules**: Load the relevant rule files below based on the task:
   - Maps → `rules/maps.md`
   - 3D → `rules/3d.md`
   - Charts → `rules/charts.md`
   - Captions → `rules/subtitles.md`
   - Voiceover → `rules/voiceover.md`
   - Text animations → `rules/text-animations.md`
   - Transitions → `rules/transitions.md`
   - Audio → `rules/audio.md`
   - Animations → `rules/animations.md`
   - Timing → `rules/timing.md`

2. **Scaffold** (do NOT use `npx create-video` — it requires interactive prompts):
   ```bash
   mkdir -p /tmp/elophanto/<project-name>
   cd /tmp/elophanto/<project-name> && npm init -y
   cd /tmp/elophanto/<project-name> && npm install remotion @remotion/cli @remotion/media react react-dom typescript @types/react
   ```
   **CRITICAL**: Every shell_execute command MUST start with `cd /tmp/elophanto/<project-name> &&`.
   The shell does NOT persist working directory between calls.

3. **Create project files**:
   - `src/index.ts` — entry point with `registerRoot()`
   - `src/Root.tsx` — `<Composition>` definitions (id, fps, dimensions, duration)
   - `src/MyComposition.tsx` — your video component using `useCurrentFrame()`, `interpolate()`, etc.
   - `tsconfig.json` — TypeScript config

   Minimal entry point:
   ```typescript
   // src/index.ts
   import {registerRoot} from 'remotion';
   import {Root} from './Root';
   registerRoot(Root);
   ```

   Minimal root:
   ```typescript
   // src/Root.tsx
   import {Composition} from 'remotion';
   import {MyVideo} from './MyVideo';
   export const Root = () => (
     <Composition id="MyVideo" component={MyVideo}
       durationInFrames={300} fps={30} width={1920} height={1080} />
   );
   ```

4. **Build**: Write React components following Remotion patterns from the rules.
   Key APIs: `useCurrentFrame()`, `useVideoConfig()`, `interpolate()`, `spring()`,
   `<AbsoluteFill>`, `<Sequence>`, `<Series>`, `<Audio>`, `<Video>`, `<Img>`

5. **Render** (ALWAYS do this — never stop before rendering):
   ```bash
   cd /tmp/elophanto/<project-name> && npx remotion render src/index.ts <CompositionId> out/video.mp4 --timeout=60000
   ```
   Use `--timeout=120000` for complex videos. Always pass `timeout: 300` to shell_execute for renders.
   The `cd` is REQUIRED — without it, `npx remotion` will fail with "could not determine executable".

**IMPORTANT**: Do NOT stop after writing files. You MUST attempt the render step.
The user expects a rendered .mp4 file, not just source code.

For complex videos, use swarm_spawn to delegate the build to a coding agent.

## When to use

Use this skill whenever you are dealing with Remotion code or asked to create videos programmatically.

## Captions

When dealing with captions or subtitles, load the [./rules/subtitles.md](./rules/subtitles.md) file for more information.

## Using FFmpeg

For some video operations, such as trimming videos or detecting silence, FFmpeg should be used. Load the [./rules/ffmpeg.md](./rules/ffmpeg.md) file for more information.

## Audio visualization

When needing to visualize audio (spectrum bars, waveforms, bass-reactive effects), load the [./rules/audio-visualization.md](./rules/audio-visualization.md) file for more information.

## Sound effects

When needing to use sound effects, load the [./rules/sound-effects.md](./rules/sound-effects.md) file for more information.

## How to use

Read individual rule files for detailed explanations and code examples:

- [rules/3d.md](rules/3d.md) - 3D content in Remotion using Three.js and React Three Fiber
- [rules/animations.md](rules/animations.md) - Fundamental animation skills for Remotion
- [rules/assets.md](rules/assets.md) - Importing images, videos, audio, and fonts into Remotion
- [rules/audio.md](rules/audio.md) - Using audio and sound in Remotion - importing, trimming, volume, speed, pitch
- [rules/calculate-metadata.md](rules/calculate-metadata.md) - Dynamically set composition duration, dimensions, and props
- [rules/can-decode.md](rules/can-decode.md) - Check if a video can be decoded by the browser using Mediabunny
- [rules/charts.md](rules/charts.md) - Chart and data visualization patterns for Remotion (bar, pie, line, stock charts)
- [rules/compositions.md](rules/compositions.md) - Defining compositions, stills, folders, default props and dynamic metadata
- [rules/extract-frames.md](rules/extract-frames.md) - Extract frames from videos at specific timestamps using Mediabunny
- [rules/fonts.md](rules/fonts.md) - Loading Google Fonts and local fonts in Remotion
- [rules/get-audio-duration.md](rules/get-audio-duration.md) - Getting the duration of an audio file in seconds with Mediabunny
- [rules/get-video-dimensions.md](rules/get-video-dimensions.md) - Getting the width and height of a video file with Mediabunny
- [rules/get-video-duration.md](rules/get-video-duration.md) - Getting the duration of a video file in seconds with Mediabunny
- [rules/gifs.md](rules/gifs.md) - Displaying GIFs synchronized with Remotion's timeline
- [rules/images.md](rules/images.md) - Embedding images in Remotion using the Img component
- [rules/light-leaks.md](rules/light-leaks.md) - Light leak overlay effects using @remotion/light-leaks
- [rules/lottie.md](rules/lottie.md) - Embedding Lottie animations in Remotion
- [rules/measuring-dom-nodes.md](rules/measuring-dom-nodes.md) - Measuring DOM element dimensions in Remotion
- [rules/measuring-text.md](rules/measuring-text.md) - Measuring text dimensions, fitting text to containers, and checking overflow
- [rules/sequencing.md](rules/sequencing.md) - Sequencing patterns for Remotion - delay, trim, limit duration of items
- [rules/tailwind.md](rules/tailwind.md) - Using TailwindCSS in Remotion
- [rules/text-animations.md](rules/text-animations.md) - Typography and text animation patterns for Remotion
- [rules/timing.md](rules/timing.md) - Interpolation curves in Remotion - linear, easing, spring animations
- [rules/transitions.md](rules/transitions.md) - Scene transition patterns for Remotion
- [rules/transparent-videos.md](rules/transparent-videos.md) - Rendering out a video with transparency
- [rules/trimming.md](rules/trimming.md) - Trimming patterns for Remotion - cut the beginning or end of animations
- [rules/videos.md](rules/videos.md) - Embedding videos in Remotion - trimming, volume, speed, looping, pitch
- [rules/parameters.md](rules/parameters.md) - Make a video parametrizable by adding a Zod schema
- [rules/maps.md](rules/maps.md) - Add a map using Mapbox and animate it
- [rules/voiceover.md](rules/voiceover.md) - Adding AI-generated voiceover to Remotion compositions using ElevenLabs TTS
