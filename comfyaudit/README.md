# ComfyAudit

A ComfyUI custom node pack that audits the workflow you're looking at, and tells
you what you'd otherwise find out the hard way: which models it pulls in, whether
you're allowed to sell the output, where the weights came from, how much of it a
human has to babysit, and what will break when it moves off the machine it was
built on.

Built for the moment a workflow arrives from an artist, a vendor, or a Discord
link, and someone has to decide whether it can go near a paying job.

Two ways to run it. **Extensions → ComfyAudit → Audit this workflow** gives you a
report on the current canvas without touching the graph:

```
Commercial clearance : BLOCKED — 4 models forbid commercial use
Production risk      : 97/100 (Severe)
Automation index     : 17/100 (Hands-on artist tool)
```

Or drop the **Audit This Workflow** node in and hit Run, and it audits the graph
it's sitting in — no configuration, because ComfyUI hands any node that asks for
them the running prompt and the UI workflow.

## Install

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/dughogan/dughogan comfyaudit-tmp
mv comfyaudit-tmp/comfyaudit . && rm -rf comfyaudit-tmp
pip install -r comfyaudit/requirements.txt   # only needed for the Claude node
```

Restart ComfyUI. The auditor itself is standard library only, so it can't break
your environment; the single dependency is the Anthropic SDK, and without it
every other node still works.

## Nodes

| Node | What it does |
|---|---|
| **Audit This Workflow** | Audits the running graph. Outputs the report as Markdown and JSON, plus risk score, automation index and clearance verdict as separate sockets. |
| **Claude Review** | Has Claude investigate the audit — see below. |
| **Audit Gate** | Aborts the run when the audit finds a blocker, so a workflow that can't be delivered never renders. |
| **Save Audit Report** | Writes the report into your ComfyUI output folder as HTML, Markdown or JSON. |

A pipeline gate is four nodes: `Audit This Workflow → Audit Gate → your graph`,
with `Save Audit Report` hanging off the side so every render has a clearance
sheet next to it.

## What it checks

**Models.** Every weight the graph loads, including the ones a simple parser
misses: models named by custom nodes with no published schema, `embedding:`
references buried inside prompt text, inline `<lora:...>` syntax, LoRA strengths
paired with the right file, and hosted models that only exist on a vendor's
servers.

**Licences.** Each model is matched against a curated knowledge base and reported
with its commercial-use position, whether a fee applies, the specific
restrictions, and a link to the source. The traps it's built to catch are the
ones that are easy to miss:

| Model | Why it matters |
|---|---|
| FLUX.1 [dev] | Non-commercial. The restriction covers the **outputs**, not just the weights. |
| Stable Diffusion 3.5 | Free commercially only under $1M total company revenue — all revenue, not AI revenue. |
| InsightFace (antelopev2, buffalo) | Non-commercial, and **inherited** by IP-Adapter FaceID, InstantID and every face-swap pack built on it. |
| CodeFormer | Non-commercial (S-Lab 1.0), and it arrives silently bundled inside face-restore packs. |
| Ultralytics YOLO | AGPL-3.0. Ultralytics' position is that internal pipeline use needs an Enterprise Licence or your tool goes open source. |
| BRIA RMBG | Non-commercial without a paid agreement, and it's in half the matting workflows on the internet. |
| HunyuanVideo | Territory **excludes the EU, UK and South Korea**. |
| 4x-UltraSharp and friends | Popular community upscalers are frequently CC BY-NC-SA. |
| Depth Anything V2 | Base and Large are CC BY-NC; only Small is Apache 2.0. |

**Provenance.** Where each weight came from — offline from a bundled index of
500+ known model files, and optionally live from HuggingFace, Civitai and the
Comfy Registry. Gated repositories, run-time auto-downloads and untraceable
community merges are called out individually.

**Prompts.** Positive and negative are worked out from the sampler wiring rather
than guessed from node titles, so it stays right through reroutes, conditioning
combines, ControlNet stacks and subgraphs.

**Assets.** Every external input, marked by how it's supplied: an upload widget a
person clicks, a path baked into the graph, an absolute path from someone's
D: drive, or a URL fetched at run time.

**Dependencies.** Which custom node packs are needed, who wrote them, how many
stars they have, when they were last touched, whether the workflow pins a
version, and whether two installed packs claim the same node class name.

**Production risk.** Findings across licensing, provenance, reproducibility,
dependency, runtime and data handling, each with evidence and something you can
act on.

## The automation index

The question this answers is "can I queue this and walk away, or does an artist
have to sit with it?". The score is built from *touchpoints* — concrete places a
human has to act — weighted by how often they have to act:

```
| Weight | When     | Touchpoint                          | Why
|    1.2 | per-run  | Write or edit 2 static prompt(s)    | Typed into the node that consumes it...
|    1.0 | per-run  | Supply image for Plate              | 'image' is an upload widget...
|    0.6 | per-run  | Advance 1 fixed seed(s) by hand     | control_after_generate is 'fixed'...
|    0.6 | per-run  | 1 node(s) are muted or bypassed     | Switches someone flips between runs...
```

Only the recurring stages drive the headline number; setup is real but you pay it
once, so it's reported separately rather than held against the workflow forever.
It also distinguishes a prompt typed into a dedicated string node — which a
submission script can overwrite through the `/prompt` API — from one buried
inside an encoder, because those are very different amounts of work to automate.

## Running inside ComfyUI makes it sharper

The same engine works on a bare `.json` file, but in-process it stops guessing:

- **Custom node widgets get real names.** Offline, a widget on a node nobody
  published a schema for is `widget_0`. In-process the node is asked directly, so
  it's `lora_name_1`, with the model folder recovered by matching the combo's
  options against `folder_paths`.
- **Model presence is a fact.** Every weight is checked against the folders
  ComfyUI actually reads, so "this won't run here" is a finding rather than an
  unchecked assumption.
- **In-house packs stop reading as unidentified.** A pack the public registry has
  never heard of is a critical finding from a JSON file, and correctly so. Live,
  it's resolved to `custom_nodes/<dir>` with the installed version read off disk.

## The Claude review

The rule engine is deterministic and knows exactly what it knows. What it can't
do is recognise that `juggernautXL_v9Rundiffusion.safetensors` is an SDXL
community merge, notice that a prompt names a living artist, or work out what to
swap in when the upscaler turns out to be non-commercial.

Those are judgement calls, so the **Claude Review** node hands them to an agent
that *investigates* — it reads the models, the prompts, the findings and the
packs through tools, checks the auditor's own licence knowledge base so its
answers stay consistent, and looks at what's installed locally before proposing a
substitution you'd actually be able to make today.

Four modes:

- **identify** — name the models the rules couldn't, and what their lineage
  implies for commercial use. A FLUX.1 [dev] fine-tune can't be more permissive
  than FLUX.1 [dev].
- **clearance** — read the prompt text for the risks no licence check catches:
  real people, trademarks, copyrighted characters, living artists named as a
  style reference.
- **remediate** — propose specific replacements and an ordered plan.
- **full** — all three.

You can also just ask it something: *"can this go on the farm overnight?"*

Everything it concludes is kept separate from the rule findings, labelled
model-derived, and carries its own confidence. A wrong licence claim is worse
than an honest "unknown", and the prompt says so.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or run: ant auth login
```

Uses `claude-opus-5` with adaptive thinking. Web search is on by default so it
can check a licence at source — **turn it off when the workflow content is
confidential**, and note that the review sends model names and prompt text to the
Anthropic API either way. That's inherent in the feature; it's opt-in for exactly
that reason.

## Command line

The same auditor runs headless, for CI and batch work. From the directory *above*
the pack:

```bash
# a report on stdout
python -m comfyaudit.core.cli audit workflow.json

# a self-contained HTML clearance sheet to archive with the show
python -m comfyaudit.core.cli audit workflow.json -f html -o audits/sh0120.html

# verify weights exist, and hash them
python -m comfyaudit.core.cli audit workflow.json --models-dir /opt/ComfyUI/models

# add the Claude pass
python -m comfyaudit.core.cli audit workflow.json --claude --models-dir /opt/ComfyUI/models

# ask a question instead
python -m comfyaudit.core.cli audit workflow.json --ask "what stops this being batched?"

# audit a folder; non-zero exit if anything critical turns up
python -m comfyaudit.core.cli audit shots/ -o audits/ --fail-on critical
```

It reads both workflow formats — the UI graph from **Save**, the API format from
**Export (API)** — and will pull the workflow straight out of a PNG that ComfyUI
rendered:

```bash
python -m comfyaudit.core.cli audit render_00042_.png
```

## Studio licence overrides

The bundled knowledge base is a starting point, not gospel. Add your own weights,
or overrule ours, in the same format, and point the node's `licence_overrides`
widget (or `--licences`) at it:

```json
{
  "licences": {
    "inhouse": {
      "name": "Facility internal",
      "commercial_use": "yes",
      "fee": "none",
      "summary": "Trained in house on cleared material. Cleared for all client work."
    }
  },
  "models": [
    {
      "id": "house-skin-loras",
      "family": "House skin detail LoRAs",
      "licence": "inhouse",
      "match": { "filename": ["studio_skin_detail"] },
      "confidence": "high"
    }
  ]
}
```

## How it knows what it knows

Everything works offline, from data built into the package:

- **Core node schemas** scraped from a real ComfyUI release with an AST pass over
  `nodes.py`, `comfy_extras/` and `comfy_api_nodes/`, handling both the legacy
  `INPUT_TYPES` form and the newer `io.Schema` form. This is what makes it
  possible to read a UI-format workflow at all: `widgets_values` is a bare
  positional array, so without the real widget order you can't tell a prompt from
  a filename from a seed.
- **Custom node index** from the ComfyUI-Manager registry: ~5,900 packs and
  ~40,000 node class names, with stars and last-commit dates.
- **Known model index** mapping common weight filenames to upstream repos.
- **Licence knowledge base** in `core/knowledge/data/licences.json`, with a
  `source` link and a `confidence` on every entry.

Rebuild the catalogs against a newer ComfyUI whenever you like:

```bash
python tools/build_catalog.py --comfyui /path/to/ComfyUI --manager /path/to/manager-json
```

## Reading the output honestly

Licence verdicts are derived from **filenames**, which aren't authoritative —
anyone can rename a checkpoint. So every verdict reports the pattern it matched
and a confidence level, and a `low` confidence verdict is a prompt to check the
source page, not an answer. The matcher is deliberately strict about boundaries:
`ae.safetensors` matches the FLUX autoencoder, not every file ending in `_vae`.

Against the 588 official ComfyUI workflow templates, the current rules produce 16
`blocked` verdicts, all genuine (FLUX dev variants, SDXL Turbo, Depth Anything V2
Large, 4x-UltraSharp).

This is an engineering tool, not legal advice. It exists to surface the questions
worth putting to your legal or production team before a delivery, and to make the
answers reproducible six months later when someone asks why a shot looks the way
it does.

## Development

```bash
python -m pytest        # 109 tests
```

The agent tests point a real Anthropic client at a local stub of the Messages
API, so the tool schemas, the multi-turn loop and the paused-turn restart are
exercised rather than mocked. The ComfyUI-facing tests run against a stand-in
`nodes` / `folder_paths` pair, since ComfyUI itself can't be imported in a test
environment.

## Licence

MIT.
