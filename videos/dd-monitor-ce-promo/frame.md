---
version: alpha
name: Cobalt Grid — Frame (video / frame layer)
description: >
  Video-first companion to Cobalt Grid's design.md. The unit is the frame (1920×1080). Atoms
  are identical and sacred — warm cream paper, electric cobalt ink (the only ink), the permanent
  graph-paper grid, Microsoft YaHei UI serif 400 + Microsoft YaHei UI + DM Mono, the top/bottom cobalt
  hairlines, and the pixel-glitch + QR-block signatures. Composition, frame scale, and
  aspect-ratio behavior are rewritten for the frame. Motion is out of scope.
unit: the frame — 1920×1080 primary; 9:16 and 1:1 documented
principle: atoms are sacred · composition is free · numbers come from the script

colors:
  # paper-2 手工修正：build-frame 把它判成了预设的 accent2 而塞进品牌粉 #fb7299，
  # 但 Cobalt Grid 的 doctrine 是「严格双色、无第二表面」，而 paper-2 是**地面族**的一档
  # （预设原值 #E6E0CE 是比 paper 深一档的米色），不是强调色。这里换成软件本体真实存在的
  # 表面令牌 CONTENT = #303338，既守住双色纪律，又让面板有真实依据。
  # B 站粉 #fb7299 不进设计系统 —— 它只在真实录屏里自然出现（直播徽标、弹幕点）。
  paper: "#222428"
  paper-2: "#303338"
  ink: "#f1f2f5"
  ink-soft: "#00a1d6"
  grid: "rgba(0, 161, 214, 0.10)"
  ink-faint: "rgba(0, 161, 214, 0.18)"

typography:
  # — reading ramp —
  body:        { fontFamily: "Microsoft YaHei UI", cqw: 0.83, weight: 400, lineHeight: 1.5 }
  body-lede:   { fontFamily: "Microsoft YaHei UI", cqw: 0.95, weight: 400, lineHeight: 1.5 }
  micro:       { fontFamily: "Microsoft YaHei UI", px: 13, weight: 600, tracking: "0.16em", upper: true }
  micro-strong:{ fontFamily: "Microsoft YaHei UI", px: 16, weight: 600, tracking: "0.18em", upper: true }
  mono-tag:    { fontFamily: "DM Mono", cqw: 0.78, weight: 400, tracking: "0.05em" }
  mono-chrome: { fontFamily: "DM Mono", px: 13, weight: 400, tracking: "0.06em" }
  # — display / hero ramp (Microsoft YaHei UI 700, negative tracking) —
  # 参考片的重磅标题是**靠字重**立住的（测得字重约 700），不是靠拉大字号。
  # 所以本项目的 display 阶梯从预设的 400 全部改成 700 —— 这是对预设的刻意偏离，见下方对齐规则。
  table-name:  { fontFamily: "Microsoft YaHei UI", cqw: 1.5, weight: 700, lineHeight: 1.15 }
  row-headline:{ fontFamily: "Microsoft YaHei UI", cqw: 2.1, weight: 600, lineHeight: 1.05 }
  ed-callout:  { fontFamily: "Microsoft YaHei UI", cqw: 2.6, weight: 600, lineHeight: 1.1 }
  headline:    { fontFamily: "Microsoft YaHei UI", cqw: 4.6, weight: 700, lineHeight: 0.95 }
  headline-index:{ fontFamily: "Microsoft YaHei UI", cqw: 5.0, weight: 700, lineHeight: 0.95 }
  display-quote:{ fontFamily: "Microsoft YaHei UI", cqw: 5.7, weight: 700, lineHeight: 1.05, tracking: "-0.005em" }
  display-chapter:{ fontFamily: "Microsoft YaHei UI", cqw: 6.8, weight: 700, lineHeight: 1.0, tracking: "-0.005em" }
  display-closing:{ fontFamily: "Microsoft YaHei UI", cqw: 9.4, weight: 700, lineHeight: 0.96, tracking: "-0.005em" }
  display-hero:{ fontFamily: "Microsoft YaHei UI", cqw: 10.4, weight: 700, lineHeight: 0.9, tracking: "-0.008em" }
  vbig-numeral:{ fontFamily: "Microsoft YaHei UI", cqw: 12.5, weight: 700, lineHeight: 0.9, tracking: "-0.015em" }

spacing:
  edge: "4cqw"          # standard frame edge inset (~80px@1920)
  pad-top: "7cqw"
  pad-bottom: "6cqw"
  gap-md: "2cqw"

components:
  graph-grid:
    backgroundImage: "linear-gradient grid, ~2cqw cells, 10% {colors.ink} ({colors.grid})"
    placement: "behind EVERY frame on the ground"
    description: "Permanent graph-paper grid — never disabled; the canvas tone."
  hairlines:
    rule: "0.12cqw solid {colors.ink}"
    placement: "≈3cqw from top + bottom, inset {spacing.edge}"
    description: "Two persistent cobalt rules framing every composition."
  page-chrome:
    typography: "{typography.pagenum}"
    color: "{colors.ink}"
    placement: "page number bottom-right, nav/meta hint bottom-left, above the bottom hairline"
    description: "The only persistent chrome."
  pixel-glitch:
    backgroundColor: "{colors.paper}"
    fill: "repeating-linear-gradient(90deg, {colors.ink} 0 2px, transparent 2px 8px)"
    size: "14–30cqw wide, full height, stair-stepped"
    placement: "right on cover/data, left on chapter/colophon; z above grid, below headline"
    description: "Stair-stepped scanline column. Decorative."
  qr-block:
    backgroundColor: "{colors.paper}"
    cells: "8×8, {colors.ink} on / {colors.grid} off"
    size: "3–9cqw square"
    shadow: "0 0 0 0.12cqw {colors.paper} (anti-shadow for readability, not elevation)"
    description: "QR mosaic patch — corner punctuation."
  topbar-rule:
    typography: "{typography.headline-index} + {typography.mono-tag}"
    borderBottom: "0.12cqw solid {colors.ink}"
    description: "Section header on index/data/table frames."
  ledger-row:
    layout: "grid: mono num · Microsoft YaHei UI name · Hanken desc · mono delta"
    borderBottom: "0.06cqw solid {colors.ink-faint} (header 0.12cqw solid {colors.ink})"
    typography: "{typography.mono-tag} + {typography.table-name} + {typography.body}"
    description: "Dense matrix row with ↑/↓/— delta."
  pixel-stack-bar:
    cells: "column-reverse, {colors.grid} off / {colors.ink} on"
    baseline: "0.12cqw solid {colors.ink} + {typography.mono-tick} ticks"
    description: "Data as grid-unit cells; echoes the glitch."
  vstack-label:
    typography: "{typography.mono-tick}"
    transform: "writing-mode: vertical-rl"
    description: "Catalogue chrome along a frame edge."
---

# Cobalt Grid — Frame (video / frame layer)

## Brand adaptation (READ FIRST — the frontmatter is the source of truth)

This is the **cobalt-grid** preset remixed onto the captured brand. The YAML frontmatter above (colors · typography · components) is **normative and already correct — use it verbatim.** The prose below is the ORIGINAL preset's intent; read it THROUGH the frontmatter:

- **Fonts** — already set to **Microsoft YaHei UI** (display) / **Microsoft YaHei** (body); ignore any preset font name lingering in prose.
- **Weights** — the brand font ships `{400, 600, 700}` only; every weight is clamped to these — ignore higher preset weights (e.g. 600/700) in prose.
- **Colors** — use the frontmatter hex; preset color NAMES in prose (e.g. "cobalt", "cream") mean the remapped brand values.

## 参考片对齐 — 本项目的最高优先级规则（压过下面所有预设原文）

本片的目标是**贴着参考片的风格与动效**（`Video_reference/来看看最新的_MC_启动器___LauncherX…mp4`，
1920×1080 / 24fps / 63.4s，纯 BGM 无口播）。参考片的实测特征：

- **一场一景**，不是连续镜头。全片平均镜头 ≈2.4s，但分布不均：开头 6.75s 一个纯氛围长镜头，
  6.75–9.6s 一次密集快切（标题爆发），之后每段功能 3–6s。
- 场景在**暖色实拍影棚场 / 大色块卡片场 / 白底窗口场 / 深色极光渐变场 / 纯品牌色满场 / 黑场**
  之间交替。
- 真正串起全片的是**一个反复出现的道具**（那张巨型版本号卡片，在下载页和反馈页又回来），
  不是连续的镜头。
- 实测排版：**居中**的重磅大标题（≈4.2cqw，字重 700，负字距）+ 居中副标题
  （≈2.1cqw，字重 600，字距拉开 0.16em），标题在上、窗口在下。
- 背景是**带暗角的近白场**（画面边缘比中心暗约 6–8%）。

### 停用：预设的招牌原子一律不用

参考片里一个都没有，所以本项目**全部停用**——`graph-grid`、`hairlines`、`pixel-glitch`、
`qr-block`、`pixel-stack-bar`、`vstack-label`、`page-chrome`、`topbar-rule`、`ledger-row`。
frontmatter 里这几个 component 保留原样只为记录来源，**worker 不许调用它们**。
「严格双色 + 方格纸」的 risograph 纪律**在本项目失效**。

### 场景色场：只有三种，一帧只用一种

| 色场 | 值 | 用在哪 | 字色 |
| --- | --- | --- | --- |
| `field-dark` | `#222428` | 开场氛围、竖屏段、插件段、片尾 | `#f1f2f5` |
| `field-blue` | `#00a1d6` | **布局系统整段（03–06）** | `#0d1114`（深字压亮底，对比度更高） |
| `field-light` | `#f1f2f5` | 细节段（08–11）、宣言段 | `#101114` |
| `field-black` | `#0d0e10` | 仅 Frame 01 的开场与 Frame 15 的片尾 | `#f1f2f5` |

`field-blue` 和 `field-light` 上**不要**再叠任何渐变或纹理——参考片的色块是平的。
`field-dark` / `field-black` 允许一层极缓慢移动的极光渐变（参考片的深色场就是这么做的），
但**不许出现第二层纹理**。

### 标题块（每一拍的主结构）

- 标题块**居中**（预设的"左对齐编辑体"在本项目失效）。
- 主标题用 `{typography.headline}`（4.6cqw / 700），副标题用 `{typography.row-headline}`
  （2.1cqw / 600 / tracking 0.16em）。
- 标题块与窗口的垂直关系：标题在上（约 `pad-top` 位置），窗口在下并**被画面下沿裁掉**——
  这是参考片的固定手法，暗示"界面还在往下延伸"，不要为了塞下整个窗口而缩小它。
- 副标题里的并列项之间**用空格分隔**（如 "音量 静音 画质"），不要用顿号堆成一串。

### 窗口 mockup 法规

- 圆角 `10px`（软件本体的 `RADIUS_LG` 是 12，tile 是 10 —— 用 10）。
- 柔和投影：`0 2cqw 5cqw rgba(0,0,0,0.28)`，**不许**发光、不许描边高光。
- **一切软件画面必须来自真机截图或真实录屏，一个像素都不许用 DOM 重画。**
- 窗口可以整体做轻微 3D 斜置（`rotateY(-6deg)` 量级）或推近，但**不许**变形到看不出是同一个窗口。

### 英雄道具：布局图 chip

参考片靠那张版本号卡片贯穿全片。本项目的等价物是**软件自己的布局缩略图 chip**
（`ddm/layouts.py` 里那套小格子线框图）——一个 `10cqw` 见方、圆角 8px、底色
`rgba(241,242,245,0.08)` 或反色的小方块，里面用细线画出当前布局的格子排布。

它**必须**出现在每一个讲布局的拍（03–06）、在 Frame 14 作为"全部布局"的阵列回收一次。
这是全片唯一的"图形记忆点"，靠它把七个分散的场景缝成一支片子。

## Overview

Cobalt Grid at frame scale is a **two-color risograph trend-report** — warm cream paper, electric
cobalt ink, and a **permanent graph-paper grid** behind every frame. Cobalt is the _only_ ink:
headlines, body, rules, the grid, the pixel-glitch decoration, the QR patches. There is no accent
color and no second surface.

The voice is a three-face conversation: **Microsoft YaHei UI** serif at weight 400 (size, not weight,
makes hierarchy) carries every display and headline; **Microsoft YaHei UI** carries body and
uppercase tracked labels; **DM Mono** carries all chrome — page numbers, tags, ticks, vertical
stacks. Every frame is framed by top + bottom cobalt hairlines; declarative frames carry the
**pixel-glitch column** and a **QR-block** patch.

**Key characteristics at frame scale:**

- **Strictly two-color** — cream paper + cobalt ink; no accent, no second surface.
- **Permanent ~2cqw graph-paper grid** (10% cobalt) behind every frame; cannot be disabled.
- **Top + bottom 1.5px cobalt hairlines** frame every composition, inset by `edge`.
- **Microsoft YaHei UI 400** for all display (negative tracking); **Hanken 600** uppercase 0.16em labels; **DM Mono** chrome.
- **Pixel-glitch column + QR-block** as the signature decorative patches on declarative frames.
- **Pixel-stack bars** render data as grid-unit cells (cobalt on / 10% off).

## The Frame

### Frame Craft Bar

Three eyeball tests gate every frame before any structural check:

- **Squint** — one Microsoft YaHei UI element dominates at **3–6× its nearest neighbor** (`display-hero`/`vbig-numeral`); hierarchy is size, never weight.
- **Silence** — declarative frames (cover, chapter, quote, colophon) read **45–60% empty** with the grid showing; the **index ledger and data frame are the one dense exception** (density via quiet repetition, not richness).
- **Restraint** — **two-color only** (cream + cobalt, never a second hue); one pixel-glitch column and at most one QR-block per declarative frame.
- **Reference** — aim at a **WIRED Japan / Shift two-color risograph monograph**; failure looks like a **colorful dashboard with a second accent hue**.

- **Primary:** 1920×1080 (16:9). Display authored in **`cqw`** (`px ÷ 1920 × 100 = cqw`).
- **Vertical:** 1080×1920 (9:16). **Square:** 1080×1080 (1:1).
- **Safe area:** `edge` (4cqw) inset; hairlines + page chrome live on the safe line.

**The container law (load-bearing).** Every frame ground sets `container-type: size` AND carries
the graph-paper `background-image`; ALL frame-relative units are `cqw`/`cqh` against it — never
`vw`. The grid `background-size` is `~2cqw 2cqw` so cell density holds at any render size.

## Colors

Tokens identical to the source. `{colors.paper}` is the ground; `{colors.ink}` cobalt is the only
ink (type, rules, grid lines, glitch, QR). `{colors.ink-soft}` is a secondary cobalt for editorial
subtitles only; `{colors.grid}` (10%) is the permanent grid + chart "off" cells; `{colors.ink-faint}`
(18%) is faint row dividers. **Never a second hue** — emphasis comes from size, from switching
Hanken→Microsoft YaHei UI, from a mono delta arrow, or from opacity, never from color.

## Typography

Two ramps. The **reading ramp** (Hanken body 0.83cqw, mono chrome in px) carries copy + labels;
the **display/hero ramp** (Microsoft YaHei UI `headline` 4.6cqw → `vbig-numeral` 12.5cqw) carries every
statement and figure.

- **Legibility floor:** any load-bearing line ≥ **1.4cqw**; mono chrome (px) is colophon only.
- **Fit-to-measure:** size the headline to its line length. Cap the block at **≤ 78cqw**; ≤3 words → `display-hero`/`vbig-numeral`; 4–6 → `display-chapter`; 7+ → `headline`.
- **Microsoft YaHei UI at 400 only**, in cobalt, with negative tracking (hero −0.008em, numeral −0.015em). **Hanken labels uppercase, 0.16–0.18em.** **DM Mono 0.04–0.08em.** No bold serif.

## Depth & Surface

Flat. Depth is structural only:

- **1.5px cobalt rules** — slide hairlines, topbar rule, chart baseline.
- **1px ink-faint dividers** — dense list / ledger rows.
- **The graph-paper grid** — measured-plane tone behind everything.
- **Pixel-glitch + QR** — texture and graphic punctuation, no z-axis.

**Ceiling:** no drop shadow (the QR's 1.5px paper outset is an anti-shadow for readability, not elevation), no gradient, no rounded corner, no second color.

## Shapes

- **0 radius everywhere** — frames, ledger rows, QR cells, glitch blocks, charts. Zero circular elements; this squareness is part of the identity.

## Components

- **graph-grid / hairlines / page-chrome** — the permanent frame furniture, inherited by every composition.
- **pixel-glitch** (edge column) + **qr-block** (corner patch) — the signature decoration on declarative frames.
- **topbar-rule** — the index/data/table section header. **ledger-row** — dense matrix row with delta arrows.
- **pixel-stack-bar** — data as grid-unit cells. **vstack-label** — vertical mono catalogue chrome.

## Frame Treatments

> Recipe: ground · container · composes · focal · chrome · accent · silence · Fixed/Free · density.
> The grid + hairlines are present on every frame. Choose density by type: declarative = sparse, index/data = dense.

### 1 · Hero Cover (identity · move: serif + glitch · left)

**Ground** paper + grid, hairlines. **Composes** pixel-glitch (right, ~26cqw), qr-block (top-right), display-hero, ed-callout. **Focal** a 1–2 line `display-hero` Microsoft YaHei UI headline in cobalt, left-anchored, with an italic `ed-callout` subtitle in `{colors.ink-soft}`. **Chrome** Hanken kicker; mono meta top + page number. **Accent** none (cobalt is the only ink). **Silence** ~45% paper. **Fixed** Microsoft YaHei UI 400, glitch + QR present, grid + hairlines. **Free** title, glitch step pattern, QR placement. **Density** sparse.

### 2 · Index Ledger (catalog · move: dense matrix · left — the dense frame)

**Ground** paper + grid, hairlines, `pad-top`/`pad-bottom`. **Composes** topbar-rule, ledger-rows. **Focal** a topbar (`headline-index` + mono lab-tag, 1.5px rule) over 4–6 ledger rows (mono num · Microsoft YaHei UI name · Hanken desc), ink-faint dividers. **Chrome** page number. **Accent** mono delta arrows. **Silence** tight — the density exception (the grid wants filling). **Fixed** 1.5px topbar rule, 1px ink-faint dividers, Microsoft YaHei UI names. **Free** rows, lab-tag, deltas. **Density** dense-exception.

### 3 · Chapter Opener (section · move: scale · sparse · left)

**Ground** paper + grid, hairlines. **Composes** pixel-glitch (left, ~14cqw, low opacity), mono index, display-chapter, body-lede. **Focal** a `display-chapter` Microsoft YaHei UI title, with a small mono `CHAPTER NN` index above and an optional Hanken lede ≤42cqw. **Accent** none. **Silence** ~60% — let the grid breathe. **Fixed** Microsoft YaHei UI 400, glitch low-opacity, grid showing. **Free** title, lede, glitch side. **Density** sparse.

### 4 · Data Frame (chart · move: pixel-stack · left)

**Ground** paper + grid, hairlines, `pad-top`. **Composes** topbar-rule, pixel-stack-bar row. **Focal** a row of 6–8 pixel-stack bars (cobalt on / 10% off) over a 1.5px cobalt baseline with mono ticks. **Chrome** topbar headline + mono fig-tag; page number. **Accent** none — data is cobalt cells. **Silence** moderate. **Fixed** grid-unit cells, cobalt baseline, mono ticks. **Free** bar values (from script), tick labels. **Density** standard/dense.

### 5 · Manifesto / Quote (quote · move: centered statement · sparse)

**Ground** paper + grid, hairlines. **Composes** display-quote (or display-manifesto), attribution rule, optional compact glitch. **Focal** a 2–3 line Microsoft YaHei UI pull in cobalt, with a Hanken kicker above and a 1px cobalt attribution rule + mono byline beneath. **Accent** none. **Silence** ~55% — deliberately open. **Fixed** Microsoft YaHei UI 400, attribution rule, grid showing. **Free** quote, byline. **Density** sparse.

### 6 · Colophon (closer · move: right-aligned close · sparse)

**Ground** paper + grid, hairlines. **Composes** pixel-glitch (left edge, mirroring the cover), display-closing, mono credit columns. **Focal** a right-aligned `display-closing` Microsoft YaHei UI title with a Hanken kicker above. **Chrome** 3–4 column mono credit grid at the foot; page number. **Accent** none. **Silence** ~50%. **Fixed** glitch on left, Microsoft YaHei UI 400. **Free** closing line, credits. **Density** sparse.

## Composition Rules

### Do

- Keep the **graph-paper grid + top/bottom hairlines** on every frame — they are the system.
- Set **Microsoft YaHei UI at 400 in cobalt**; make hierarchy with size, not weight; negative-track display.
- Track **Hanken labels uppercase 0.16em**; **DM Mono chrome 0.04–0.08em**.
- Render data as **pixel-stack cells** (cobalt on / 10% off); echo the glitch language.
- Use the **pixel-glitch column + QR patch** on declarative frames (cover, chapter, quote, colophon).
- Lean: declarative frames sparse and breathing; index/data dense. Vary anchor (left for index/chapter, centered for quote/closer).

### Don't

- Don't introduce a second ink color — cream + cobalt only.
- Don't bold Microsoft YaHei UI, round any corner, or add a drop shadow (QR outset is an anti-shadow only).
- Don't disable the grid or suppress the hairlines.
- Don't crowd chapter / quote / colophon — those let the grid show.
- Don't blow a serif headline edge-to-edge — fit to measure.

## Aspect-Ratio Behavior

| Treatment         | 16:9                        | 9:16                                 | 1:1                          |
| ----------------- | --------------------------- | ------------------------------------ | ---------------------------- |
| Hero Cover        | headline left, glitch right | headline top, glitch full-width band | headline upper, glitch lower |
| Index Ledger      | topbar + rows               | topbar + fewer rows                  | 2-col compresses to 1        |
| Chapter Opener    | title left, glitch left     | title top, glitch side               | centered title               |
| Data Frame        | 6–8 bars                    | 4–5 bars taller                      | square chart                 |
| Manifesto / Quote | centered pull               | centered, taller                     | centered                     |
| Colophon          | right-aligned, glitch left  | stacked, glitch top                  | centered close               |

Grid + hairlines hold on the short edge for every ratio; re-step display so no load-bearing line
drops below 1.4cqw. Mono chrome stays Latin/digit-only.

## Approved Entities

No real customers, logos, or vendors are defined in the source — render any such mark as a
placeholder. Trend names, signals, and figures are content; the system supplies the grid and chrome.

## Numerals & Claims (hard rule)

Never invent figures, deltas, dates, or signal counts at frame scale. Render slots as `— figure —`,
`{metric}`, `↑ —`. Pixel-stack bar heights and ledger deltas especially carry placeholders until the
script supplies values. Mono catalogue ordinals (001, 002…) are decorative and may be sequential.

## Pre-Render Self-Audit

- **Squint** — one Microsoft YaHei UI element dominates at 3–5× its neighbor.
- **Silence** — declarative frames 45–60% empty; only index/data run dense.
- **Two-color** — cream + cobalt only; no second hue anywhere.
- **Furniture** — grid present, top/bottom hairlines present, page chrome above the hairline.
- **Type** — Microsoft YaHei UI 400 negative-tracked, fit-to-measure; Hanken labels 0.16em; ≥1.4cqw floor.
- **Depth** — 0 shadow (QR outset excepted), 0 rounded corner.
- **Anchor** — left on index/chapter/cover, centered on quote/closer; no 3 consecutive frames share an anchor.
- **Fabrication** — every numeral/delta traces to the script, else placeholder.

## Known Gaps

- **Motion intentionally out of scope.** frame.md specifies composition only; the 280ms cross-fade in the source is a deck mechanic.
- **Pixel-glitch is rendered in CSS here** (stacked scanline blocks) rather than the source's inline SVG, to keep the showcase SVG-free; fidelity is preserved.
- **Three Google Fonts** (Microsoft YaHei UI, Microsoft YaHei UI, DM Mono); CJK pairing (Noto Serif SC 700/400) carries over from the source.
- **9:16 / 1:1 are guidance**; verify the legibility floor and grid density per ratio.
- The QR mosaic and glitch step patterns are hand-authored; there is no generative layer.
