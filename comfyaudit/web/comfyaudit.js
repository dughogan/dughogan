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

app.registerExtension({
  name: "comfyaudit.panel",
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
      console.log(
        `[comfyaudit] ready — ${live}, licence KB v${status?.knowledge?.licences?.version}, `
        + `Claude ${status?.claude?.available ? "available" : "unavailable: " + status?.claude?.reason}`
      );
    } catch (err) {
      console.warn("[comfyaudit] server routes not reachable:", err);
    }
  },
});
