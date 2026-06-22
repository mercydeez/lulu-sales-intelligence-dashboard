// Types + helpers for the Developer Portal (public API catalog, code-snippet and
// embed-snippet generators). Kept pure so it's trivial to type-check and reuse.

export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  scopes: string[];
  last_used_at: string | null;
  request_count: number;
  revoked: boolean;
}

export interface Hook {
  id: number;
  url: string;
  events: string[];
  active: boolean;
  last_status: number | null;
  failure_count: number;
  last_delivery_at?: string | null;
}

export interface Delivery {
  id: number;
  event: string;
  status_code: number | null;
  ok: boolean;
  error: string | null;
  delivered_at: string | null;
}

export interface PublicEndpoint {
  method: 'GET' | 'POST';
  path: string;
  desc: string;
  scope: string;
  // Example JSON body for POST endpoints (shown/sent in the playground).
  sampleBody?: Record<string, unknown>;
}

// The public, API-key-authenticated surface (mirrors backend routes/public_api.py).
export const PUBLIC_ENDPOINTS: PublicEndpoint[] = [
  { method: 'GET', path: '/api/public/v1/kpis', desc: 'Tenant KPIs (units + AED revenue)', scope: 'read' },
  { method: 'GET', path: '/api/public/v1/forecast/projection', desc: 'Forward revenue projection', scope: 'read' },
  { method: 'GET', path: '/api/public/v1/inventory/reorder-suggestions', desc: 'Forecast-driven reorder suggestions', scope: 'read' },
  { method: 'GET', path: '/api/public/v1/findings', desc: 'Diagnostics findings (what\'s going wrong)', scope: 'read' },
  { method: 'POST', path: '/api/public/v1/ai/ask', desc: 'Ask Sage (NL→SQL, grounded answer)', scope: 'read', sampleBody: { question: 'What was revenue last week?' } },
  { method: 'GET', path: '/api/public/v1/branding', desc: 'White-label branding for embeds', scope: 'read' },
];

const KEY_PLACEHOLDER = 'lsk_YOUR_API_KEY';

export function curlSnippet(base: string, ep: PublicEndpoint, key: string): string {
  const k = key || KEY_PLACEHOLDER;
  if (ep.method === 'POST') {
    const body = JSON.stringify(ep.sampleBody ?? {});
    return `curl -X POST ${base}${ep.path} \\\n  -H "X-API-Key: ${k}" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
  }
  return `curl ${base}${ep.path} \\\n  -H "X-API-Key: ${k}"`;
}

export function jsSnippet(base: string, ep: PublicEndpoint, key: string): string {
  const k = key || KEY_PLACEHOLDER;
  const opts =
    ep.method === 'POST'
      ? `{\n  method: 'POST',\n  headers: { 'X-API-Key': '${k}', 'Content-Type': 'application/json' },\n  body: JSON.stringify(${JSON.stringify(ep.sampleBody ?? {})}),\n}`
      : `{ headers: { 'X-API-Key': '${k}' } }`;
  return `const res = await fetch('${base}${ep.path}', ${opts});\nconst data = await res.json();\nconsole.log(data);`;
}

export function pythonSnippet(base: string, ep: PublicEndpoint, key: string): string {
  const k = key || KEY_PLACEHOLDER;
  if (ep.method === 'POST') {
    return `import requests\nr = requests.post(\n  "${base}${ep.path}",\n  headers={"X-API-Key": "${k}"},\n  json=${JSON.stringify(ep.sampleBody ?? {})},\n)\nprint(r.json())`;
  }
  return `import requests\nr = requests.get("${base}${ep.path}", headers={"X-API-Key": "${k}"})\nprint(r.json())`;
}

// A self-contained, copy-paste embeddable "Ask Sage" widget. Scoped to the key;
// theme via accentColor (pull the tenant's brand from /api/public/v1/branding).
export function embedSnippet(base: string, key: string, accent = '#0f766e'): string {
  const k = key || KEY_PLACEHOLDER;
  return `<div id="sage-widget"></div>
<script>
(function () {
  var API = "${base}", KEY = "${k}", ACCENT = "${accent}";
  var root = document.getElementById("sage-widget");
  root.style.cssText = "max-width:420px;font-family:system-ui,sans-serif;border:1px solid #e5e7eb;border-radius:12px;padding:16px";
  root.innerHTML =
    '<div style="font-weight:600;margin-bottom:8px">Ask Sage</div>' +
    '<div style="display:flex;gap:8px"><input id="sage-q" placeholder="Ask about your data…" ' +
    'style="flex:1;padding:8px;border:1px solid #d1d5db;border-radius:8px"/>' +
    '<button id="sage-go" style="background:' + ACCENT + ';color:#fff;border:0;border-radius:8px;padding:8px 12px">Ask</button></div>' +
    '<div id="sage-a" style="margin-top:12px;white-space:pre-wrap;color:#374151"></div>';
  async function ask() {
    var q = document.getElementById("sage-q").value;
    var a = document.getElementById("sage-a");
    a.textContent = "Thinking…";
    try {
      var res = await fetch(API + "/api/public/v1/ai/ask", {
        method: "POST",
        headers: { "X-API-Key": KEY, "Content-Type": "application/json" },
        body: JSON.stringify({ question: q })
      });
      var d = await res.json();
      a.textContent = d.answer || d.detail || "No answer.";
    } catch (e) { a.textContent = "Error contacting Sage."; }
  }
  document.getElementById("sage-go").onclick = ask;
})();
</script>`;
}
