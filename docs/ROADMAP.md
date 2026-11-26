# MangaForge Product & Architecture Roadmap

This document captures the architectural audit, identified creator pain points, and phased implementation plan for evolving MangaForge from a backend continuation pipeline into a visual, precision-controllable manga studio.

## Current Gaps Identified

1. **Under-visualized structured intelligence**: The backend already extracts chronological events, character co-occurrences, state transitions, 10-episode arc digests (`arc_summaries`), tiered world rules (`core_rules` / `discovered_rules`), foreshadowing clue progressions (`pits`), bounding-box crops, and branch DAGs—yet most of this data is only exposed in flat CRUD tables or raw JSON modals.
2. **Coarse generation granularity**: `GenerationStudio` only supports full-episode re-rendering, even though single-panel rendering (`render_panel`) and `ImageBackend.inpaint` exist underneath. One flawed panel forces regenerating the entire chapter.
3. **Static horizontal lettering**: `LayoutEngine` renders fixed horizontal speech boxes server-side, lacking traditional vertical CJK manga lettering (`竖排对白`), shout/whisper balloon variants, and interactive client-side bubble adjustment.
4. **Manual reference curation friction**: When auto-cropping grabs an awkward profile or cover frame, creators cannot visually drag a crop box on the original manga page to replace a character's reference image.
5. **Reasoning-model output truncation**: High-thinking multimodal models consume substantial reasoning tokens; omitting an explicit `OPENAI_MAX_TOKENS` budget risks truncating structured JSON output.

---

## Phased Implementation Plan

### Phase 1 — Reasoning-Model Hardening & Story Atlas / QA Backend
- Add `OPENAI_MAX_TOKENS` (default `16384`) to `Settings` and wire it across all structured and tool-calling LLM calls.
- Implement `GET /api/v1/projects/{project_id}/memory/graph` aggregating:
  - **Character Relationship & Co-Occurrence Graph** (nodes with cropped avatars, outfits, and state evolution timelines; weighted edges with shared scenes).
  - **Story Arc & Pit Swimlane Timeline** (10-episode arc blocks, foundational vs rolling world rules, pit lifecycle bars from introduction through clue nodes to resolution).
  - **Multiverse Branch DAG** (branches and forked episode lineage for visual Git-graph rendering).
- Implement `POST /api/v1/projects/{project_id}/memory/ask` ("Ask the Manga Bible"): grounded Q&A over Story Bible + Multi-Query RRF recall returning answers with clickable episode/page visual citations.

### Phase 2 — Precision Studio Backend (Single-Panel Re-Roll, Vertical CJK, Interactive Bubbles, CBZ/Webtoon, ComfyUI)
- **Single-Panel Re-Render & Candidate History**:
  - `POST /api/v1/generation/episodes/{episode_id}/panels/{panel_id}/rerender`
  - `POST /api/v1/generation/episodes/{episode_id}/panels/{panel_id}/select/{image_id}`
  - `POST /api/v1/generation/episodes/{episode_id}/panels/{panel_id}/inpaint`
- **LayoutEngine v2**:
  - Traditional **Vertical CJK Manga Typesetting** (`writing_mode: "vertical" | "horizontal"`) with vertical punctuation substitution (`「」`→`﹁﹂`, `……`→`⋮`, `——`→`│`).
  - Additional comic balloon shapes (`shout` spiky starburst, `whisper` dashed outline) and per-dialogue `custom_box` overrides from the interactive frontend canvas.
- **Export Ecosystem**: Extend `/export` to support `pdf`, `cbz` (standard comic archive), and `webtoon` (seamless vertical strip PNG).
- **Visual Page-to-Asset Crop**: `POST /api/v1/projects/assets/{asset_id}/crop-from-page` to crop any bounding box from an imported manga page directly into an asset's reference gallery.
- **Local ComfyUI Backend**: Implement `ComfyUIImageBackend` (`IMAGE_BACKEND=comfyui`) supporting custom workflow templates and reference image upload.

### Phase 3 — Visual Story Atlas & Interactive Studio Frontend
- **Project Detail — Story Atlas Tab**:
  - Interactive Character Co-Occurrence & Relationship Graph (SVG with cropped face avatars, hover focus, click-to-inspect character evolution & shared moments).
  - Story Arc & Pit Swimlane Timeline (horizontal swimlanes + tiered `core_rules` / `arc_summaries` cards).
  - Interactive Multiverse Branch DAG (visual tree with cover thumbnails and quick Fork/Diff actions).
  - "Ask the Manga Bible" interactive Q&A panel with clickable manga page citations.
- **Generation Studio Upgrades**:
  - `@Character` / `#Pit` quick-insert selector chips in Step 0 (`custom_instructions` boost).
  - Per-panel Re-Render modal, reference asset selector, candidate A/B switcher, and RenderAgent trace viewer in Step 2.
  - Interactive Drag-and-Drop Bubble Canvas + Vertical/Horizontal mode toggle + PDF/CBZ/Webtoon export in Step 3.
- **Episode Reader Upgrades**:
  - Right-to-Left (RTL) Double-Page Tankobon Reader toggle + Interactive drag-box "Crop to Asset Reference" tool on original pages.

### Phase 4 — Live Verification, Visual Showcase & Documentation
- Full `ruff`, `tsc --noEmit`, `vite build`, and expanded `pytest` verification.
- Capture live UI screenshots & vertical-lettered manga output against the real *Isekai Ojisan* dataset, and update `README.md` / `README.zh-CN.md`.

---

## Future Backlog (Post-v2)
- Character 3-view turnaround & expression sheet auto-generator (`kind="turnaround"`).
- Interactive "Choose-Your-Own-Manga" branching reader mode with live 1–3 page continuation.
- Motion Comic / Dubbed Shorts MP4 export (per-character TTS + Ken Burns camera pans + animated speech balloons).
- Pluggable `MangaSourceProvider` architecture for CBZ/PDF volume auto-splitting and additional web sources.
