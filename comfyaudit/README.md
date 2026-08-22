# comfyaudit

Point it at a ComfyUI workflow and it tells you what you would otherwise find out
the hard way: which models it pulls in, whether you are allowed to sell the
output, where the weights came from, how much of it a human has to babysit, and
what will break when it moves off the machine it was built on.

Built for the moment a workflow arrives from an artist, a vendor, or a Discord
link, and someone has to decide whether it can go near a paying job.

```
$ comfyaudit audit beauty-pass.json

====================================================================
 beauty-pass.json
====================================================================
 Commercial clearance : BLOCKED
 Production risk      : 97/100 (Severe)
 Automation index     : 17/100 (Hands-on artist tool)
 Models / packs       : 10 / 3
 Findings             : 1 critical, 4 high, 4 medium, 2 low, 1 info
   [critical] 4 model(s) forbid commercial use
   [high] 1 absolute path(s) hard-coded in the graph
====================================================================
```

## What it actually checks

**Models.** Every weight the graph loads, including the ones no simple parser
finds: models named by custom nodes that have no published schema, `embedding:`
references buried inside prompt text, inline `<lora:...>` syntax, LoRA strengths
paired with the right file, and hosted models that only exist on a vendor's
servers.

**Licences.** Each model is matched against a curated knowledge base covering the
families that actually turn up in production, and reported with the commercial-use
position, whether a fee applies, the specific restrictions, and a link to the
source. The traps it is built to catch are the ones that are easy to miss:

| Model | Why it matters |
|---|---|
| FLUX.1 [dev] | Non-commercial. The restriction covers the **outputs**, not just the weights. |
| Stable Diffusion 3.5 | Free commercially only under $1M total company revenue - measured on all revenue, not AI revenue. |
| InsightFace (antelopev2, buffalo) | Non-commercial, and the restriction is **inherited** by IP-Adapter FaceID, InstantID and every face-swap pack built on it. |
| CodeFormer | Non-commercial (S-Lab 1.0), and it arrives silently bundled inside face-restore node packs. |
| Ultralytics YOLO detectors | AGPL-3.0. Ultralytics' position is that internal pipeline use needs an Enterprise Licence or your tool goes open source. |
| BRIA RMBG | Non-commercial without a paid BRIA agreement, and it is in half the matting workflows on the internet. |
| HunyuanVideo | Territory **excludes the EU, UK and South Korea**. |
| 4x-UltraSharp and friends | Popular community upscalers are frequently CC BY-NC-SA. |
| Depth Anything V2 | Base and Large are CC BY-NC; only Small is Apache 2.0. |

**Provenance.** Where each weight came from, resolved offline from a bundled index
of 500+ known model files, and optionally live from HuggingFace, Civitai (by exact
SHA-256 when a local models folder is available) and the Comfy Registry. Gated
repositories, run-time auto-downloads and untraceable community merges are called
out individually.

**Prompts.** Positive and negative are worked out from the sampler wiring rather
than guessed from node titles, so it stays right through reroutes, conditioning
combines, ControlNet stacks and subgraphs. Wildcards, `{a|b}` alternation and
embedded dependencies are extracted alongside.

**Assets.** Every external input, marked by how it is supplied: an upload widget a
person clicks, a path baked into the graph, an absolute path from someone's
D: drive, or a URL fetched at run time.

**Dependencies.** Which custom node packs are needed, who wrote them, how many
stars they have, when they were last touched, whether the workflow pins a version,
and whether two installed packs claim the same node class name.

**Automation.** See below.

**Production risk.** Findings across licensing, provenance, reproducibility,
dependency, runtime and data-handling, each with evidence and something you can
actually do about it.

## The automation index

The question this is trying to answer is "can I queue this and walk away, or does
an artist have to sit with it?". The score is built from *touchpoints* - concrete
places a human has to act - weighted by how often they have to act:

- `setup` - once per machine (install a pack, repoint a path, get an API key)
- `per-run` - every single generation (pick an image, retype a prompt, bump a seed)
- `review` - somebody has to look at the result
- `per-output` - somebody has to save or pick the keeper

Only the recurring stages drive the headline number; setup is real but you pay it
once, so it is reported separately rather than held against the workflow forever.

```
| Weight | When     | Touchpoint                          | Why
|    1.2 | per-run  | Write or edit 2 static prompt(s)    | Typed into the node that consumes it...
|    1.0 | per-run  | Supply image for Plate              | 'image' is an upload widget...
|    0.6 | per-run  | Advance 1 fixed seed(s) by hand     | control_after_generate is 'fixed'...
|    0.6 | per-run  | 1 node(s) are muted or bypassed     | Switches someone flips between runs...
```

It also distinguishes a prompt typed into a dedicated string node - which a
submission script can overwrite through the `/prompt` API - from one buried inside
an encoder, because those are very different amounts of work to automate.

## Install

```bash
pip install -e .        # no dependencies; Python 3.9+
```

Nothing is pulled in beyond the standard library, so it installs next to a ComfyUI
environment without disturbing it.

## Use

```bash
# a report on stdout
comfyaudit audit workflow.json

# a self-contained HTML report you can archive with the show
comfyaudit audit workflow.json -f html -o audits/sh0120.html

# machine-readable, for a pipeline
comfyaudit audit workflow.json -f json -o audit.json

# verify the weights actually exist on this machine, and hash them
comfyaudit audit workflow.json --models-dir /opt/ComfyUI/models

# resolve provenance and licences live (cached on disk for a week)
comfyaudit audit workflow.json --online --models-dir /opt/ComfyUI/models

# audit a whole folder of workflows
comfyaudit audit shots/ -o audits/

# gate a submission: non-zero exit if anything critical is found
comfyaudit audit workflow.json --fail-on critical --quiet
```

It reads both workflow formats - the UI graph you get from **Save**, and the API
format from **Export (API)** - and will also pull the workflow straight out of the
metadata of a PNG that ComfyUI rendered:

```bash
comfyaudit audit render_00042_.png
```

## Studio licence overrides

The bundled knowledge base is a starting point, not gospel. Add your own weights,
or overrule ours, in the same format:

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

```bash
comfyaudit audit workflow.json --licences /shows/config/licences.json
```

## How it knows what it knows

Everything works offline, from data built into the package:

- **Core node schemas** scraped from a real ComfyUI release with an AST pass over
  `nodes.py`, `comfy_extras/` and `comfy_api_nodes/`, handling both the legacy
  `INPUT_TYPES` form and the newer `io.Schema` form. This is what makes it
  possible to read a UI-format workflow correctly at all: `widgets_values` is a
  bare positional array, so without the real widget order you cannot tell a
  prompt from a filename from a seed.
- **Custom node index** from the ComfyUI-Manager registry: ~5,900 packs and
  ~40,000 node class names, with stars and last-commit dates.
- **Known model index** mapping common weight filenames to their upstream repos.
- **Licence knowledge base** in `comfyaudit/knowledge/data/licences.json`, with a
  `source` link and a `confidence` on every entry.

Rebuild the catalogs against a newer ComfyUI whenever you like:

```bash
python tools/build_catalog.py --comfyui /path/to/ComfyUI --manager /path/to/manager-json
```

## Reading the output honestly

Licence verdicts are derived from **filenames**, which are not authoritative -
anyone can rename a checkpoint. So every verdict reports the pattern it matched on
and a confidence level, and a `low` confidence verdict is a prompt to go and check
the source page, not an answer. The matcher is deliberately strict about
boundaries: `ae.safetensors` matches the FLUX autoencoder, not every file ending
in `_vae`.

Against the 588 official ComfyUI workflow templates, the current rules produce 16
`blocked` verdicts, all of which are genuine (FLUX dev variants, SDXL Turbo,
Depth Anything V2 Large, 4x-UltraSharp).

This is an engineering tool, not legal advice. It exists to surface the questions
worth putting to your legal or production team before a delivery, and to make the
answers reproducible six months later when someone asks why a shot looks the way
it does.

## Development

```bash
python -m pytest              # 70 tests
python tools/make_example.py  # regenerate the example workflows
```

## Licence

MIT.
