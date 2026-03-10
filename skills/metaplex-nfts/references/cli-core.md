# Core CLI Reference

Commands for creating and managing Core NFTs and collections via the `mplx` CLI.

> **Prerequisites**: Run Initial Setup from `./cli.md` first (RPC, keypair, SOL balance).

---

## Commands

```bash
# Core Assets
mplx core asset create --name <NAME> --uri <URI>
mplx core asset create --name <NAME> --uri <URI> --owner <ADDR>             # Mint to a different wallet — --owner works on all asset create variants
mplx core asset create --name <NAME> --uri <URI> --collection <ADDR>
mplx core asset create --files --image <PATH> --json <PATH>                 # From local files (uploads automatically) — may error on JSON upload; use manual upload workflow as fallback
mplx core asset fetch <ADDR>
mplx core asset update <ASSETID> --name <NAME>
mplx core asset update <ASSETID> --uri <URI>
mplx core asset update <ASSETID> --image <PATH>                             # Re-uploads image via Irys
mplx core asset update <ASSETID> --collectionId <ADDR>                      # Move to different collection
mplx core asset burn <ADDR>                                                    # Also: --collection <ADDR>, --list <file.json>
mplx core asset template                                                    # Generate template files

# Core Collections
mplx core collection create --name <NAME> --uri <URI>
mplx core collection create --name <NAME> --uri <URI> --pluginsFile <PATH>
mplx core collection fetch <ADDR>
mplx core collection template                                               # Generate template files
```

---

## Core Plugins

**Plugin file format** (for `--pluginsFile`):

```json
[{
  "type": "Royalties",
  "basisPoints": 500,
  "creators": [{"address": "<CREATOR_ADDRESS>", "percentage": 100}],
  "ruleSet": {"type": "None"}
}]
```

**Available Types:** `Royalties`, `FreezeDelegate`, `BurnDelegate`, `TransferDelegate`, `Attributes`, `ImmutableMetadata`, `PermanentFreezeDelegate`, `PermanentTransferDelegate`, `PermanentBurnDelegate`

**RuleSet Options:**
- `{"type": "None"}`
- `{"type": "ProgramAllowList", "programs": [...]}`
- `{"type": "ProgramDenyList", "programs": [...]}`

**Example - Collection with Royalties:**

```bash
# Create plugins.json
echo '[{
  "type": "Royalties",
  "basisPoints": 500,
  "creators": [{"address": "<CREATOR_ADDRESS>", "percentage": 100}],
  "ruleSet": {"type": "None"}
}]' > plugins.json

# Create collection with plugins
mplx core collection create \
  --name "My Collection" \
  --uri "https://gateway.irys.xyz/xxx" \
  --pluginsFile ./plugins.json
```

Note: `basisPoints: 500` = 5%. Creator percentages must total 100.

---

## Metadata Workflow

### Before Creating - Gather from User:
- Name
- Description (optional)
- Attributes (optional)
- Image file
- For collections: Ask if they want royalties

### Single NFT/Collection

```bash
# Option A: Local files (one step)
mplx core asset create --files --image ./image.png --json ./metadata.json

# Option B: Manual upload workflow
# 1. Upload image
mplx toolbox storage upload ./image.png
# Returns: https://gateway.irys.xyz/<IMAGE_HASH>

# 2. Create metadata JSON
echo '{
  "name": "My NFT",
  "description": "Description here",
  "image": "https://gateway.irys.xyz/<IMAGE_HASH>",
  "attributes": [{"trait_type": "Background", "value": "Blue"}]
}' > metadata.json

# 3. Upload metadata
mplx toolbox storage upload ./metadata.json
# Returns: https://gateway.irys.xyz/<META_HASH>

# 4. Create asset
mplx core asset create --name "My NFT" --uri "https://gateway.irys.xyz/<META_HASH>"
```

### Multiple NFTs (Batch)

```bash
# 1. Upload all images at once
mplx toolbox storage upload ./images --directory

# 2. Create all metadata files (ONE command)
echo '{"name": "NFT #1", "image": "<URI_1>", "description": "...", "attributes": [...]}' > meta/1.json && \
echo '{"name": "NFT #2", "image": "<URI_2>", "description": "...", "attributes": [...]}' > meta/2.json && \
echo '{"name": "NFT #3", "image": "<URI_3>", "description": "...", "attributes": [...]}' > meta/3.json

# 3. Upload all metadata at once
mplx toolbox storage upload ./meta --directory

# 4. Create all assets (ONE command)
mplx core asset create --name "NFT #1" --uri "<META_URI_1>" --collection <ADDR> && \
mplx core asset create --name "NFT #2" --uri "<META_URI_2>" --collection <ADDR> && \
mplx core asset create --name "NFT #3" --uri "<META_URI_3>" --collection <ADDR>
```
