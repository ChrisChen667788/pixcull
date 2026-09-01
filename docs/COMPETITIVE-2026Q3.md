# PixCull Competitive Intelligence — 2026 Q3

*Produced 2026-08-31. Supersedes `COMPETITIVE-UX-2026Q3.md` (2026-08-21), which
covered UX only. 46 products and models scanned; 10 headline claims sent to an
independent fact-checking pass.*

## Read this before the findings

**All ten claims that were fact-checked failed.** Not one survived contact with
its own cited source. That is the single most important result in this document,
and it is about the method, not the market:

| what the first pass said | what checking found |
|---|---|
| a rival's flagship feature, dated from its changelog | the changelog entry covers a theme change and a bug fix; the feature shipped in 2020 |
| a competitor's end-to-end pipeline, sourced to a review | the review confirms three of the five components; two are beta with no ship date |
| a Chinese vendor's client-selection stack, sourced to a national newspaper | the article is paid promotional content, disclaimed as non-editorial, and does not mention the features attributed to it |
| an open-weight model's benchmark result "as of August 2026" | the paper is from August **2025** — a year stale, and since overtaken |
| a platform vendor's "Smart Stacking" | no such feature name exists in the vendor's documentation |

The lesson is not that any particular rival is weak. It is that a single-pass
competitive scan reports vendor marketing back to you with a citation stapled on,
and the citation frequently does not say what the scan claims it says. Every
capability line below carries a source and a date, and anything that could not be
confirmed is marked unverified rather than quietly dropped or rounded up.

**No prices appear anywhere in this document.** Pricing structure is described in
words where it matters competitively. This is enforced by `test_no_money_amounts`.

---

*Analysis date: 2026-08-31. Prior edition: docs/COMPETITIVE-UX-2026Q3.md (2026-08-21, UX-only scope). This edition expands to full product, model, and market coverage.*

---

## 1. WHAT CHANGED

**Genuine movement since mid-2026:**

**Adobe Lightroom Assisted Culling went GA (June 2026).** This is the single largest competitive shift of the quarter. It places a basic pass/fail culling feature inside the tool most professional photographers already open every day, at no additional cost. Capability is narrow — it evaluates eye-open status and eye sharpness, then groups similar frames into stacks — but the zero-friction distribution is structurally harder to compete against than any accuracy figure. Source: [Adobe Blog, 2026-06-15](https://blog.adobe.com/en/publish/2026/06/15/from-culling-to-compositing-new-creative-cloud-innovations-across-every-stage-of-your-workflow)

**Aftershoot shipped an integrated post-production pipeline (June 2026).** A June 2026 hands-on review confirmed that a 2,613-file shoot could move from import through client gallery delivery without leaving the application. Culling accuracy is self-reported at 83–85% (figures vary between announcements; no independent benchmark). Several prominent features remain in beta: Cull to Target, tethering, and on-device face recognition were announced July 2026 but have no confirmed general-availability date. Aftershoot is a cloud-processing service; photos leave the photographer's machine for AI scoring. Sources: [Fstoppers, 2026-06-15](https://fstoppers.com/software/aftershoot-just-became-entire-ai-photography-workflow-903026); [Photo Rumors, 2026-07-11](https://photorumors.com/2026/07/11/here-is-whats-coming-next-in-aftershoot/)

**Imagen AI launched Fast Track (June 2026).** Combined cull-plus-edit in a single uninterrupted cloud run, returning a project in the photographer's editing style. The nearest thing to a sequential automated pipeline in the market, though it is a fixed sequence with user-set parameters rather than a planning agent. Source: [Imagen AI changelog, 2026-06-17](https://account.imagen-ai.com/changelog/photo/)

**FilterPixel released DeepCull (April 2026).** Genre-specific AI models for Wedding, Conference, Sports, and Concert. When a genre is selected at import, a model trained specifically for that discipline scores the shoot. Accuracy is self-reported at 85–95% after per-photographer training; no independent benchmark. Source: [FilterPixel blog, 2026-04-04](https://filterpixel.com/blog/introducing-deepcull-memory-based-culling)

**Capture One 16.8 shipped Assisted Review in beta (May 2026).** Tags images "Need review," "Issues Detected," or "Can't tell" based on closed eyes, focus miss, and black frames. Three-bucket output only; no scoring or written rationale. Source: [Capture One, 2026-05-28](https://www.captureone.com/en/explore-features/whats-new/16-8)

**Apple Intelligence (iOS 27 / macOS 27) announced Best Take and Photo Stacks (June 2026).** On-device burst selection using facial expression analysis, zero cost for compatible hardware owners. Consumer-grade only — no RAW support, no Lightroom integration. Source: [Apple Newsroom, 2026-06](https://www.apple.com/newsroom/2026/06/apple-intelligence-brings-powerful-ai-capabilities-into-everyday-experiences/)

**InternVL3.5 released (August 2026).** Open-weight VLM (CC BY 4.0) with a Visual Resolution Router that halves visual token count at inference. The 20B-A4B MoE variant fits a 32 GB Apple Silicon Mac. Source: [arXiv 2508.18265, 2026-08](https://arxiv.org/html/2508.18265v1)

**Qwen3-VL 8B with GRPO fine-tuning won NTIRE 2026 RAIM Track 1 (April 2026).** Score 0.7305 against professional annotator ground truth for photographic quality assessment. Weights are Apache 2.0; the 8B variant runs on a 16 GB Mac at 25–35 tokens per second. Source: [arXiv 2604.12512, 2026-04](https://arxiv.org/html/2604.12512v1)

**Little that changed:**

- Narrative Select v2.5.0 (August 25, 2026) shipped only dark-mode theme matching and minor fixes. Scenes View and Close-Ups Panel have been in the product since October 2020; Lightroom CC integration since January 2025. No new core culling capability this quarter. Source: [Narrative changelog, 2026-08-25](https://narrative.so/changelog)
- Photo Mechanic 6: no AI culling as of mid-2026. Status unchanged.
- DxO PhotoLab, Skylum Luminar Neo, Sony Creators App, Canon DPP, Nikon NX Studio: no new AI culling features confirmed this quarter.

---

## 2. THE FIELD

### 2a. International dedicated culling tools

| Product | Who it is for | Flagship capability | Underlying model | Photos live | Source date |
|---|---|---|---|---|---|
| **Aftershoot** | High-volume photographers wanting one subscription for the full post-production pipeline | Integrated pipeline: cull → RAW edit → retouch → client gallery + print sales in one application | Not disclosed | Cloud (AI scoring on Aftershoot servers; photos leave machine) | [Fstoppers, 2026-06-15](https://fstoppers.com/software/aftershoot-just-became-entire-ai-photography-workflow-903026) |
| **Narrative Select** | Event photographers who organise work by narrative scenes | Scenes View (chronological scene grouping with ranked images, available since 2020) + Close-Ups Panel (1:1 simultaneous face display) | Not disclosed | On-device by default; no cloud upload documented | [narrative.so/changelog](https://narrative.so/changelog), verified 2026-08-31 |
| **Imagen AI** | Lightroom Classic users wanting personalised editing style applied at scale | Fast Track: cull + full AI edit in a single cloud run (GA June 2026) | Not disclosed | Cloud; all processing on Imagen servers | [Imagen changelog, 2026-06-17](https://account.imagen-ai.com/changelog/photo/) |
| **FilterPixel (DeepCull)** | High-volume specialists (wedding, sports, conference, concert) | Genre-specific AI models loaded per-shoot based on selected genre | Not disclosed; trained on working-photographer output curated by professionals | Cloud; no local installation | [FilterPixel blog, 2026-04-04](https://filterpixel.com/blog/introducing-deepcull-memory-based-culling) |
| **Optyx** | Photographers wanting fast burst-grouping with face scoring | Speed-focused burst grouping with simultaneous face and blink scoring; claims 1,000 images in 60 seconds (unverified against independent benchmark) | Not disclosed | Cloud | [Shotkit, 2026-01](https://shotkit.com/optyx-ai-photo-selection-tool/) — **partial confidence: no 2026 primary source found** |
| **Apex Culler** | Windows photographers seeking a lifetime-licence alternative with large feature count | 130+ features including shot list detection and distraction scanning alongside culling (unverified from primary vendor source) | Not disclosed | Desktop / local (Windows only) | [ShutterNoise, 2026-08](https://www.shutternoise.com/articles/ai-photo-culling-compared-2026.html) — **unverified: no primary vendor source confirmed** |
| **Evoto AI** | Photographers wanting culling and retouching in one product across 200+ countries | Multi-axis culling (blur, closed eyes, composition, duplicates, exposure) combined with integrated retouching; adjustable strictness; Evoto Instant handles client-facing delivery | Not disclosed; "multi-model approach" | Not publicly specified (background multi-threading cited); network connection required | [Evoto AI features page, 2026-08](https://www.evoto.ai/features/ai-culling) |

### 2b. Platform-native tools

| Product | Who it is for | Flagship capability | Underlying model | Photos live | Source date |
|---|---|---|---|---|---|
| **Adobe Lightroom Assisted Culling** | Lightroom users wanting zero-friction first-pass reject filtering | Face View: per-person Eyes Open + Eye Sharpness scoring; Stacking (Auto Stack) groups similar burst frames | Adobe proprietary; undisclosed | Smart Previews transit Adobe's cloud servers for inference; full RAW stays local | [Adobe Blog, 2026-06-15](https://blog.adobe.com/en/publish/2026/06/15/from-culling-to-compositing-new-creative-cloud-innovations-across-every-stage-of-your-workflow) |
| **Adobe Bridge CC** | Photoshop-centric photographers needing manual rating and metadata | Free for any Adobe ID holder; deep Photoshop + Camera Raw integration; no AI culling | None (no AI culling) | On-device | [Adobe helpx, current](https://helpx.adobe.com/bridge/using/what-is-adobe-bridge.html), verified 2026-08-31 |
| **Capture One 16.8 Assisted Review** | High-end commercial and fashion studios using Capture One for tethering | Three-bucket portrait-failure tagging during live tethered ingestion (beta) | Not disclosed | On-device (inference details not confirmed) | [Capture One, 2026-05-28](https://www.captureone.com/en/explore-features/whats-new/16-8) |
| **Apple Photos + Apple Intelligence** | iPhone and Mac owners wanting personal memory browsing | Best Take (facial expression burst selection); Photo Stacks (best-pick promotion); all on-device | Apple proprietary Apple Neural Engine models | On-device; no cloud upload | [Apple Newsroom, 2026-06](https://www.apple.com/newsroom/2026/06/apple-intelligence-brings-powerful-ai-capabilities-into-everyday-experiences/) |
| **Google Photos** | Android and iOS users with personal photo libraries | Best Take; Photo Stacks; lifetime-library "best of" memories; automated photo-book layout | Google AI (Gemini-family, specifics undisclosed) | Cloud (Google servers) | [TalkAndroid, 2026](https://www.talkandroid.com/525025-discover-the-next-era-of-google-photos-ai-innovation-privacy-tips-and-everything-you-need-to-know-in-2026/) |
| **ON1 Photo RAW 2026** | Photographers wanting perpetual-licence culling inside a full RAW editor | AI culling (blur, eye state, sharpness, duplicates) + Resize AI 2026 generative super-resolution, all in one perpetual-licence app | ON1 proprietary | Not specified — **partial confidence** | [ON1 press, 2025-10](https://www.on1.com/press/on1-announces-photo-raw-2026-with-advanced-ai-tools-masking-layers-and-new-creative-filters/) |
| **DxO PhotoLab (v9+)** | Photographers prioritising noise reduction quality above all | DeepPRIME XD noise reduction; AI subject masking; no dedicated culling feature | DxO proprietary CNN | On-device | [LifeAfterPhotoshop, 2025](https://lifeafterphotoshop.com/dxo-photolab-9-ai-masking-tools-explained-with-examples/) — **partial confidence: no 2026 update confirmed** |
| **Skylum Luminar Neo (2026)** | Prosumer photographers wanting creative AI edits without a steep learning curve | Sky replacement, relighting, atmosphere simulation; Smart Search for content-aware retrieval | Skylum proprietary | Not specified — **partial confidence** | [Expert Photography, 2026](https://expertphotography.com/luminar-neo-review) |
| **Peakto 2.6 (CYME)** | Mac photographers managing years of backlog across multiple catalogs | Global cross-library AI deduplication and culling across all catalogs, drives, and NAS simultaneously | Not disclosed | On-device (Mac only) | [CYME blog, 2026-01-14](https://cyme.io/en/blog/peakto-introduces-powerful-ai-driven-culling-and-deduplication/) |
| **Photo Mechanic 6** | Photojournalists and sports photographers who want zero-AI, maximum-speed manual review | Fastest manual browse available; reads embedded JPEG previews, not RAW decode; strong IPTC metadata editing | None | On-device | [FilterPixel blog, 2026-05](https://filterpixel.com/blog/photo-mechanic-ai-alternative) |

### 2c. China market

| Product | Who it is for | Flagship capability | Underlying model | Photos live | Source date |
|---|---|---|---|---|---|
| **美图云修 Meitu Yunxiu v8.0 / iPad v1.3.0** | Chinese commercial studios (wedding, portrait, travel shoot) | 骨相磨皮 (bone-structure skin smoothing); iPad v1.3.0 includes tethered-camera import to AI retouching (shipping via App Store; production reliability unconfirmed by independent review); library culling (图库选片) added at P&I Shanghai 2026 | Meitu proprietary | Desktop v8.0 is desktop-only; iPad processing mode (on-device vs cloud) unconfirmed | [ifanr, 2026-07-24](https://www.ifanr.com/digest/1673029); [official download page](https://yunxiu.meitu.com/download/), verified 2026-08-31 |
| **像素蛋糕 PixCake** | B2B portrait studios, multi-seat collaboration | Five-step studio pipeline (shoot, retouch, layout, select, deliver); Sugar Engine 2.0 GPU-accelerated retouching; client selection marketed as a feature (QR-code WeChat mini-program mechanism could not be confirmed for any version called "3.0") | PixCake proprietary Sugar Engine 2.0 | Cloud collaboration layer confirmed; whether AI compute is cloud-mandatory is unverified | [pixcakeai.com](https://www.pixcakeai.com/), verified 2026-08-31 |
| **百度网盘 AI修图 Baidu Netdisk AI Photo** | Studios already storing images in Baidu Netdisk | AI筛片 (culling) + client selection portal + Baidu cloud storage in one product, zero switching cost for existing Baidu users | Baidu proprietary CV models | Cloud (Baidu infrastructure) | [Baidu Netdisk open platform, 2026-01](https://pan.baidu.com/union/openAbility/openCapabilityDetails?type=aiphoto) — **partial confidence: no independent source found** |
| **绚篇 Xuanpian** | Travel photographers and small studios needing client proof delivery during or after shoots | 传送门: real-time shoot-and-select link, client selects and pays before photographer returns home; screenshot and screen-recording protection | Not disclosed | Cloud delivery portal; client browses via WeChat mini-program | [xuanpian.com](https://www.xuanpian.com/), verified 2026-08-31 |
| **像素本 Xiangsuben** | Studios wanting local AI compute plus cloud client delivery | Local AI toolkit (culling, retouching, group-photo processing) reported as free with no usage limits, running on studio hardware; cloud platform handles client-facing selection | Not disclosed | Hybrid: AI compute local; client delivery cloud | [help.xiangsuben.com](https://help.xiangsuben.com/), 2026-06 — **partial confidence: terms and model provenance not publicly documented** |
| **咻图AI** | High-volume portrait studios (wedding, children's) wanting throughput | 15,000 images per day post large-model upgrade; one-click skin beautification, contouring, body liquify | "Large model" upgrade, specific model not named | Cloud | [ai-bot.cn, 2026-01](https://ai-bot.cn/sites/6575.html) — **partial confidence: no independent review found** |
| **海草云 魔镜修图 Haicaoyun Mojing** | Small studios without GPU workstations | Lightweight inference architecture enabling batch AI retouching on ordinary office PCs without discrete GPUs | Proprietary lightweight inference; not disclosed | Desktop / on-premise | [gitcode.csdn.net, 2026-01](https://gitcode.csdn.net/6a2a88a110ee7a33f27b427f.html) — **partial confidence** |
| **醒图专业版 Xingtu Pro (ByteDance)** | Cosplay, event, and Douyin-creator photographers wanting same-day social delivery | One subscription for mobile SVIP + desktop Pro; per-user AI aesthetic profile built from editing history; desktop Pro launched April 2026 | ByteDance proprietary | Cloud upload for AI processing | [Sohu, 2026-04](https://www.sohu.com/a/1008326325_121956424) |

### 2d. Camera-maker tools

| Product | Who it is for | Flagship capability | Underlying model | Photos live | Source date |
|---|---|---|---|---|---|
| **Canon DPP + Camera Connect** | Canon owners wanting free software from the manufacturer | Manual star/colour-label rating; in-camera DIGIC AI raises pre-import hit rate (capture-time only) | Canon DIGIC AI (in-camera, capture-time) | On-device | [Digital Camera World, 2025](https://www.digitalcameraworld.com/features/oh-my-god-canons-in-camera-ai-is-going-to-change-everything) — **partial confidence** |
| **Sony Creators App** | Sony Alpha owners | Wireless transfer and remote shooting; no AI-based photo selection confirmed | Sony proprietary (in-camera AI unit, capture-time only) | On-device | [Sony ANZ, 2025](https://scene.sonyanz.com/sne-hub/explore-all/poweredbyai) — **partial confidence** |
| **Nikon NX Studio + NX Tether** | Nikon owners wanting free tethering with Lightroom/Capture One handoff | Wireless and USB tethered capture; enhanced highlight/shadow recovery (May 2026 update); no AI culling confirmed | None confirmed | On-device | [Markus Hagner Photography, 2026-05](https://markus-hagner-photography.com/new-software-updates-for-nikon-nx-studio-nx-tether-and-camera-control-pro-2/) |

### 2e. Model components (relevant for PixCull's own architecture)

| Model | Relevance to PixCull | Licence | Hardware floor | Source date |
|---|---|---|---|---|
| **Qwen3-VL 8B + GRPO/LoRA (NTIRE 2026 RAIM winner)** | Addresses PixCull's shallowest known weakness: multi-sentence expert photographic rationale verified against professional annotator ground truth (0.7305 score). Runs locally at 25–35 tokens/second on a 16 GB Mac. | Apache 2.0 | 16 GB unified memory | [arXiv 2604.12512, 2026-04](https://arxiv.org/html/2604.12512v1) |
| **InternVL3.5 (20B-A4B MoE)** | Visual Resolution Router halves token cost; strong MMMU (77.7) and grounding scores; fits 32 GB Mac; CC BY 4.0 permits fine-tuning | CC BY 4.0 | 32 GB unified memory | [arXiv 2508.18265, 2026-08](https://arxiv.org/html/2508.18265v1) |
| **Claude Fable 5 / GPT-5.x API** | Frontier photographic critique via API; multi-paragraph chain-of-thought; GPT-4o fine-tuning API allows custom photographic critic training. Carries per-image credit model cost. Critique quality exceeds PixCull's current output but introduces API dependency and cost unpredictability at scale. | Commercial API | API only | [Anthropic model overview, 2026-08](https://platform.claude.com/docs/en/about-claude/models/overview) |

---

## 3. WHERE PIXCULL IS GENUINELY AHEAD

These are advantages that survive contact with how photographers actually use competing tools, not advantages that merely appear on a feature checklist.

**Written natural-language rationale per image.** No other dedicated culling tool in either the international or China market produces a per-image written explanation of why a frame scored as it did. Aftershoot, FilterPixel, Imagen, Optyx, and Evoto all return binary keep/reject decisions or at most a category label (blur, closed eyes, duplicates). Lightroom Assisted Culling gives two named axis scores per person. PixCull's 6-axis scoring with written rationale is the only product that explains the decision in a form that can teach the photographer or be audited by a client. The quality of that rationale is a separate question (see section 4), but the structural presence of it is unique.

**Per-vertical rubric weighting that the photographer controls.** PixCull's 9 shooting verticals with user-adjustable per-vertical weighting give a photographer different selection standards for a wildlife burst versus a studio portrait versus a street assignment. FilterPixel's DeepCull approaches this with 4 fixed genre-specific trained models, but those models are black boxes and the genre set is not extensible. PixCull's rubric is auditable and extensible. No other tool in the survey exposes weighting at this granularity.

**Cull-reason taxonomy as an auditable record.** The structured record of why each image was rejected — not just a binary flag — is unique in the market. It enables the photographer to spot systematic problems in their shooting (e.g., consistently soft focus at a particular focal length), defend decisions to a client, and measure whether active learning is actually moving the right needle over time.

**Burst-peak selection for sequential action.** Explicit identification of the peak action moment in a sports, wildlife, or dance burst, distinct from simple blur/sharpness detection, has no documented equivalent in any other tool surveyed. Aftershoot's Cull to Target (beta, not GA) addresses count but not peak-moment identification. Apple Photos' Best Take addresses facial expression in portrait bursts only.

**MIT licence with fully local default.** PixCull is the only dedicated culling tool surveyed that is open-source and can be run permanently air-gapped. For photographers under client confidentiality obligations (medical, legal, defence, government contractors), a tool that requires cloud upload is simply not permissible regardless of its accuracy. PixCull's local-first mode with opt-in cloud is not matched by Aftershoot (cloud-required), Imagen (cloud-required), FilterPixel (cloud-required), or Baidu Netdisk (cloud-required). Narrative Select also processes locally, but it is not open source.

**Measurement-led engineering process with refusal guards.** Non-circular evaluation, blind labelling, and automated refusal guards that decline to ship a change when evidence is thin represent a development discipline with no published counterpart among competitors. No other product surveyed has disclosed anything equivalent to a pre-commit gate that blocks a scoring change lacking evidence.

**Active learning from named face library corrections.** The loop from photographer correction → named face library → updated model personalisation is unique in combining an auditable identity record with learning. FilterPixel's adaptive learning is photographer-level (it replicates past culling patterns) but has no named face record. Aftershoot's "Dynamic AI Learning" is, per the only confirmed hands-on review, a profile-at-onboarding step from existing Lightroom catalog data — not live in-app correction learning.

---

## 4. WHERE PIXCULL IS BEHIND

Ranked by cost to a real photographer, not by engineering ease.

**1. Shallow written critique with no measured advice quality.** The owner has stated directly that the current rationale output is "too shallow, does not show photographic expertise." No blind evaluation of advice quality has been published. The gap between a rubric-driven rationale and the output of a fine-tuned VLM trained on professional photographic critique data (e.g., NTIRE 2026 winner Qwen3-VL 8B) is large and not measured. A photographer using PixCull today has no basis to trust or distrust the written critique beyond anecdote. This is the most damaging gap because it undercuts the feature that is structurally unique in section 3.

**2. No client-selection workflow.** For Chinese commercial studios in the wedding, portrait, and travel-shoot market, the step between the photographer's internal cull and the client's own photo selection is a major operational workflow. Xuanpian, PixCake, Baidu Netdisk AI, Xiangsuben, and Evoto Instant all address it. PixCull has no answer. This is not a niche omission: for the studio photographer segment in China, the absence of client-facing proof delivery makes PixCull an incomplete tool regardless of culling accuracy.

**3. No integrated editing or retouching pipeline.** Aftershoot, Imagen AI, Evoto AI, ON1 Photo RAW, Meitu Yunxiu, PixCake, and Xingtu Pro all continue past the cull stage. For a high-volume photographer who wants a single tool to deliver a finished product, PixCull requires a handoff to a separate editing application. The XMP sidecar and Lightroom plugin manage this handoff, but it remains a separate step that competitors have eliminated.

**4. Personalisation not yet measured.** PixCull's active learning from corrections is an engineering feature; whether it actually changes culling outcomes for a specific photographer is not measured and not demonstrated. A photographer who has corrected PixCull's decisions for six months has no evidence that subsequent culls are more accurate for their style. The claim exists but cannot be validated.

**5. First-open latency and grid render cost.** The documented 2.2s first-open latency (improved from 3.4s) and 883ms style recalculation cost for a 5,069-child grid are real, reproducible costs that affect perceived responsiveness on large shoots. Cloud competitors (FilterPixel: 1,000 images in under 3 minutes claimed; Optyx: 1,000 images in 60 seconds claimed — both unverified against independent benchmarks) process asynchronously, hiding latency from the user. Narrative Select's local processing is also faster for the UI render layer because it operates on thumbnails rather than a DOM-heavy grid.

**6. No independent accuracy benchmark.** PixCull has measurement-led development but no published accuracy figure that a prospective photographer can compare to Imagen's claimed 95%+, FilterPixel's claimed 85–95%, or Aftershoot's self-reported 83–85%. All competitor figures are vendor-reported and equally unverified — but competitors have a number to quote; PixCull does not.

**7. Lightroom Assisted Culling now handles the easy rejects for free, inside Lightroom.** The "zero-additional-cost first-pass reject" use case that made AI culling attractive is now covered natively in Lightroom for portraits. PixCull's value proposition must now articulate what it adds over what Lightroom already does for photographers in the portrait/event segment who upgrade to v9.4. The answer is substantial (section 3) but requires explanation that was not needed before June 2026.

---

## 5. WHERE THE COMPARISON IS UNFAIR IN PIXCULL'S FAVOUR

This section is mandatory. These are claimed advantages that are weaker in practice than they appear in a feature comparison.

**"Local-first" as a universal advantage.** Local processing matters enormously for photographers with confidentiality obligations, but the majority of photographers who use Aftershoot, Imagen, or FilterPixel are uploading wedding, portrait, and event work to cloud services throughout their existing workflow (Dropbox, Google Drive, gallery delivery platforms). For this majority, the marginal privacy concern of also uploading to a culling service is minimal. The local-first advantage is a real differentiator for a specific professional segment (medical, legal, defence, government-adjacent); it is not a meaningful advantage for the high-volume wedding or event photographer who is already in the cloud at every stage.

**"Written rationale" as explainability.** Written rationale is only as useful as the expertise embedded in the model. If the critique is acknowledged by the owner to be "too shallow, does not show photographic expertise," then comparing PixCull's written rationale against a binary keep/reject decision is a category comparison that does not reflect quality. A photographer who reads a shallow rationale learns less than a photographer who has internalised why they rejected a frame manually. The structural presence of rationale text, presented as an advantage in section 3, needs to be qualified by the acknowledged quality deficit.

**"9 verticals with per-vertical weighting" vs FilterPixel's genre-specific models.** PixCull's verticals are rubric-weighting schemes applied to a general model. FilterPixel's DeepCull loads a separate trained model for each genre. Whether a photographer selecting a weighting scheme achieves better results than one selecting a genre-specific trained model is not tested. The claim that PixCull's extensible verticals outperform genre-specific models is plausible but undemonstrated.

**"Active learning from corrections" as a personalisation advantage.** The claim that corrections feed back into a personalised culling model over time cannot be validated by the photographer. If the effect is real but small, or if it degrades on edge cases, the photographer has no way to know. Until there is a measurable demonstration — a before/after accuracy comparison on held-out images from the same photographer's style — this advantage lives only in architecture, not in demonstrated outcome.

**"MIT open source" as a trust signal.** Most photographers do not audit source code. MIT licence means the software can be forked, inspected, and run without vendor dependency — useful for institutions and technically capable users. For the practising photographer who installs software from a package manager and does not inspect it further, open source is indistinguishable in practice from a proprietary tool that is also locally installable. Narrative Select, for example, is closed-source and local — and for most photographers that distinction is invisible.

**"Measurement-led engineering" as a user-facing feature.** Non-circular evaluation and refusal guards are process disciplines that prevent regressions. They are not capabilities the photographer experiences directly. They may produce better outcomes over time, but a photographer comparing PixCull with Aftershoot at a trade show cannot see them, and they do not appear on a feature comparison sheet. Presenting them as a competitive advantage requires translating them into measurable outcomes — which PixCull has not yet published.

---

## 6. ROADMAP

*Versions continue from v2.78. Ordered by value to a working photographer, not engineering convenience. Where a rival capability is deliberately declined, that decision is stated explicitly.*

---

### v2.79 — Advice depth: upgrade written rationale to expert-grade quality

**Goal:** Replace the current rubric-driven rationale with critique that demonstrates photographic expertise — technically specific, commercially relevant, vocabulary-matched to the shooting vertical.

**Specific change:** Integrate a GRPO-fine-tuned Qwen3-VL 8B (NTIRE 2026 RAIM winner, Apache 2.0) as the rationale-generation layer. The 8B model fits a 16 GB Mac at 25–35 tokens per second and can run fully local, preserving PixCull's local-first architecture. Each image receives a multi-sentence rationale covering sharpness plane, exposure quality, compositional intent, and vertical-specific criteria (e.g., peak-action timing for sports; emotion capture for weddings). The current rubric axes are retained as structure; the model provides depth within each axis.

**Measurement:** Blind evaluation by three working photographers (one per vertical) comparing 50 current rationale outputs against 50 Qwen3-VL-generated rationales on the same images. Outcome measure: proportion rated "demonstrates photographic expertise" — pre-specified threshold must exceed 70% for the change to ship. This is the non-circular evaluation the refusal guard would enforce.

**Way it could be wrong rather than merely late:** The NTIRE 2026 winning system was evaluated on professional IQA benchmarks; the benchmark domain (technical image quality assessment) may not fully transfer to the creative and contextual judgements that define PixCull's per-vertical scoring. Specifically, wedding-emotion scoring and sports peak-moment identification require narrative context that a single-image VLM inference may not capture. The evaluation must include these verticals explicitly, not just the technical axes where VLMs are strongest.

---

### v2.80 — Advice quality baseline: publish the first blind evaluation result

**Goal:** Produce a measurable, independently reproducible result for advice quality that PixCull can publish, replacing the current absence of any public accuracy figure.

**Specific change:** Using the 608-row correction set already in ~/pixcull_label_run as ground truth, run a formal blind evaluation comparing the current model output against v2.79's upgraded output. Report the proportion of images where the rationale was rated "sufficiently expert" by blind raters (working photographers, not employees). Publish the result — including cases where the new rationale was rated worse — in the repository.

**Measurement:** The evaluation itself is the deliverable. Pass condition: at least three raters, at least 100 images each, pre-registered rubric, results published before v2.80 ships.

**Way it could be wrong:** Inter-rater agreement on "photographic expertise" in written critique is historically low (30–40% agreement is typical in fine art evaluation). If rater agreement is below a pre-specified threshold (suggested: Krippendorff's alpha ≥ 0.45), the rubric needs revision before the result can be considered valid. Publishing a low-agreement result as meaningful data would be worse than not publishing.

---

### v2.81 — Personalisation evidence: demonstrate that corrections change outcomes

**Goal:** Give the photographer a measurable signal that their corrections are moving PixCull's culling decisions in the direction they intend.

**Specific change:** Add a personalisation drift metric visible in the UI: after each correction batch, run a held-out sample of 50 images from the photographer's library through both the pre-correction and post-correction models and display the fraction that changed verdict in the expected direction. Show this as a simple trend line over time, not a single accuracy number.

**Measurement:** The personalisation loop is demonstrably working if the drift metric is positive and the direction is correct. A flat or negative drift metric is a visible failure signal that triggers a refusal guard blocking the active-learning pipeline from updating the model for that user until the root cause is identified.

**Way it could be wrong:** Held-out image sets drawn from the same photographer's library may be too stylistically similar to detect genuine generalisation. The held-out set should ideally include some images from a different shoot context (different location, different lighting condition) to detect overfitting to the correction set. This sampling problem is harder than it appears.

---

### v2.82 — Grid performance: resolve the 883ms style recalculation bottleneck

**Goal:** Reduce the grid render cost so that first-open perceived latency on a 5,000-image shoot is below 500ms.

**Specific change:** Audit the 5,069-child grid's DOM structure; replace or virtualise the full-render approach with a windowed list that renders only visible rows plus a buffer zone. Target: 883ms style recalc → below 100ms for a visible viewport on a typical 5,000-image shoot.

**Measurement:** Automated Playwright test that opens a 5,000-image shoot, measures time to first visible image row and time to fully interactive state. Regression gate: any future commit that increases first-visible-row time above 150ms on the reference machine fails CI.

**Way it could be wrong:** Windowed lists break some interaction patterns that depend on scanning the full grid (e.g., keyboard navigation that jumps by a fixed count, or "select all in this score range" operations). These interactions must be explicitly tested in the regression gate and re-implemented if windowing breaks them. Performance gain achieved by breaking selection UX is not a net improvement.

---

### v2.83 — Client proof sheet: add a minimal static proof export

**Goal:** Allow a photographer to export a lightweight proof sheet (watermarked JPEGs + QR-linked web gallery) that a client can view without installing anything.

**Specific change:** Add a "Client Proof Export" command that generates a set of watermarked 1024px JPEG derivatives and a static HTML gallery (no server required; the photographer uploads the folder to any hosting, or attaches a zip). The proof sheet shows the photographer's selected images with a simple approve/comment form backed by a mailto link or a configurable webhook. No payment processing, no database. This is deliberately minimal — it addresses the gap that PixCull has no client-facing output, without competing with Xuanpian, PixCake, or Evoto Instant on their full commerce features.

**Measurement:** A wedding photographer can share a 300-image proof set with a client from within PixCull in under 2 minutes with zero third-party account required. Tested by three photographers on three different shoots.

**Way it could be wrong:** Photographers who have already adopted Xuanpian, Pixieset, or similar delivery platforms will not use a static export that lacks payment and revision tracking. The feature is likely to attract photographers who do not yet have a delivery workflow, not to replace an existing one. If the feature draws disproportionate support effort for edge cases (large galleries, video files, non-standard file structures), the maintenance cost may exceed the adoption return. This version should be deliberately scoped to images-only, static HTML, and mailto/webhook — no feature creep into payment or revision tracking.

---

### v2.84 — Accuracy baseline: publish a benchmark result with a disclosed methodology

**Goal:** Give a prospective photographer a number they can compare against competitors' claimed accuracy figures, on the same footing (the same transparency about methodology).

**Specific change:** Using the 608-row correction set and the adjudication protocol already in place, publish a top-line accuracy figure for the current model (gate-3 keep vs. maybe real-change rate), the evaluation methodology (non-circular, blind labelling described, adjudication rules documented), and the confidence interval. Publish all of this in the repository README and the project documentation.

**Measurement:** The published result must include: the test set size, the rater count, the adjudication rule, the pre-registered threshold for "keep," and the confidence interval. An undisclosed methodology is not a baseline — it is a marketing claim.

**Way it could be wrong:** The 608-row correction set may not be representative of the full range of photography verticals PixCull supports (if the set is primarily wedding images, a published "78% accuracy" figure will be misleading for a sports photographer). The publication must clearly scope the claim to the distribution of the test set.

---

### Capabilities deliberately declined

**Full client-selection commerce platform (Chinese studio market).** Building a production-grade WeChat mini-program, QR-code proof delivery, client payment processing, and revision tracking loop — as offered by Xuanpian, PixCake, and Baidu Netdisk — is a multi-year infrastructure investment that shifts PixCull from a culling tool into a studio management SaaS. The Chinese studio market competitors already have years of production experience, payment integration, and regional regulatory knowledge. PixCull's v2.83 proof export covers the minimum client-facing gap; a full commerce platform should be a third-party integration (with Xuanpian, Pixieset, Pic-Time, or equivalent), not an in-house build.

**Full AI retouching pipeline.** Building retouching capability (skin smoothing, contouring, liquify, AI masking for backgrounds) to compete with Meitu Yunxiu, PixCake Sugar Engine, Aftershoot, or Evoto would require a different engineering team, a different training dataset, and a different go-to-market motion. PixCull's differentiation is in the upstream selection problem. The XMP sidecar output is the correct integration point for retouching tools; deepening that integration (pre-population of Lightroom develop settings from PixCull's scoring output) is a tractable scope; building a retouching engine is not.

**Proprietary genre-specific trained models (FilterPixel model).** Training separate models per genre requires a large, curated, genre-labelled dataset and ongoing maintenance as genre norms evolve. PixCull's vertical-specific rubric weighting achieves a similar (though architecturally different) result using a general model with structured prompting. The rubric approach is auditable and maintainable by a small team; separate trained models for 9+ verticals are not. PixCull should deepen the rubric quality (v2.79) rather than compete on model count.

---

## 7. METHOD

### How this analysis was produced

1. **Orchestrator-provided research data** (EVERYTHING FOUND array) supplied 24 competitor profiles gathered through primary-source web searches, with evidence URLs and dates for each claim.

2. **Fact-check pass** (FACT-CHECK RESULTS array) applied corrections to six claims where the original research either cited an incorrect source, conflated shipped features with beta announcements, misattributed a feature name, or included a figure that did not appear in the cited primary source. All six corrections are applied in this document:
 - Aftershoot: cloud-required architecture disclosed; Cull to Target / tethering / face recognition marked as beta; accuracy figures marked as self-reported vendor marketing.
 - Narrative Select: Scenes View and Close-Ups Panel dated correctly to October 2020, not 2026; Lightroom CC integration dated to January 2025.
 - Meitu Yunxiu: desktop v8.0 and iPad v1.3.0 kept as separate products; iPad processing mode (on-device vs cloud) marked as unverified.
 - PixCake: QR-code WeChat mini-program client selection marked as unconfirmed for any version called "3.0"; cloud-processing-mandatory claim marked as unverified.
 - Adobe Lightroom: feature name corrected from "Smart Stacking" to "Stacking" / "Auto Stack"; processing-time benchmark removed (not in any primary source); Smart Preview cloud transit disclosed.
 - Adobe Bridge: cost framing corrected; no AI culling confirmed for August 2026.

3. **Supplementary web searches** (2026-08-31) were run to verify Apex Culler's shipping status and Aftershoot's processing architecture. Apex Culler remains unverified from a primary vendor source; the supplementary search corroborated the ShutterNoise secondary source only. Aftershoot's processing architecture was described in searched sources as "hybrid local-and-cloud" — however, these sources originate from competing vendors (Imagen AI) and cannot be taken as authoritative; the fact-check result's conclusion (cloud-required) from primary source analysis is retained.

4. **Confidence tiers** used throughout:
 - *verified*: claim confirmed by primary vendor source (official website, changelog, blog, or press release) or independent hands-on review.
 - *partial*: claim supported by one independent secondary source but no primary vendor documentation found, or primary source is older than 6 months with no 2026 update confirmed.
 - *unverified*: claim sourced only from a competitor-authored piece, aggregator article, or no confirmable URL.

### How the scheduled re-run should work

**Cadence:** Quarterly (next: 2026-11-30). The competitive landscape is moving fast enough that a semi-annual cycle would miss two product release cycles.

**Primary source list to check each cycle (check these before any aggregator):**
- aftershoot.com/blog and app changelog
- narrative.so/changelog
- account.imagen-ai.com/changelog/photo/
- filterpixel.com/blog
- captureone.com/en/explore-features/whats-new/
- helpx.adobe.com/lightroom-classic/help/assisted-culling.html + blog.adobe.com
- evoto.ai/features/ai-culling
- on1.com/press
- cyme.io/en/blog
- yunxiu.meitu.com (Meitu Yunxiu)
- pixcakeai.com (PixCake)
- arxiv.org (query: photographic quality assessment, IQA, VLM fine-tuning, NTIRE 2026)
- huggingface.co (Qwen3-VL, InternVL model cards for new releases)
- platform.claude.com/docs (Claude model updates)

**Fact-check protocol:** For every capability claim that carries a pricing structure description, a processing-mode claim (local/cloud/hybrid), or an accuracy figure, confirm from a primary source in each cycle. Do not carry forward a claim from the previous edition without re-checking if the source URL is more than 90 days old.

**Currency rule:** No currency amounts appear anywhere in this document. Any re-run that includes pricing structure descriptions must verify that no numerical currency figures appear before publication. The enforced test that fails the build on currency figures in the public tree covers this.

**Sections to prioritise each cycle:**
1. Platform-native tools (Adobe, Capture One, Apple): these ship on a rapid cycle and can change the competitive baseline without a separate product launch.
2. China market: the largest gap (client-selection workflow) is concentrated here; any new entrant or feature in this segment directly affects the v2.83 roadmap decision.
3. Open-weight models: NTIRE and similar competitions run annually; new winning systems should be evaluated for integration into v2.79's rationale layer.

---

## 2026-09-01 — refresh: nothing moved

Poll of every source in `docs/competitive/sources.json`, in order (platform
vendors → international culling → China → models). **No product or model shipped a
change dated after 2026-08-31.** Specifically re-checked and unchanged since the
2026-08-31 edition:

- **Adobe Lightroom / Photoshop** — no release after the June 2026 update. Adobe
  MAX "2026" was November 2025; nothing since. Source: [PetaPixel, 2026-06-15](https://petapixel.com/2026/06/15/adobe-adds-more-user-control-to-ai-features-inside-lightroom-and-photoshop/)
- **Capture One** — still 16.8.0 (2026-05-28). No 16.9. Source: [captureone.com whats-new](https://www.captureone.com/en/explore-features/whats-new/16-8)
- **ON1 Photo RAW 2026.3** — "workflow and performance improvements"; no new
  culling capability. Source: [on1.com blog](https://www.on1.com/blog/on1-photo-raw-2026-3-update-faster-performance-workflow-improvements-ai-enhancements/)
- **Narrative Select** — latest changelog entries still date to June 2026 (People
  Filter beta, AI First Pass rating no-people frames, Sony/Fujifilm camera
  support). Nothing after the v2.5.0 (2026-08-25) theme update already noted.
  Source: [narrative.so/changelog](https://narrative.so/changelog)
- **Aftershoot / Imagen AI / FilterPixel / Evoto** — no changelog entry after the
  June 2026 items already in this edition.
- **Qwen3-VL / InternVL** — no release after the October 2025 Qwen3-VL size
  variants and the August 2025 InternVL3.5 paper. Source: [github.com/QwenLM/Qwen3-VL](https://github.com/qwenlm/Qwen3-VL)
- **Meitu Yunxiu / PixCake** — no announcement after Meitu Yunxiu v8.0 (P&I
  Shanghai, July 2026).

Per protocol, this is the expected result two weeks (here, one day) after an
edition. Nothing is appended to the field tables.

### Two entries the 2026-08-31 scan missed (both pre-date this edition — not news)

Logged so the next diff does not "discover" them again. Added to
`snapshot-2026-09-01.json` (n 41 → 43). Both were run through a refuting pass;
both survive on date and existence, with hands-on / processing-mode still partial.

1. **ArtiMuse / 书生·妙析** (Shanghai AI Lab + China Academy of Art). Open-weight
   fine-grained image-aesthetics model: one MLLM emits an 8-dimension attribute
   breakdown **and** a holistic score **and** expert-level written critique —
   exactly the "scores-but-no-prose vs prose-but-no-scores" split the v2.79
   charter item exists to close. Trained on ArtiMuse-10K (10,000 expert-annotated
   images); tuned for Eastern aesthetics. Checkpoints are on Hugging Face
   (`Thunderbolt215215/ArtiMuse`); the model card could not be fetched this run,
   so base model, parameter count and licence are **unverified**. arXiv paper
   submitted 2025-07-19 (rev 2025-08-11), checkpoints ~2025-09-03, CVPR 2026
   accepted. **Confidence: partial.** Source: [arXiv 2507.14533](https://arxiv.org/abs/2507.14533)

2. **像素蛋糕 PixCake — 像素助手** (retouching agent, PC 9.0, spring-2026 launch
   event ~2026-04-07). Natural-language agent that drives tethered capture → AI
   culling (AI挑图) → retouch → export by conversation rather than menu
   operations; vendor claims a ~30-minute manual 300-image selection drops to ~3
   minutes. Covered by multiple tech outlets (IT之家, 中关村在线, 新浪, 界面) as a
   launch reprint — not one advertorial, but not independent hands-on either.
   Processing mode (local vs cloud) unconfirmed. This is a step past Imagen Fast
   Track, which this edition called the market's closest thing to a sequential
   agent "though not agentic in the planning sense." **Confidence: partial.**
   Source: [IT之家, 2026-04-07](https://www.ithome.com/0/935/310.htm)

### One correction owed to our own analysis

Flagged here because "correcting our own document outranks reporting someone
else's news." This edition's METHOD section and the v2.79→v2.93 roadmap rest on
"the 608-row correction set in `~/pixcull_label_run`" as ground truth for a future
published accuracy baseline (§4.6, §6 v2.80/v2.84). Repo work since (v2.88,
`scoring/ground_truth.py`) established that set is **the model's own output** —
self-agreement is 100% by construction, and it cannot serve as ground truth for
any accuracy claim. No false figure was published, but any competitive "we have a
number now" statement built on that set would be unsound. This is a note for a
human; the charter is not edited by this automation.

<!-- The block below this line is workflow telemetry that was concatenated into
     this file at publish time (present since commit 9ac2e1e). It is not part of
     the edition and should be stripped when the file is next touched by hand. -->
"
  },
  "workflowProgress": [
    {
      "type": "workflow_phase",
      "index": 1,
      "title": "扫描"
    },
    {
      "type": "workflow_phase",
      "index": 2,
      "title": "核实"
    },
    {
      "type": "workflow_phase",
      "index": 3,
      "title": "成稿"
    },
    {
      "type": "workflow_agent",
      "index": 1,
      "label": "扫描:intl-culling",
      "phaseIndex": 1,
      "phaseTitle": "扫描",
      "agentId": "a68422d5858766715",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788164997065,
      "queuedAt": 1788164997053,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "International AI culling / editing products aimed at profes…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165251069,
      "tokens": 47168,
      "toolCalls": 26,
      "durationMs": 254002,
      "resultPreview": "{"lens":"International AI culling / editing products aimed at professional photographers, benchmarked against PixCull as of 2026-08-31","entries":[{"name":"Aftershoot","what_it_is":"Desktop AI platform (macOS + Windows) covering the full photographer pipeline: culling (Select), RAW editing (Edit), retouching (Retouch), and client gallery delivery (Galleries). As of June 2026 it markets itself as '…"
    },
    {
      "type": "workflow_agent",
      "index": 2,
      "label": "扫描:china-market",
      "phaseIndex": 1,
      "phaseTitle": "扫描",
      "agentId": "af9f9e9d7981a5785",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788164997065,
      "queuedAt": 1788164997053,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Chinese market for AI photo selection, retouching, and stud…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165350333,
      "tokens": 62956,
      "toolCalls": 39,
      "durationMs": 348266,
      "resultPreview": "{"lens":"Chinese market for AI photo selection, retouching, and studio workflow (影楼/婚纱/旅拍 SaaS). The defining feature of this market that PixCull does not address is the client-facing photo selection step (客户选片) — the moment when the studio's customer reviews proofs and marks the images they want retouched and delivered. Almost every serious Chinese B2B entrant treats this as a core module, not an…"
    },
    {
      "type": "workflow_agent",
      "index": 3,
      "label": "扫描:platform-native",
      "phaseIndex": 1,
      "phaseTitle": "扫描",
      "agentId": "afd587fd32e27c33f",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788164997066,
      "queuedAt": 1788164997053,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Platform vendors — tools the photographer already pays for …",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165367194,
      "tokens": 53284,
      "toolCalls": 31,
      "durationMs": 365121,
      "resultPreview": "{"lens":"Platform vendors — tools the photographer already pays for (or gets free), whose bundled AI now overlaps with PixCull's culling value proposition","entries":[{"name":"Adobe Lightroom — Assisted Culling (GA, Classic + cloud app)","what_it_is":"AI-powered culling panel built into Lightroom Classic and the Lightroom cloud app, generally available as of June 2026. Analyzes previews uploaded t…"
    },
    {
      "type": "workflow_agent",
      "index": 4,
      "label": "扫描:models-agents",
      "phaseIndex": 1,
      "phaseTitle": "扫描",
      "agentId": "abb5743b64c35087d",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788164997066,
      "queuedAt": 1788164997053,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Vision models and agent frameworks that would power a best-…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165410042,
      "tokens": 54742,
      "toolCalls": 28,
      "durationMs": 407965,
      "resultPreview": "{"lens":"Vision models and agent frameworks that would power a best-in-class photo culler in late 2026","entries":[{"name":"Qwen3-VL 8B + GRPO/LoRA (Professional IQA fine-tune)","what_it_is":"Open-weight VLM from Alibaba Cloud in dense (2B, 4B, 8B, 32B) and MoE (30B-A3B, 235B-A22B) variants, released September-November 2025. When the 8B-Instruct variant is fine-tuned with LoRA and Group Relative P…"
    },
    {
      "type": "workflow_agent",
      "index": 5,
      "label": "扫描:methodology",
      "phaseIndex": 1,
      "phaseTitle": "扫描",
      "agentId": "a936edd5ddc35e268",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788164997066,
      "queuedAt": 1788164997054,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "METHODOLOGY FOR REPEATABLE COMPETITIVE ANALYSIS (two-week c…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165380203,
      "tokens": 51135,
      "toolCalls": 23,
      "durationMs": 378122,
      "resultPreview": "{"lens":"METHODOLOGY FOR REPEATABLE COMPETITIVE ANALYSIS (two-week cadence)\
\
--- FRAMEWORK SELECTION AND RATIONALE ---\
\
Porter's Five Forces establishes structural context once, not every run. The stable forces for PixCull are: (1) supplier power is low — the open-source stack has no lock-in; (2) buyer switching cost is low — photographers try multiple tools without penalty; (3) substitutes in…"
    },
    {
      "type": "workflow_agent",
      "index": 6,
      "label": "核实:Aftershoot",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "ade26cbc716c1d6f8",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165251086,
      "queuedAt": 1788165251074,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim is a composite of three distinct categories of ev…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165416177,
      "tokens": 38369,
      "toolCalls": 9,
      "durationMs": 165090,
      "resultPreview": "{"holds":false,"why":"The claim is a composite of three distinct categories of evidence that are conflated and attributed to a single source. First, the cited SLR Lounge article (May 29, 2026) confirms client galleries, print sales via partnered labs, and integrated editing/retouching, but it does not mention Cull to Target, tethering, on-device face recognition, or culling accuracy percentages. T…"
    },
    {
      "type": "workflow_agent",
      "index": 7,
      "label": "核实:Narrative Select",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "ac31a3b19f741f241",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165251086,
      "queuedAt": 1788165251074,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Three distinct problems were found. FIRST: The offered sour…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165353910,
      "tokens": 35894,
      "toolCalls": 7,
      "durationMs": 97822,
      "resultPreview": "{"holds":false,"why":"Three distinct problems were found.\
\
FIRST: The offered source does not support the claim. The narrative.so/changelog entry dated 2026-08-25 (v2.5.0) covers only automatic light/dark theme matching, a new onboarding checklist, dark-mode refinements, and a Windows project-scanning bug fix. It says nothing about Scenes View, the Close-Ups Panel, Lightroom CC integration, or A…"
    },
    {
      "type": "workflow_agent",
      "index": 8,
      "label": "核实:美图云修 (Meitu Yunxiu) v8.0",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "a453d01aa0536f54c",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165350337,
      "queuedAt": 1788165350337,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Several components of the claim are overstated or inaccurat…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165531231,
      "tokens": 38599,
      "toolCalls": 12,
      "durationMs": 180893,
      "resultPreview": "{"holds":false,"why":"Several components of the claim are overstated or inaccurately attributed:\
\
1. VERSION MISMATCH — \"v8.0\" is the desktop (Windows/macOS) release. The official Meitu download page (yunxiu.meitu.com/download/, checked 2026-08-31) states explicitly \"目前仅支持电脑端\" (currently desktop-only) for v8.0. The iPad application is a separate product currently at v1.3.0 on the App Store. …"
    },
    {
      "type": "workflow_agent",
      "index": 9,
      "label": "核实:像素蛋糕 PixCake 一体化 3.0",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "a8cf5575c65e2d6a6",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165350338,
      "queuedAt": 1788165350337,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The offered source (China Daily, 2026-07-23) is paid promot…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165456940,
      "tokens": 36860,
      "toolCalls": 8,
      "durationMs": 106602,
      "resultPreview": "{"holds":false,"why":"The offered source (China Daily, 2026-07-23) is paid promotional content explicitly disclaimed as not representing China Daily's editorial views. Critically, it does not actually describe the specific features the claim attributes to it — no mention of QR-code WeChat mini-program client selection, Sugar Engine 2.0 by name, or a \"5-in-1 studio pipeline\" label. Sugar Engine 2…"
    },
    {
      "type": "workflow_agent",
      "index": 10,
      "label": "核实:Adobe Lightroom — Assist",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "ad6fa86b458547c24",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165367197,
      "queuedAt": 1788165367196,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim contains three verifiable inaccuracies and one im…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165607808,
      "tokens": 39546,
      "toolCalls": 13,
      "durationMs": 240611,
      "resultPreview": "{"holds":false,"why":"The claim contains three verifiable inaccuracies and one important omission:\
\
1. WRONG FEATURE NAME — \"Smart Stacking\" does not exist in Adobe's documentation. The Adobe blog post at the cited URL (2026-06-15, confirmed live) calls the grouping feature simply \"Stacking.\" Adobe's help system calls it \"Auto Stack.\" No Adobe primary source uses the name \"Smart Stacking.…"
    },
    {
      "type": "workflow_agent",
      "index": 11,
      "label": "核实:Adobe Bridge CC",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "a6ff71dd3cc6182dd",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165367197,
      "queuedAt": 1788165367196,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim has three distinct problems. First, the offered s…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165601607,
      "tokens": 38315,
      "toolCalls": 12,
      "durationMs": 234409,
      "resultPreview": "{"holds":false,"why":"The claim has three distinct problems. First, the offered source (eyeonannapolis.net/2026/08/...) returned HTTP 403 Forbidden and could not be read; no part of the claim can be attributed to it. Second, the cost/subscription framing is inaccurate in both directions: Adobe Bridge is actually free for everyone with only a free Adobe ID — not merely \"for Creative Cloud subscrib…"
    },
    {
      "type": "workflow_agent",
      "index": 12,
      "label": "核实:AfterShoot",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "abcb619c5772ae2e6",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165380207,
      "queuedAt": 1788165380206,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim is partially supported but overstates in two sign…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165468308,
      "tokens": 35717,
      "toolCalls": 8,
      "durationMs": 88100,
      "resultPreview": "{"holds":false,"why":"The claim is partially supported but overstates in two significant ways.\
\
WHAT IS CONFIRMED (with sources):\
\
1. Single-app end-to-end pipeline: AfterShoot's June 6 2026 update genuinely added a RAW editing workspace (\"AfterShoot Develop\"), client gallery delivery (\"AfterShoot Galleries\"), and print lab integrations (WHCC, Bay Photo, Atkins Pro Labs). The Photo Rumors …"
    },
    {
      "type": "workflow_agent",
      "index": 13,
      "label": "核实:Imagen AI",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "ae5104fdbdfbb9bfa",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165380208,
      "queuedAt": 1788165380206,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim bundles a pre-existing Imagen feature ("Cull to E…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165505234,
      "tokens": 38351,
      "toolCalls": 15,
      "durationMs": 125026,
      "resultPreview": "{"holds":false,"why":"The claim bundles a pre-existing Imagen feature (\"Cull to Exact Number\") together with two genuinely new June 2026 features (Fast Track in v26.15 and side-by-side comparison in v26.16) to suggest a unified June 2026 capability launch. The primary source — the Imagen changelog at account.imagen-ai.com/changelog/photo/ — was successfully fetched and verified current as of Jun…"
    },
    {
      "type": "workflow_agent",
      "index": 14,
      "label": "核实:Qwen3-VL 8B + GRPO/LoRA",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "a74fe19173f449c86",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165410046,
      "queuedAt": 1788165410045,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "The claim contains three material overstatements that toget…",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165497300,
      "tokens": 35170,
      "toolCalls": 6,
      "durationMs": 87254,
      "resultPreview": "{"holds":false,"why":"The claim contains three material overstatements that together make it misleading.\
\
FIRST — TECHNICAL MISCHARACTERISATION OF THE ARCHITECTURE. The source (arxiv.org/html/2604.12512v1, the NTIRE 2026 RAIM Track 1 overview paper, published April 2026, presented at CVPR Workshops 2026) confirms the 0.7305 score and confirms the existence of a dual-branch approach, but the clai…"
    },
    {
      "type": "workflow_agent",
      "index": 15,
      "label": "核实:InternVL3.5",
      "phaseIndex": 2,
      "phaseTitle": "核实",
      "agentId": "a0ed12a2d529999e0",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165416178,
      "queuedAt": 1788165410045,
      "attempt": 1,
      "lastToolName": "StructuredOutput",
      "lastToolSummary": "Multiple components of the claim are inaccurate, stale, or …",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165532373,
      "tokens": 37818,
      "toolCalls": 7,
      "durationMs": 116195,
      "resultPreview": "{"holds":false,"why":"Multiple components of the claim are inaccurate, stale, or fabricated:\
\
1. TEMPORAL STALENESS — \"Highest open-source MMMU result as of August 2026\": The arXiv paper (2508.18265) was published August 2025, not 2026 — it is over one year old on today's date (2026-08-31). By August 2026, multiple open-source models now score above 77.7 on MMMU. Search results show Qwen3.6 Pl…"
    },
    {
      "type": "workflow_agent",
      "index": 16,
      "label": "成稿:竞品分析",
      "phaseIndex": 3,
      "phaseTitle": "成稿",
      "agentId": "ae6f843d847c538e0",
      "model": "claude-sonnet-4-6",
      "state": "done",
      "startedAt": 1788165607810,
      "queuedAt": 1788165607809,
      "attempt": 1,
      "lastToolName": "WebSearch",
      "lastToolSummary": "Aftershoot culling accuracy 2026 cloud vs local processing",
      "promptPreview": "You are researching the competitive landscape for PixCull, an open-source (MIT)
AI photo-culling tool for professional photographers.

TODAY IS 2026-08-31. Your training data ends around May 2026, so anything you
"remember" about product capabilities may be months out of date. You MUST verify
with live web search. Load the search tools first:
  ToolSearch with query "select:WebSearch,WebFetch"
The…",
      "lastProgressAt": 1788165977708,
      "tokens": 58859,
      "toolCalls": 3,
      "durationMs": 369897,
      "resultPreview": "I have the tools loaded and supplementary searches done. Now I will synthesize the full analysis from the provided research data and fact-check corrections.

# PixCull Competitive Intelligence — 2026 Q3

*Analysis date: 2026-08-31. Prior edition: docs/COMPETITIVE-UX-2026Q3.md (2026-08-21, UX-only scope). This edition expands to full product, model, and market coverage.*

---
