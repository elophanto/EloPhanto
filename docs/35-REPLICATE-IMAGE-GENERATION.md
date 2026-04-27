# Replicate Image Generation

Generate AI images using Google's Nano Banana 2 model via the Replicate API.

## Setup

### 1. Get API Key

Visit https://replicate.com/account/api-tokens to create your API token.

### 2. Configure in `config.yaml`

```yaml
replicate:
  enabled: true
  api_key: "your_replicate_api_token_here"  # Your Replicate API token
  default_model: "google/nano-banana-2"
  default_resolution: "1024"  # 512, 1024, 2048, 4096
  default_aspect_ratio: "1:1"  # 1:1, 16:9, 9:16, 4:3, 3:4
  default_format: "jpg"  # jpg, png
  default_output_mode: "local"  # url, local (recommended: Replicate deletes URL content after ~12 hours)
```

### 3. Restart Agent

Restart EloPhanto for config changes to take effect.

## Usage

### Tool: `replicate_generate`

Generate AI images using Google's Nano Banana 2 model via Replicate API.

### Parameters

| Parameter | Type | Required | Default | Options |
|-----------|------|-----------|-----------|----------|
| prompt | string | Yes | - | Text description of image |
| resolution | string | No | 1024 | 512, 1024, 2048, 4096 |
| aspect_ratio | string | No | 1:1 | 1:1, 16:9, 9:16, 4:3, 3:4 |
| output_format | string | No | jpg | jpg, png |
| output_mode | string | No | local | url, local |
| filename | string | No | generated.jpg | Required when output_mode="local" |

### Examples

Generate a polo player image:

```
replicate_generate(
  prompt="Professional polo player on a beautiful green field in Sotogrande, Spain. Bright sunny day, blue sky.",
  aspect_ratio="16:9",
  resolution="1024",
  output_mode="url"
)
```

Generate a beach ride and save locally:

```
replicate_generate(
  prompt="Andalusian horse walking on a pristine beach at golden sunset in Sotogrande. Warm golden light, peaceful atmosphere.",
  aspect_ratio="16:9",
  resolution="1024",
  output_format="jpg",
  output_mode="local",
  filename="beach-ride.jpg"
)
```

## Pricing (Nano Banana 2)

| Resolution | Cost per image | Images per $1 |
|------------|----------------|---------------|
| 512px | ~$0.03 | ~33 images |
| 1024px | ~$0.067 | ~14 images |
| 2048px | ~$0.101 | ~10 images |
| 4096px | ~$0.151 | ~7 images |

## Output Modes

### `local` (Recommended)
- Downloads image to `<agent.workspace>/generated_images/` (the workspace
  configured under the `agent:` block in `config.yaml`; falls back to
  `<project_root>/workspace/generated_images/` if unset).
- Images persist permanently on your machine.
- **Returns absolute paths** — `data["path"]` and `data["absolute_path"]`
  are both the resolved absolute filesystem path. Pass either directly to
  `browser_upload_file` / `browser_file_chooser` — no CWD juggling needed.
- **Auto-registers in the knowledge base** — every successful local save
  also writes a metadata stub to `knowledge/learned/images/{date}-{slug}.md`
  containing the prompt, model, dimensions, absolute path, and Replicate
  URL. Future calls to `knowledge_search` ("the meeting avatar from
  yesterday", "the moonscape with a bee") will surface these naturally,
  letting the agent reuse old assets instead of regenerating them.
- Recommended for production use.

### `url` (Temporary)
- Returns a public URL to the generated image.
- **Important**: Replicate deletes URL content after ~12 hours. The tool
  returns `data["url_expires_in_hours"] = 12` as a reminder.
- Use for quick testing, previews, or uploads to platforms that ingest
  remote URLs. For long-lived assets always prefer `local`.

## Tool Result Shape

`output_mode: "local"` returns:
```json
{
  "path": "/Users/you/agent-ws/generated_images/foo.jpg",
  "absolute_path": "/Users/you/agent-ws/generated_images/foo.jpg",
  "url": "https://replicate.delivery/...",
  "url_expires_in_hours": 12
}
```

`output_mode: "url"` returns:
```json
{
  "url": "https://replicate.delivery/..."
}
```

## Prompt Tips

For best results with Nano Banana 2:

- **Be specific**: Include subjects, style, lighting, mood, and composition
- **Mention location**: "Sotogrande, Spain", "Mediterranean coast", "Andalusia"
- **Set the mood**: "peaceful", "energetic", "luxurious", "cinematic"
- **Add technical details**: "golden hour", "wide shot", "close-up", "photorealistic"

Good examples:
- ✅ "Andalusian horse on a beach at golden sunset in Sotogrande, Spain. Warm golden light, peaceful Mediterranean atmosphere."
- ✅ "Professional polo player swinging mallet on a pristine green field in Sotogrande. Bright sunny day, blue sky, white uniform."
- ✅ "Wide shot of Sotogrande coastline with polo field in foreground, Mediterranean blue sea in background. Luxury tourism vibe."

## Permissions

Permission level: `moderate`

## Troubleshooting

### API Key Not Found
- Ensure `api_key` is set in `config.yaml`
- Restart the agent after updating config

### Images Not Saving
- Check `<agent.workspace>/generated_images/` exists (the plugin creates
  it automatically; if creation fails check parent-dir permissions)
- Verify write permissions on the configured workspace
- Ensure `output_mode="local"` is set
- If `agent.workspace` isn't configured in `config.yaml`, files land at
  `<project_root>/workspace/generated_images/` instead — check there

### Browser Can't Find the File
The plugin returns absolute paths so this should be rare, but if you see
"file not found" when calling `browser_upload_file` after a generation:
- Confirm the path you're passing matches `data["absolute_path"]` from the
  `replicate_generate` result, not `data["path"]` — they're the same value
  but using `absolute_path` makes the intent explicit
- Check the browser bridge process has read access to the workspace dir
  (it should — same user, same machine)

### Poor Image Quality
- Try higher resolution (1024 or 2048)
- Refine your prompt with more specific details
- Adjust aspect ratio to match your needs
