"use strict";
let token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
history.replaceState(null, "", location.pathname);
let snapshot = null,
  pending = false,
  historyLoaded = false;
const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};
const stamp = (s) =>
  s
    ? new Date(s).toLocaleString(undefined, { timeZoneName: "short" })
    : "Unknown";
const ms = (n) =>
  n === null
    ? "Unknown"
    : n < 0
      ? "Invalid time"
      : n > 86400000
        ? `${(n / 86400000).toFixed(1)} days`
        : `${Math.round(n).toLocaleString()} ms`;
function notice(text) {
  $("notice").textContent = text;
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, ...options.headers },
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Inspection unavailable");
  return data;
}
function render(data) {
  snapshot = data;
  $("dashboard").hidden = false;
  $("login").hidden = true;
  $("source").textContent =
    data.source === "SYNTHETIC" ? "SYNTHETIC TOUR" : "RECORDED SIMULATOR";
  $("source-label").textContent = data.label;
  $("capture").textContent =
    `Captured ${stamp(data.captured_at)} · Source timestamps are not refreshed`;
  $("updated").textContent = `Inspected ${stamp(data.server_at)}`;
  const cards = data.channels.map((c) => {
    const card = node("article", undefined, "channel");
    const head = node("div", undefined, "channel-head");
    head.append(node("span", c.name), node("span", c.connection, "pill muted"));
    card.append(
      head,
      node("p", `${c.symbol || "No quote"} · at capture`, "sub"),
    );
    const dl = node("dl");
    for (const [k, v] of [
      ["Quote age now", ms(c.quote_age_ms)],
      ["Transport delay", ms(c.transport_delay_ms)],
      ["Clock uncertainty", ms(c.clock_uncertainty_ms)],
      ["Telemetry", c.telemetry_status],
    ])
      dl.append(node("dt", k), node("dd", v));
    card.append(
      dl,
      node(
        "div",
        `${c.freshness.replaceAll("_", " ")} · entry blocked`,
        "freshness",
      ),
    );
    return card;
  });
  $("channel-cards").replaceChildren(...cards);
  const feed = data.telemetry_source;
  $("feed-status").textContent =
    feed.status === "NOT_CONFIGURED"
      ? "Snapshot only · no telemetry file configured"
      : `Telemetry file: ${feed.status} · sequence ${feed.sequence ?? "unknown"} · ${feed.provenance || "retained evidence only"}. No broker collector is attached.`;
  if (!incidentBrowsing) renderIncidents(data.incidents);
  const selected = $("selected").value;
  $("selected").replaceChildren(
    new Option("Workspace questions", ""),
    ...data.records.map(
      (r) => new Option(`${r.kind} · ${r.id.slice(0, 8)}`, r.id),
    ),
  );
  if (data.records.some((r) => r.id === selected))
    $("selected").value = selected;
  renderRecords();
  $("blockers").replaceChildren(...data.blockers.map((b) => node("li", b)));
  const c = data.calendar;
  $("calendar-message").textContent = c.message;
  const details = node("dl");
  for (const [label, value] of [
    [
      "Reminder",
      c.reminder_due
        ? "Review needed"
        : "Not due — source freshness unverified",
    ],
    ["Last reviewed", stamp(c.last_reviewed_at)],
    ["Review due", stamp(c.review_due_at)],
    ["Upcoming releases", c.upcoming_event_count ?? "Unknown"],
  ])
    details.append(node("dt", label), node("dd", value));
  $("calendar-details").replaceChildren(...details.childNodes);
  $("calendar-events").replaceChildren(
    node(
      "p",
      `Upcoming schedule: showing ${data.calendar_events.shown} of ${data.calendar_events.total} (including cancellations)`,
    ),
    ...data.calendar_events.events.map((event) =>
      node(
        "p",
        `${event.release} · ${stamp(event.scheduled_at)} · ${event.status}`,
        "news-item",
      ),
    ),
  );
  const news = data.records.filter(
    (r) => r.kind === "health" || r.kind === "news",
  );
  $("news").replaceChildren(
    ...news.map((r) =>
      node(
        "div",
        Object.entries(r.facts)
          .map(([k, v]) => `${k}: ${v ?? "Unknown"}`)
          .join(" · "),
        "news-item",
      ),
    ),
  );
  if (!news.length)
    $("news").append(node("p", "No news/provider evidence in this snapshot."));
}
function renderRecords() {
  const query = $("evidence-search").value.trim().toLowerCase();
  const list = snapshot.records.filter(
    (r) =>
      ($("kind").value === "all" || r.kind === $("kind").value) &&
      JSON.stringify([r.id, r.kind, r.facts, r.provenance])
        .toLowerCase()
        .includes(query),
  );
  $("evidence-count").textContent =
    `${list.length} of ${snapshot.records.length} projected records`;

  $("empty").hidden = !!list.length;
  $("records").replaceChildren(
    ...list.map((r) => {
      const b = node("button", undefined, "record");
      b.type = "button";
      b.setAttribute("aria-label", `Inspect ${r.kind} ${r.id.slice(0, 8)}`);
      const summary = node("span", undefined, "record-summary");
      summary.append(
        node(
          "span",
          Object.entries(r.facts)
            .filter(([k]) => !["cutoff", "checked_at"].includes(k))
            .map(([k, v]) => `${k}: ${v ?? "Unknown"}`)
            .join(" · "),
        ),
        node("span", `${stamp(r.at)} · ${r.provenance}`, "record-meta"),
      );
      b.append(
        node("span", r.kind, "record-kind"),
        summary,
        node("span", "↗", "record-arrow"),
      );
      if (r.kind === "lesson")
        summary.append(
          node(
            "span",
            `Memory eligible at cutoff: ${r.memory_eligible ? "yes" : "no"}`,
            "record-meta",
          ),
        );
      b.addEventListener("click", () => {
        showTrace(r.id);
        $("selected").value = r.id;
        $("question").value = "Explain this recorded evidence";
        $("advisor").scrollIntoView({ behavior: "smooth", block: "nearest" });
        $("question").focus();
      });
      return b;
    }),
  );
}
async function refresh() {
  if (!token) {
    $("login").hidden = false;
    notice("Open the private local session URL to inspect the workspace.");
    return;
  }
  try {
    render(await api("/api/overview"));
    if (!historyLoaded) {
      const history = await api("/api/history");
      historyLoaded = true;
      $("history-note").textContent =
        `${history.total} saved answers · latest ${history.shown} loaded. Questions are not retained.`;
      if (
        !pending &&
        $("messages").children.length === 1 &&
        history.answers.length
      )
        $("messages").replaceChildren(...history.answers.map(answer));
    }
    document.body.classList.remove("unavailable");
    notice("");
  } catch (e) {
    document.body.classList.add("unavailable");
    notice(
      `Service unavailable — displayed data is last received, not current. ${e.message}`,
    );
  }
}
function answer(data) {
  const article = node("article", undefined, "answer");
  article.append(
    node("strong", "Advisor · evidence reader"),
    node("p", data.text),
  );
  if (data.rationale)
    article.append(
      node("small", "Original recorded rationale · untrusted quotation"),
      node("p", data.rationale),
    );
  if (data.validation_reason)
    article.append(node("p", `Recorded validation: ${data.validation_reason}`));
  for (const c of data.citations || []) {
    const block = node("div", undefined, "citation");
    block.append(
      node("strong", `${c.kind} · ${stamp(c.recorded_at)}`),
      node("p", c.facts.map((f) => `${f.name}: ${f.value}`).join("\n")),
      node("code", `Record ${c.record_id}\nSHA-256 ${c.sha256}`),
      node(
        "p",
        `${c.provenance} · ${c.unresolved_references.length} unresolved references`,
      ),
    );
    article.append(block);
  }
  for (const b of data.blockers || []) article.append(node("p", b));
  for (const c of data.channels || [])
    article.append(
      node(
        "p",
        `${c.name}: ${c.freshness}; age ${ms(c.quote_age_ms)}; delay ${ms(c.transport_delay_ms)}`,
      ),
    );
  article.append(node("small", `Read-only · ${stamp(data.answered_at)}`));
  return article;
}
$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (pending || !token) return;
  pending = true;
  $("send").disabled = true;
  $("question").disabled = true;
  const question = $("question").value;
  $("messages").append(node("article", question, "question"));
  const data = {
    request_id: crypto.randomUUID(),
    question,
    record_id: $("selected").value || null,
    language: $("language").value,
  };
  try {
    $("messages").append(
      answer(
        await api("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }),
      ),
    );
    $("question").value = "";
  } catch (err) {
    $("messages").append(
      node(
        "article",
        `Could not retrieve evidence: ${err.message}. No trading action was performed.`,
        "answer",
      ),
    );
  } finally {
    pending = false;
    $("send").disabled = false;
    $("question").disabled = false;
    $("messages").scrollTop = $("messages").scrollHeight;
  }
});
document.querySelectorAll("[data-question]").forEach((b) =>
  b.addEventListener("click", () => {
    $("selected").value = "";
    $("question").value = b.dataset.question;
    $("chat-form").requestSubmit();
  }),
);
$("kind").addEventListener("change", renderRecords);
$("evidence-search").addEventListener("input", renderRecords);
$("refresh").addEventListener("click", refresh);
$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  token = $("token").value.trim();
  $("token").value = "";
  refresh();
});
$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("ics").files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    $("upload-result").textContent = "File exceeds 2 MiB limit.";
    return;
  }
  $("upload").disabled = true;
  try {
    await api("/api/calendar", {
      method: "POST",
      headers: { "Content-Type": "text/calendar" },
      body: await file.arrayBuffer(),
    });
    $("upload-result").textContent =
      "Saved locally. Calendar coverage remains unqualified.";
    await refresh();
  } catch (err) {
    $("upload-result").textContent = `Upload rejected: ${err.message}`;
  } finally {
    $("upload").disabled = false;
  }
});
let incidentBrowsing = false,
  incidentBefore = null,
  incidentQuery = "",
  incidentRequest = 0,
  traceRequest = 0;
function renderIncidents(data) {
  incidentBefore =
    "next_before" in data
      ? data.next_before
      : data.total > data.shown
        ? data.events.at(-1)?.id
        : null;
  $("incident-older").disabled = !incidentBefore;
  $("incident-count").textContent =
    `${data.total} matching retained transitions · showing ${data.shown}`;
  $("incident-events").replaceChildren(
    ...data.events.map((event) => {
      const e = node("article", undefined, "incident");
      e.append(
        node("strong", `${event.kind}: ${event.state}`),
        node("span", stamp(event.at)),
        node("code", `Evidence ${event.evidence}`),
      );
      return e;
    }),
  );
}
async function loadIncidents(before = null) {
  const request = ++incidentRequest;
  incidentBrowsing = true;
  $("incident-older").disabled = true;
  try {
    const params = new URLSearchParams({ q: incidentQuery });
    if (before) params.set("before", before);
    const data = await api(`/api/incidents?${params}`);
    if (request === incidentRequest) renderIncidents(data);
  } catch (e) {
    if (request === incidentRequest)
      $("incident-count").textContent =
        `Incident search unavailable: ${e.message}`;
  }
}
$("incident-search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  incidentQuery = $("incident-query").value.trim();
  loadIncidents();
});
$("incident-older").addEventListener("click", () =>
  loadIncidents(incidentBefore),
);
$("incident-latest").addEventListener("click", () => {
  incidentQuery = "";
  $("incident-query").value = "";
  loadIncidents();
});
async function showTrace(id) {
  const request = ++traceRequest;
  $("trace-panel").hidden = false;
  $("trace-status").textContent = "Loading recorded links…";
  $("trace-nodes").replaceChildren();
  $("trace-links").replaceChildren();
  try {
    const data = await api(`/api/trace/${encodeURIComponent(id)}`);
    if (request !== traceRequest) return;
    $("trace-status").textContent =
      `${data.nodes.length} linked records · ${data.missing.length} missing references · cutoff ${stamp(data.cutoff)}`;
    $("trace-nodes").replaceChildren(
      ...data.nodes.map((r) => {
        const e = node("article", undefined, "incident");
        e.append(
          node("strong", `${r.kind} · ${stamp(r.at)}`),
          node("code", `Record ${r.id}`),
          node(
            "p",
            r.details_available
              ? JSON.stringify(r.facts)
              : "Details outside the dashboard projection",
          ),
          node("code", `SHA-256 ${r.sha256}`),
        );
        return e;
      }),
    );
    $("trace-links").replaceChildren(
      ...data.links.map((l) =>
        node(
          "p",
          `${l.source} → ${l.target} · ${l.relation} · ${l.resolved ? "record present" : "MISSING"}`,
          "trace-link",
        ),
      ),
    );
  } catch (e) {
    if (request === traceRequest)
      $("trace-status").textContent =
        `Evidence trail unavailable: ${e.message}`;
  }
}
$("export").addEventListener("click", async () => {
  $("export").disabled = true;
  try {
    const report = await api("/api/report");
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    );
    const link = node("a");
    link.href = url;
    link.download = "fx-talanta-inspection.json";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice(
      "Inspection report exported. It is bounded offline evidence, not qualification or a full archive.",
    );
  } catch (e) {
    notice(`Export unavailable: ${e.message}`);
  } finally {
    $("export").disabled = false;
  }
});
window.addEventListener("hashchange", () => {
  const supplied = new URLSearchParams(location.hash.slice(1)).get("token");
  if (!supplied) return;
  token = supplied;
  history.replaceState(null, "", location.pathname);
  historyLoaded = false;
  refresh();
});
refresh();
setInterval(() => {
  if (!document.hidden) refresh();
}, 5000);
