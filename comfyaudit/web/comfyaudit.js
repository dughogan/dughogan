/**
 * comfyaudit - audit the graph on the canvas from the ComfyUI menu.
 *
 * The node path is for pipelines. This is for the other case: you have a
 * workflow open and want to know whether it can be delivered before you spend
 * an hour rendering with it.
 *
 * ComfyUI's menu API changed between frontend generations, so registration is
 * attempted several ways and whichever lands is the one used.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const PREFIX = "/comfyaudit";
// The pill is toned by operational risk, not by licence. Licence terms are
// reported, never graded, so there is no colour that would be honest for them.
const RISK_TONE = {
  Severe: "#a32e22",
  High: "#a32e22",
  Elevated: "#8a5a12",
  Moderate: "#8a5a12",
  Low: "#2f6b3f",
};

let overlay = null;

/* ------------------------------------------------------------------ */
/* Panel                                                               */
/* ------------------------------------------------------------------ */

function closePanel() {
  if (overlay) {
    overlay.remove();
    overlay = null;
    document.removeEventListener("keydown", onKeydown);
  }
}

function onKeydown(event) {
  if (event.key === "Escape") closePanel();
}

function openPanel(title) {
  closePanel();

  overlay = document.createElement("div");
  Object.assign(overlay.style, {
    position: "fixed",
    inset: "0",
    background: "rgba(0,0,0,.55)",
    zIndex: "10000",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
  });
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closePanel();
  });

  const frame = document.createElement("div");
  Object.assign(frame.style, {
    background: "var(--comfy-menu-bg, #202020)",
    color: "var(--fg-color, #e6e6e6)",
    width: "min(1100px, 100%)",
    height: "min(90vh, 100%)",
    borderRadius: "8px",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    boxShadow: "0 24px 64px -24px rgba(0,0,0,.8)",
  });

  const bar = document.createElement("div");
  Object.assign(bar.style, {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "10px 14px",
    borderBottom: "1px solid var(--border-color, #3a3a3a)",
    flex: "0 0 auto",
  });

  const heading = document.createElement("strong");
  heading.textContent = title;
  heading.style.fontSize = "14px";

  const spacer = document.createElement("div");
  spacer.style.flex = "1";

  const closeButton = document.createElement("button");
  closeButton.textContent = "Close";
  closeButton.className = "comfy-btn";
  closeButton.onclick = closePanel;

  bar.append(heading, spacer, closeButton);

  const body = document.createElement("div");
  Object.assign(body.style, { flex: "1 1 auto", overflow: "auto", minHeight: "0" });

  frame.append(bar, body);
  overlay.append(frame);
  document.body.append(overlay);
  document.addEventListener("keydown", onKeydown);

  return { bar, body, heading, spacer, closeButton };
}

function setStatus(body, message) {
  body.innerHTML = "";
  const box = document.createElement("div");
  Object.assign(box.style, { padding: "28px", fontSize: "14px", lineHeight: "1.6" });
  box.textContent = message;
  body.append(box);
}

function setError(body, message) {
  body.innerHTML = "";
  const box = document.createElement("div");
  Object.assign(box.style, {
    padding: "28px",
    fontSize: "14px",
    lineHeight: "1.6",
    whiteSpace: "pre-wrap",
    color: "#e88a7d",
  });
  box.textContent = message;
  body.append(box);
}

function showReport(body, html) {
  body.innerHTML = "";
  const iframe = document.createElement("iframe");
  Object.assign(iframe.style, { width: "100%", height: "100%", border: "0" });
  // The report is a whole self-contained document; srcdoc keeps it isolated
  // from ComfyUI's own styles rather than fighting them.
  iframe.srcdoc = html;
  body.append(iframe);
}

// A one-glance composition: how the workflow's models divide across licence
// positions, in the order a reader cares about them.
function licenceBrief(summary) {
  const counts = summary.licence_counts || {};
  const order = ["permissive", "conditional", "non-commercial", "unstated"];
  const parts = order.filter((k) => counts[k]).map((k) => `${counts[k]} ${k}`);
  return parts.length ? parts.join(", ") : "no models";
}

function addPill(bar, spacer, summary) {
  const pill = document.createElement("span");
  const tone = RISK_TONE[summary.risk_band] || "#8a5a12";
  Object.assign(pill.style, {
    font: "600 11px ui-monospace, monospace",
    letterSpacing: ".08em",
    textTransform: "uppercase",
    padding: "3px 9px",
    borderRadius: "999px",
    border: `1px solid ${tone}`,
    color: tone,
  });
  pill.textContent = `${summary.models} models · ${licenceBrief(summary)} · risk ${summary.risk} · auto ${summary.automation}`;
  bar.insertBefore(pill, spacer);
}

function addSaveButton(bar, spacer, html, name) {
  const button = document.createElement("button");
  button.textContent = "Save HTML";
  button.className = "comfy-btn";
  button.onclick = () => {
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name}.audit.html`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
  bar.insertBefore(button, spacer.nextSibling);
}

/* ------------------------------------------------------------------ */
/* Requests                                                            */
/* ------------------------------------------------------------------ */

async function post(path, payload) {
  const response = await api.fetchApi(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let data;
  try {
    data = await response.json();
  } catch (err) {
    throw new Error(`Server returned ${response.status} with no JSON body.`);
  }
  if (!response.ok || data.error) {
    throw new Error(data.error || `Server returned ${response.status}.`);
  }
  return data;
}

function graphName() {
  const raw = app.graph?.extra?.workflowName || app.workflowManager?.activeWorkflow?.filename;
  return (raw || "workflow").replace(/\.json$/i, "");
}

async function runAudit({ withClaude = false } = {}) {
  const title = withClaude ? "Workflow audit + Claude review" : "Workflow audit";
  const { bar, body, spacer } = openPanel(title);
  setStatus(
    body,
    withClaude
      ? "Auditing the graph, then asking Claude to investigate. The review makes "
        + "several model calls and can take a minute."
      : "Auditing the graph…"
  );

  let workflow;
  try {
    workflow = app.graph.serialize();
  } catch (err) {
    setError(body, `Could not serialise the graph: ${err.message}`);
    return;
  }

  try {
    const path = withClaude ? `${PREFIX}/review` : `${PREFIX}/audit`;
    const payload = withClaude
      ? { workflow, mode: "full", options: { check_local_models: true } }
      : { workflow, options: { check_local_models: true } };
    const data = await post(path, payload);

    let html = data.html;
    if (withClaude && data.review_markdown) {
      html = injectReview(html, data.review_markdown, data.review);
    }
    showReport(body, html);
    if (data.summary) addPill(bar, spacer, data.summary);
    addSaveButton(bar, spacer, html, graphName());
  } catch (err) {
    setError(body, `${err.message}\n\nCheck the ComfyUI server console for details.`);
  }
}

/**
 * Fold the Claude section into the report page as plain, readable HTML.
 * Deliberately minimal - it inherits the report's own stylesheet.
 */
function injectReview(html, markdown, review) {
  const escape = (text) =>
    String(text).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const label = review && review.ran
    ? `Mode ${escape(review.mode)} · ${escape(review.model)} · ${review.usage?.turns ?? 0} turns`
    : "Not run";

  const section = `
    <div class="sheet">
      <h2><span class="num">7</span>Claude review<span class="count">${label}</span></h2>
      <div class="block warn">
        <p style="margin-top:0"><strong>Model-derived, not rule-derived.</strong>
        Everything below was produced by Claude reading this workflow. Verify before
        acting on it.</p>
        <pre style="white-space:pre-wrap">${escape(markdown)}</pre>
      </div>
    </div>`;

  return html.includes("</body>")
    ? html.replace("</body>", `${section}</body>`)
    : html + section;
}

/* ------------------------------------------------------------------ */
/* Registration                                                        */
/* ------------------------------------------------------------------ */

const COMMANDS = [
  {
    id: "comfyaudit.audit",
    label: "Audit this workflow",
    icon: "pi pi-verified",
    function: () => runAudit({ withClaude: false }),
  },
  {
    id: "comfyaudit.review",
    label: "Audit + Claude review",
    icon: "pi pi-sparkles",
    function: () => runAudit({ withClaude: true }),
  },
];


/* ------------------------------------------------------------------ */
/* Studio profile                                                      */
/* ------------------------------------------------------------------ */

/**
 * The facts about a facility that licence terms turn on.
 *
 * These live in ComfyUI's own settings rather than on a node, because they
 * describe the studio and not the graph: territory and revenue are the same for
 * every workflow on the machine, and asking someone to restate a constant in
 * each one is how it ends up wrong in half of them.
 *
 * All of it is optional. Set nothing and the report describes the licence terms
 * and reaches no verdict, which is the default and a perfectly good answer.
 * Setting them turns that description into a go / no-go with its reasoning
 * shown. The Python side reads these back out of comfy.settings.json; the ids
 * here must match server/settings.py.
 */
const STUDIO_SETTINGS = [
  {
    id: "ComfyAudit.Studio.Territory",
    name: "Territory",
    tooltip:
      "Where work is rendered and deployed. Several open-weight licences "
      + "exclude regions outright — MiniMax H3 excludes the US, EU, UK and "
      + "South Korea — and no fee lifts a territory exclusion.",
    type: "combo",
    options: ["not set", "United States", "European Union", "United Kingdom",
              "South Korea", "Canada", "Australia", "Japan", "China", "India",
              "elsewhere"],
    defaultValue: "not set",
  },
  {
    id: "ComfyAudit.Studio.Revenue",
    name: "Annual revenue",
    tooltip:
      "Total company revenue, not AI-derived revenue. Free use is capped at "
      + "$1M by Stability and $20M by MiniMax; above a cap you need an "
      + "agreement, which is a budget line rather than a blocker.",
    type: "combo",
    options: ["not set", "under $1M", "$1M - $10M", "$10M - $20M",
              "$20M - $100M", "over $100M"],
    defaultValue: "not set",
  },
  {
    id: "ComfyAudit.Studio.Ships",
    name: "What ships",
    tooltip:
      "Copyleft only reaches your own code when something is distributed, so "
      + "this decides whether an AGPL node pack is a non-issue or a serious "
      + "problem.",
    type: "combo",
    options: ["not set", "finished frames to a client",
              "nothing leaves the building", "software containing this workflow",
              "a network service"],
    defaultValue: "not set",
  },
  {
    id: "ComfyAudit.Studio.TrainsModels",
    name: "Outputs train other models",
    tooltip:
      "Several licences forbid this outright and worldwide, with no fee that "
      + "lifts it.",
    type: "boolean",
    defaultValue: false,
  },
  {
    id: "ComfyAudit.Studio.Likeness",
    name: "Real performers involved",
    tooltip:
      "No model licence grants rights in a performer's face — that comes from "
      + "their contract and, increasingly, their union agreement. Turning this "
      + "on makes the report raise it wherever the graph does identity work.",
    type: "boolean",
    defaultValue: false,
  },
  {
    id: "ComfyAudit.Studio.Label",
    name: "Studio name",
    tooltip: "A label for the report: a facility, a show or a client.",
    type: "text",
    defaultValue: "",
  },
].map((setting) => ({ ...setting, category: ["ComfyAudit", "Studio profile", setting.name] }));

/**
 * The facility's record of what it has already decided about.
 *
 * Not part of the profile — that says what the studio is, this says what it has
 * concluded — but it belongs in the same panel for the same reason: it is a
 * property of the installation, not of any one workflow. With a path set, every
 * report leads with what is new rather than restating what was cleared months
 * ago. Written with `comfyaudit registry add`, never automatically.
 */
const REGISTRY_SETTINGS = [
  {
    id: "ComfyAudit.Registry.Path",
    name: "Registry file",
    tooltip:
      "Path to a JSON file recording what this facility has already approved, "
      + "rejected or parked. Optional. With one, a workflow whose models were "
      + "all cleared before says so in a line instead of repeating itself.",
    type: "text",
    defaultValue: "",
    category: ["ComfyAudit", "Registry", "Registry file"],
  },
];

app.registerExtension({
  name: "comfyaudit.panel",
  settings: [...STUDIO_SETTINGS, ...REGISTRY_SETTINGS],
  commands: COMMANDS,
  menuCommands: [{ path: ["Extensions", "ComfyAudit"], commands: COMMANDS.map((c) => c.id) }],

  async setup() {
    // Older frontends have no command palette; give them a plain button.
    const legacyMenu = document.querySelector(".comfy-menu");
    if (legacyMenu && !document.getElementById("comfyaudit-button")) {
      const button = document.createElement("button");
      button.id = "comfyaudit-button";
      button.textContent = "Audit workflow";
      button.title = "comfyaudit: models, licences, automation and production risk";
      button.onclick = () => runAudit({ withClaude: false });
      legacyMenu.append(button);
    }

    try {
      const response = await api.fetchApi(`${PREFIX}/status`);
      const status = await response.json();
      const live = status?.knowledge?.live_introspection ? "live node schemas" : "bundled catalog";
      const studio = status?.studio_profile?.profile_set
        ? status.studio_profile.profile
        : "none set — reports will describe the licences without reaching a verdict";
      const registry = status?.studio_profile?.registry_path || "none set";
      console.log(
        `[comfyaudit] ready — ${live}, licence KB v${status?.knowledge?.licences?.version}, `
        + `Claude ${status?.claude?.available ? "available" : "unavailable: " + status?.claude?.reason}`
        + `\n[comfyaudit] studio profile: ${studio}`
        + `\n[comfyaudit] registry: ${registry}`
      );
    } catch (err) {
      console.warn("[comfyaudit] server routes not reachable:", err);
    }
  },
});
