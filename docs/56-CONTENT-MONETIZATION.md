# 56 — Content Monetization

Two tool groups that turn EloPhanto into a revenue-generating agent:
**Publishing** (content → platform) and **Affiliate Marketing** (product → pitch → post).

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   Content Monetization                    │
├──────────────────────┬───────────────────────────────────┤
│   Publishing Tools   │      Affiliate Tools              │
│                      │                                   │
│  youtube_upload      │  affiliate_scrape                 │
│  twitter_post        │  affiliate_pitch                  │
│  tiktok_upload       │  affiliate_campaign               │
└──────────┬───────────┴────────────┬──────────────────────┘
           │                        │
    Browser Bridge           Browser Bridge + LLM
    (pre-auth Chrome)        (scrape + generate)
           │                        │
    ┌──────┴──────┐          ┌──────┴──────┐
    │  YouTube    │          │   Amazon    │
    │  X / Twitter│          │   Product   │
    │  TikTok    │          │   Pages     │
    └─────────────┘          └─────────────┘
```

## Publishing Tools

All publishing tools use the existing browser bridge with pre-authenticated
Chrome profiles. No Selenium dependency — everything goes through our
Node.js bridge (JSON-RPC).

### `youtube_upload`

Upload a video file to YouTube (Shorts or regular).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_path` | string | yes | Local path to MP4/WebM file |
| `title` | string | yes | Video title (max 100 chars) |
| `description` | string | no | Video description |
| `visibility` | string | no | `public`, `unlisted`, `private` (default: `unlisted`) |
| `is_short` | boolean | no | Mark as YouTube Short (default: false) |
| `tags` | array | no | Video tags for SEO |

**Flow**: Navigate to YouTube Studio → Upload → Fill metadata → Set visibility → Extract video URL.

### `twitter_post`

Post text and/or media to X (Twitter).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | yes | Tweet text (max 280 chars) |
| `media_path` | string | no | Local path to image/video to attach |
| `reply_to_url` | string | no | URL of tweet to reply to |

**Flow**: Navigate to compose → Type content → Attach media → Post → Extract tweet URL.

### `tiktok_upload`

Upload a short video to TikTok.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file_path` | string | yes | Local path to MP4 file |
| `caption` | string | yes | Video caption (max 2200 chars) |
| `tags` | array | no | Hashtags (without #) |
| `visibility` | string | no | `public`, `friends`, `private` (default: `public`) |

**Flow**: Navigate to TikTok upload → Select file → Add caption/tags → Post → Extract URL.

## Affiliate Marketing Tools

### `affiliate_scrape`

Scrape product information from e-commerce platforms.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | yes | Product page URL (Amazon, etc.) |
| `extract_fields` | array | no | Fields to extract (default: all) |

**Returns**: title, price, rating, features, image_urls, asin/product_id.

### `affiliate_pitch`

Generate a marketing pitch for a product using LLM.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `product_data` | object | yes | Product data from `affiliate_scrape` |
| `platform` | string | yes | Target platform (`twitter`, `tiktok`, `youtube`) |
| `tone` | string | no | `casual`, `professional`, `enthusiastic` (default: `casual`) |
| `affiliate_link` | string | no | Affiliate URL to include |
| `max_length` | integer | no | Character limit (default: platform limit) |

**Returns**: Generated pitch text, suggested hashtags, call-to-action.

### `affiliate_campaign`

Create and track an affiliate marketing campaign.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | string | yes | `create`, `status`, `list` |
| `product_url` | string | create | Product page URL |
| `affiliate_link` | string | create | Your affiliate link |
| `platforms` | array | create | Platforms to target |
| `campaign_id` | string | status | Campaign ID to check |

**Flow (create)**: Scrape product → Generate pitches per platform → Post to each → Track in DB.

## Database Tables

### `publishing_log`

Tracks every piece of content published to external platforms.

```sql
CREATE TABLE IF NOT EXISTS publishing_log (
    publish_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,          -- youtube, twitter, tiktok
    content_type TEXT NOT NULL,      -- video, text, image
    title TEXT NOT NULL DEFAULT '',
    local_path TEXT,                 -- source file path
    platform_url TEXT,               -- URL on platform after publish
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, published, failed
    metadata_json TEXT DEFAULT '{}', -- platform-specific metadata
    campaign_id TEXT,                -- links to affiliate campaign
    created_at TEXT NOT NULL,
    published_at TEXT
)
```

### `affiliate_campaigns`

Tracks affiliate marketing campaigns and their performance.

```sql
CREATE TABLE IF NOT EXISTS affiliate_campaigns (
    campaign_id TEXT PRIMARY KEY,
    product_url TEXT NOT NULL,
    product_title TEXT NOT NULL DEFAULT '',
    product_data_json TEXT DEFAULT '{}',
    affiliate_link TEXT NOT NULL,
    platforms_json TEXT DEFAULT '[]', -- target platforms
    pitches_json TEXT DEFAULT '{}',   -- generated pitches per platform
    status TEXT NOT NULL DEFAULT 'active', -- active, paused, completed
    posts_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

## Combined Revenue Flows

### Autonomous YouTube Shorts Pipeline

```
Heartbeat trigger (daily) →
  1. Generate trending topic (LLM)
  2. Create video script + visuals (Remotion + Replicate)
  3. Render video (shell_execute: npx remotion render)
  4. youtube_upload(file_path, title, is_short=true)
  5. twitter_post(teaser + YouTube link)
```

### Affiliate Marketing Pipeline

```
Heartbeat trigger (weekly) →
  1. Browse trending products (browser bridge)
  2. affiliate_scrape(product_url)
  3. affiliate_pitch(product_data, platform="twitter")
  4. twitter_post(pitch + affiliate_link)
  5. Track in affiliate_campaigns table
```

### Cross-Platform Content Distribution

```
User: "Create a video about AI agents and post everywhere"
  1. Create video (Remotion)
  2. youtube_upload(video.mp4, title)
  3. tiktok_upload(video.mp4, caption)
  4. twitter_post(teaser + link)
  5. commune_post(summary)
```

## Configuration

No new config section needed. Publishing tools use:
- **Browser bridge** — already configured via `browser:` section
- **Chrome profiles** — pre-authenticated (user logs in once)
- **LLM router** — for pitch generation (via `_router`)
- **Database** — for tracking (via `_db`)

## Permission Levels

| Tool | Permission | Rationale |
|------|-----------|-----------|
| `youtube_upload` | DESTRUCTIVE | Publishes content publicly |
| `twitter_post` | DESTRUCTIVE | Publishes content publicly |
| `tiktok_upload` | DESTRUCTIVE | Publishes content publicly |
| `affiliate_scrape` | MODERATE | Reads external pages |
| `affiliate_pitch` | SAFE | LLM text generation only |
| `affiliate_campaign` | DESTRUCTIVE | Orchestrates publishing |

## Tool Group

All tools use group `"monetization"` for profile-based filtering.
