/* Praxis frontend — vanilla JS, no build step */

// ---------------------------------------------------------------------------
// Role management
// ---------------------------------------------------------------------------
const ROLES = { PM: "pm", ALGO: "algo" };

function getRole() {
  return localStorage.getItem("praxis_role") || ROLES.PM;
}
function setRole(role) {
  localStorage.setItem("praxis_role", role);
  document.dispatchEvent(new CustomEvent("rolechange", { detail: role }));
}

function apiFetch(path, options = {}) {
  const role = getRole();
  return fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Role": role,
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  }).then(async (r) => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return r.json();
  });
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function html(strings, ...vals) {
  return strings.reduce((acc, s, i) => acc + (vals[i - 1] ?? "") + s);
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (typeof c === "string") e.insertAdjacentHTML("beforeend", c);
    else if (c) e.appendChild(c);
  }
  return e;
}

function toast(msg, type = "info") {
  const colors = { info: "bg-blue-600", success: "bg-emerald-600", error: "bg-red-600" };
  const t = el(
    "div",
    { class: `fixed bottom-6 right-6 z-50 px-5 py-3 rounded-xl text-white text-sm shadow-xl ${colors[type]} transition-all duration-300` },
    msg
  );
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 3000);
}

// ---------------------------------------------------------------------------
// Phase badge
// ---------------------------------------------------------------------------
const PHASE_STYLE = {
  idle:        "bg-zinc-100 text-zinc-600",
  exploring:   "bg-blue-100 text-blue-700",
  simplifying: "bg-amber-100 text-amber-700",
  regressing:  "bg-violet-100 text-violet-700",
  promoting:   "bg-emerald-100 text-emerald-700",
  blocked:     "bg-red-100 text-red-700",
};
const PHASE_ICON = {
  idle: "○", exploring: "⟳", simplifying: "⬡",
  regressing: "✓", promoting: "▲", blocked: "✕",
};
function phaseBadge(phase) {
  const cls = PHASE_STYLE[phase] || "bg-zinc-100 text-zinc-500";
  const icon = PHASE_ICON[phase] || "?";
  return `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}">${icon} ${phase}</span>`;
}

// ---------------------------------------------------------------------------
// Outcome badge
// ---------------------------------------------------------------------------
const OUTCOME_STYLE = {
  improved:   "text-emerald-600 font-semibold",
  simplified: "text-blue-600 font-semibold",
  neutral:    "text-zinc-400",
  regressed:  "text-red-500 font-semibold",
  failed:     "text-red-700 font-bold",
};
function outcomeBadge(outcome) {
  const cls = OUTCOME_STYLE[outcome] || "text-zinc-400";
  return `<span class="${cls}">${outcome}</span>`;
}

// ---------------------------------------------------------------------------
// Role switcher (rendered in every page header)
// ---------------------------------------------------------------------------
function mountRoleSwitcher(container) {
  const render = (role) => {
    container.innerHTML = `
      <div class="flex items-center gap-2 bg-zinc-100 rounded-full p-1">
        <button id="btn-pm" class="px-3 py-1 rounded-full text-sm font-medium transition-all ${role === "pm" ? "bg-white shadow text-zinc-800" : "text-zinc-500 hover:text-zinc-700"}">
          🗂 Product
        </button>
        <button id="btn-algo" class="px-3 py-1 rounded-full text-sm font-medium transition-all ${role === "algo" ? "bg-white shadow text-zinc-800" : "text-zinc-500 hover:text-zinc-700"}">
          ⚙ Algorithm
        </button>
      </div>`;
    $("#btn-pm", container).onclick = () => { setRole("pm"); render("pm"); applyRoleVisibility("pm"); };
    $("#btn-algo", container).onclick = () => { setRole("algo"); render("algo"); applyRoleVisibility("algo"); };
  };
  render(getRole());
}

function applyRoleVisibility(role) {
  $$("[data-role]").forEach((el) => {
    const allowed = el.dataset.role.split(",").map((s) => s.trim());
    el.style.display = allowed.includes(role) ? "" : "none";
  });
}

// call once on load
document.addEventListener("DOMContentLoaded", () => {
  const rs = $("#role-switcher");
  if (rs) mountRoleSwitcher(rs);
  applyRoleVisibility(getRole());
});
