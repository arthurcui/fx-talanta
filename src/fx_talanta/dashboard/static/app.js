"use strict";
let bootstrap = new URLSearchParams(location.hash.slice(1)).get("token") || "";
let authenticated = false,
  csrf = "",
  sessionEpoch = 0;
history.replaceState(null, "", location.pathname);
let lastIncident = null,
  retryExplanation = null;
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
  const epoch = sessionEpoch;
  const response = await fetch(path, {
    ...options,
    headers: { "X-FX-CSRF": csrf, ...options.headers },
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(
      path === "/api/explain" || path.startsWith("/api/research/")
        ? 60000
        : 8000,
    ),
  });
  const data = await response.json();
  if (epoch !== sessionEpoch) throw new Error("Session changed");
  if (
    response.status === 403 &&
    !path.startsWith("/api/operator/") &&
    path !== "/api/session"
  )
    signedOut();
  if (!response.ok) throw new Error(data.error || "Inspection unavailable");
  return data;
}
function render(data) {
  snapshot = data;
  $("service-status").textContent =
    `Inspection worker: ${data.service.status}; last successful sample ${stamp(data.service.last_sample_at)}. This is not sustained qualification.`;
  $("operator-panel").hidden = !data.operator_enabled;
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
  $("use-model").disabled = !data.model.enabled;
  if (!data.model.enabled) $("use-model").checked = false;
  $("model-status").textContent = data.model.enabled
    ? `Bounded model enabled · ${data.model.reserved_calls}/${data.model.max_calls} calls reserved · ${data.model.unresolved_calls} unresolved; no automatic refunds or retries.`
    : "Model calls disabled; local evidence reader available.";
  const workflow = data.matched_workflow || { status: "NOT_CONFIGURED" };
  const runner = ["RUNNER", "OPERATIONS", "DISPATCH"].includes(
    workflow.source_kind,
  );
  $("workflow-status").textContent =
    `${workflow.status} · ${runner ? "simulation runner (direct read)" : "offline receipt workflow"} · trading disabled`;
  $("workflow-details").replaceChildren();
  if (workflow.receipt_sequence !== undefined) {
    $("workflow-details").append(
      node(
        "p",
        `${workflow.provenance} · ${workflow.observations} observations · ${workflow.decisions} decisions · ${workflow.outcomes} outcomes · ${workflow.revisions} corrections`,
      ),
      node(
        "p",
        `${workflow.missing_decisions} missing decisions · ${workflow.pending_outcomes} pending outcomes. Deadline ${stamp(workflow.deadline)}. These counts are not closed broker trades.`,
      ),
      node(
        "p",
        `Receipt ${workflow.receipt_sequence} · ${workflow.receipt_hash}. Prospective qualification remains unverified.`,
      ),
    );
    if (runner) {
      if (workflow.selector === "RECORDED_MODEL_RESPONSES") {
        Object.entries(workflow.recorded_model_summary || {}).forEach(
          ([arm, m]) => {
            $("workflow-details").append(
              node(
                "p",
                `${arm}: ${m.recorded_replies} recorded replies · ${m.rejected_or_hold} rejected/HOLD · ${m.input_tokens}/${m.output_tokens} reported input/output tokens · known reported model cost USD ${m.known_reported_cost_usd} · ${m.unknown_cost_replies} unknown-cost replies · maximum reported latency ${m.maximum_reported_latency_ms}ms. Recorded simulation evidence; no verified model calls. Model cost is separate from trade P&L.`,
              ),
            );
          },
        );
      }
      $("workflow-details").append(
        node(
          "p",
          `${workflow.normalized_inputs ?? 0} normalized inputs · asserted channels ${(workflow.input_channels || []).join(", ") || "manual fixtures"}. Source provenance is not independently qualified.`,
        ),
      );
      if (workflow.source_queue) {
        const q = workflow.source_queue;
        if (q.model_dispatch) {
          const d = q.model_dispatch;
          $("workflow-details").append(
            node(
              "p",
              `Model dispatch ${d.status}: ${d.reserved_calls}/${d.max_calls} calls reserved · ${d.reserved_tokens}/${d.max_reserved_tokens} tokens reserved · ${d.unresolved_reserved_calls} unresolved reserved calls · ${d.unknown_cost_calls} unknown-cost calls. No automatic refunds or resends; transport unverified.`,
            ),
          );
        }
        $("workflow-details").append(
          node(
            "p",
            `Source queue ${q.status}: ${q.queued} queued / ${q.acknowledged} acknowledged / ${q.pending} pending. Oldest pending age: ${q.oldest_pending_age_seconds ?? "none"}s. Unacknowledged runner commit: ${q.unacknowledged_runner_commit}. Producer liveness UNVERIFIED; source not qualified.`,
          ),
        );
      }
      $("workflow-details").append(
        node(
          "p",
          `Last input ${stamp(workflow.last_input_at)} · receipt age ${workflow.input_age_seconds}s. Receipt age is not quote latency or entry readiness. Selector: ${workflow.selector}.`,
        ),
      );
      Object.entries(workflow.arms || {}).forEach(([name, arm]) => {
        $("workflow-details").append(
          node(
            "p",
            `${name}: last gateway state ${arm.state} · ${arm.entries} attempts · ${arm.open_positions} open / ${arm.closed_simulated_positions} closed simulated positions. No broker trades.`,
          ),
        );
      });
    }
  }
  const study = data.study;
  $("study-results").replaceChildren();
  if (study) {
    $("study-results").append(
      node(
        "p",
        `${study.report.provenance} · ${study.report.result} · source ${study.source_sha256}`,
        "news-item",
      ),
    );
    study.report.comparisons.forEach((c) =>
      $("study-results").append(
        node(
          "p",
          `${c.left} vs ${c.right}: ${c.complete_pairs} complete / ${c.excluded_pairs} excluded pairs; mean net difference USD ${c.mean_net_difference_usd ?? "unknown"}. ${c.uncertainty}`,
          "news-item",
        ),
      ),
    );
  } else $("study-results").append(node("p", "No imported comparison."));
  const latestIncident = data.incidents.events[0]?.id ?? 0;
  if (
    lastIncident !== null &&
    latestIncident > lastIncident &&
    $("alert-changes").checked
  ) {
    const changes = data.incidents.events.filter((e) => e.id > lastIncident);
    $("incident-alert").textContent =
      `New sampled changes: ${changes.map((e) => `${e.kind}: ${e.state}`).join("; ")}. Open incident history for evidence.`;
  }
  lastIncident = latestIncident;
  const ops = data.operations;
  const lines = [
    `Cutoff ${stamp(ops.cutoff)} · ${ops.record_versions} record versions · ${ops.corrections} corrections`,
    `Decisions: ${JSON.stringify(ops.decisions)}`,
    `Operational outcomes: ${JSON.stringify(ops.operational_outcomes)}`,
    `Compliance: ${JSON.stringify(ops.compliance)}`,
    `Known economic labels: ${JSON.stringify(ops.known_economic_labels)} · ${ops.economics_unavailable} unavailable`,
    `Equity / net P&L / drawdown / exposure / open positions: Unknown. ${ops.account_metrics_reason}`,
  ];
  $("operation-summary").replaceChildren(
    ...lines.map((text) => node("p", text, "news-item")),
  );
  const usage = ops.model_usage;
  $("usage-summary").textContent =
    `Recorded traces (including fixtures, not billing): ${usage.distinct_requests} distinct requests; ${usage.conflicting_requests} conflicts excluded; ${usage.input_tokens} input / ${usage.output_tokens} output tokens; maximum latency ${ms(usage.max_latency_ms)}.`;
  $("qualification-gates").replaceChildren(
    ...ops.gates.map((g) =>
      node("p", `${g.id}: ${g.requirement} — ${g.status}`, "news-item"),
    ),
  );
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
  if (!authenticated) {
    $("login").hidden = false;
    return;
  }
  try {
    const overview = await api("/api/overview");
    render(overview);
    await refreshStrategies();
    $("broker-panel").hidden = !overview.broker_view_enabled;
    if (overview.broker_view_enabled) refreshBroker();
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
    node("strong", data.mode || "Advisor · evidence reader"),
    node("p", data.text),
  );
  if (data.status) article.append(node("p", `${data.status}: ${data.reason}`));
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
  if (pending || !authenticated) return;
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
  const useModel = $("use-model").checked;
  if (useModel) {
    retryExplanation = data;
    $("retry-explanation").hidden = false;
  }
  try {
    const value = await api(useModel ? "/api/explain" : "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    $("messages").append(answer(value));
    $("question").value = "";
    if (useModel && value.reason !== "OUTCOME_UNKNOWN_NO_RESEND") {
      retryExplanation = null;
      $("retry-explanation").hidden = true;
    }
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
function signedOut() {
  clearStrategy();
  $("strategy-history").replaceChildren();
  $("lifecycle-milestones").replaceChildren();
  $("lifecycle-gaps").replaceChildren();
  authenticated = false;
  csrf = "";
  sessionEpoch++;
  snapshot = null;
  historyLoaded = false;
  retryExplanation = null;
  $("dashboard").hidden = true;
  $("login").hidden = false;
  $("logout").hidden = true;
  $("logout-all").hidden = true;
  $("operator-token").value = "";
  $("password").value = "";
  $("messages").replaceChildren();
  notice("Signed out. Sign in again or reopen your private launch shortcut.");
}
async function openSession(data) {
  try {
    const result = await api(
      "/api/session",
      data
        ? {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-FX-Session": "1",
            },
            body: JSON.stringify(data),
          }
        : {},
    );
    const local = ["LOCAL_OWNER", "LOCAL_SETUP"].includes(result.mode);
    const setup = result.mode === "LOCAL_SETUP";
    $("login-form").hidden = !local && result.mode !== "OWNER";
    $("login-title").textContent = setup
      ? "Create your workspace sign-in"
      : "Sign in to your workspace";
    $("login-submit").textContent = setup
      ? "Create account and sign in"
      : "Sign in";
    $("password").minLength = setup ? 16 : 1;
    $("password").autocomplete = setup ? "new-password" : "current-password";
    $("password-confirm-label").hidden = !setup;
    $("password-confirm").hidden = !setup;
    $("password-confirm").required = setup;
    $("logout-all").hidden = !(local && result.authenticated);
    $("login-help").textContent = setup
      ? "Choose a username and a passphrase of at least 16 characters. This account is only for this local workspace."
      : local
        ? "Sign in normally. Sessions last up to 30 days, with a 7-day inactivity limit. You can revoke all sessions. Trading remains disabled."
        : result.mode === "OWNER"
          ? "Use your configured owner credentials. Trading remains disabled."
          : "Open your private dashboard launch shortcut. No token needs to be pasted here.";
    authenticated = result.authenticated;
    csrf = result.csrf || "";
    $("logout").hidden = !authenticated;
    await refresh();
  } catch (e) {
    if (data && "bootstrap" in data) return openSession(null);
    notice(e.message);
    $("login").hidden = false;
  }
}
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (
    !$("password-confirm").hidden &&
    $("password-confirm").value !== $("password").value
  ) {
    notice("Passphrases do not match.");
    return;
  }
  const data = { username: $("username").value, password: $("password").value };
  $("password-confirm").value = "";
  $("password").value = "";
  await openSession(data);
});
$("logout").addEventListener("click", async () => {
  try {
    await api("/api/session/logout", { method: "POST" });
    signedOut();
    await openSession(null);
  } catch (e) {
    notice("Sign-out could not be confirmed: " + e.message);
  }
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
$("retry-explanation").addEventListener("click", async () => {
  if (!retryExplanation || pending) return;
  pending = true;
  $("retry-explanation").disabled = true;
  try {
    const value = await api("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(retryExplanation),
    });
    $("messages").append(answer(value));
    if (value.reason !== "OUTCOME_UNKNOWN_NO_RESEND") {
      retryExplanation = null;
      $("retry-explanation").hidden = true;
    }
  } catch (e) {
    notice(
      `Same request remains unresolved: ${e.message}. No new request was created.`,
    );
  } finally {
    pending = false;
    $("retry-explanation").disabled = false;
  }
});
$("study-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("study-file").files[0];
  if (!file || file.size > 16 * 1024 * 1024) {
    $("study-message").textContent = "Study must be at most 16 MiB.";
    return;
  }
  $("study-upload").disabled = true;
  try {
    await api("/api/study", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await file.arrayBuffer(),
    });
    $("study-message").textContent =
      "Validated and retained offline study. No qualification or execution enabled.";
    await refresh();
  } catch (err) {
    $("study-message").textContent =
      `Study rejected; previous result retained. ${err.message}`;
  } finally {
    $("study-upload").disabled = false;
  }
});
let brokerPending = false;
let brokerQuoteExpiry = null;
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(brokerQuoteExpiry);
    const panel = $("broker-quotes");
    if (panel)
      panel.replaceChildren(
        node("p", "Quote display paused — a new server sample is required."),
      );
  } else if (authenticated && !$("broker-panel").hidden) {
    refreshBroker();
  }
});
async function refreshBroker() {
  if (brokerPending) return;
  brokerPending = true;
  const requestedAt = performance.now();
  try {
    const value = await api("/api/broker");
    clearTimeout(brokerQuoteExpiry);
    $("broker-status").textContent =
      `${value.label ?? "Journal"}: ${value.state ?? value.status} · ${value.reason ?? ""} · current positions UNKNOWN; entry blocked`;
    $("broker-details").replaceChildren(
      node(
        "p",
        value.recorded_at
          ? `Recorded ${stamp(value.recorded_at)} · transport at capture: ${value.transport_at_capture ?? "UNKNOWN"} · clock policy at sample: ${value.recorded_clock_policy ?? "UNKNOWN"} · quote freshness: ${value.quote_freshness ?? "UNVERIFIED"} (at server sample)`
          : "No observation",
      ),
      node("p", JSON.stringify(value.snapshot ?? {}), "news-item"),
      node(
        "p",
        value.channels
          ? JSON.stringify(value.channels)
          : "Historical journal source",
      ),
    );
    if (value.quote_observation) {
      const observation = value.quote_observation;
      const panel = node("div");
      panel.id = "broker-quotes";
      panel.append(
        node(
          "p",
          "Original broker quote age — not network latency. Two-second ceiling; trading disabled. Broker clock accuracy is not independently bounded.",
        ),
      );
      let expiresIn = Infinity;
      for (const q of observation.quotes) {
        const age =
          q.age_seconds === null ? "Unknown" : `${q.age_seconds.toFixed(3)} s`;
        const upper =
          q.age_upper_bound_seconds === null
            ? "Unknown"
            : `${q.age_upper_bound_seconds.toFixed(3)} s`;
        panel.append(
          node(
            "p",
            `${q.symbol}: ${q.state} · sampled age ${age} · host-clock upper estimate ${upper}`,
          ),
        );
        if (q.state === "FRESH")
          expiresIn = Math.min(
            expiresIn,
            (2 - q.age_upper_bound_seconds) * 1000,
          );
      }
      $("broker-details").append(panel);
      if (Number.isFinite(expiresIn)) {
        const expire = () => {
          panel.replaceChildren(
            node(
              "p",
              "Quote display expired — awaiting a new server sample. No current freshness inferred.",
            ),
          );
        };
        const remaining = expiresIn - (performance.now() - requestedAt);
        if (remaining <= 0) expire();
        else brokerQuoteExpiry = setTimeout(expire, remaining);
      }
    }
  } catch (e) {
    clearTimeout(brokerQuoteExpiry);
    $("broker-status").textContent =
      `Broker journal unavailable. No current account state inferred. ${e.message}`;
    $("broker-details").replaceChildren();
  } finally {
    brokerPending = false;
  }
}
window.addEventListener("hashchange", () => {
  const supplied = new URLSearchParams(location.hash.slice(1)).get("token");
  if (!supplied) return;
  sessionEpoch++;
  history.replaceState(null, "", location.pathname);
  historyLoaded = false;
  openSession({ bootstrap: supplied });
});
openSession(bootstrap ? { bootstrap } : null);
bootstrap = "";
setInterval(() => {
  if (!document.hidden) refresh();
}, 5000);

let operatorPreview = null;
async function operatorCall(path, data) {
  return api("/api/operator/" + path, {
    method: data ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${$("operator-token").value}`,
      "Content-Type": "application/json",
    },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
}
$("operator-read").addEventListener("click", async () => {
  try {
    const value = await operatorCall("state");
    $("operator-state").textContent = JSON.stringify(value.state, null, 2);
    $("operator-position").replaceChildren(
      new Option("None", ""),
      ...value.state.owned_positions.map((id) => new Option(id, id)),
    );
  } catch (e) {
    $("operator-state").textContent = "Unavailable";
    $("operator-result").textContent = e.message;
  }
});
$("operator-preview").addEventListener("click", async () => {
  operatorPreview = null;
  $("operator-confirm").disabled = true;
  try {
    operatorPreview = await operatorCall("preview", {
      action: $("operator-action").value,
      position_id: $("operator-position").value || null,
    });
    $("operator-preview-text").textContent =
      `SIMULATOR ONLY: ${operatorPreview.text}. Expires ${stamp(operatorPreview.expires_at)}`;
    $("operator-confirmation").value = "";
    $("operator-confirm").disabled = false;
  } catch (e) {
    $("operator-preview-text").textContent = "No valid preview";
    $("operator-result").textContent = e.message;
  }
});
$("operator-confirm").addEventListener("click", async () => {
  if (!operatorPreview) return;
  $("operator-confirm").disabled = true;
  try {
    const result = await operatorCall("confirm", {
      request_id: operatorPreview.request_id,
      confirmation: $("operator-confirmation").value,
    });
    $("operator-result").textContent =
      `Simulator: ${result.status} / ${result.reason}. Trading disabled.`;
  } catch (e) {
    $("operator-result").textContent =
      `${e.message}. Retain this preview to inspect the same request; do not create another action.`;
  } finally {
    $("operator-confirm").disabled = false;
  }
});
$("operator-revoke").addEventListener("click", async () => {
  try {
    await operatorCall("revoke", {});
    $("operator-token").value = "";
    operatorPreview = null;
    $("operator-confirm").disabled = true;
    $("operator-result").textContent = "Operator session revoked.";
  } catch (e) {
    $("operator-result").textContent = e.message;
  }
});

async function refreshNotifications() {
  try {
    const value = await api("/api/notifications");
    $("notification-status").textContent =
      `${value.total} local incidents; ${value.undelivered} undelivered; ${value.unacknowledged} unacknowledged. Latest ${value.events.length} shown.`;
    const external = value.external || { status: "NOT_CONFIGURED", states: {} };
    $("notification-status").textContent +=
      ` External receiver: ${external.status}; ${external.states.DELIVERED || 0} accepted, ${external.states.UNKNOWN || 0} uncertain, ${external.states.QUEUED || 0} queued, ${external.states.SENDING || 0} in flight. Receiver acceptance does not mean a person read the alert.`;
    $("notification-list").replaceChildren(
      ...value.events.map((item) => {
        const row = node("article", undefined, "news-item");
        row.append(
          node(
            "p",
            `${item.event.kind}: ${item.event.state} at ${stamp(item.event.at)}. ${item.delivered ? "Local file verified" : "Delivery unavailable"}`,
          ),
        );
        const receipt = (external.recent || []).find(
          (r) => r.incident_id === item.event.id,
        );
        if (receipt)
          row.append(
            node(
              "p",
              `Receiver: ${receipt.state} · ${receipt.reason} · ${stamp(receipt.at)}`,
            ),
          );
        if (item.acknowledged)
          row.append(node("p", `Acknowledged ${stamp(item.acknowledged)}`));
        else {
          const button = node(
            "button",
            `Acknowledge incident ${item.event.id}`,
          );
          button.disabled = !item.delivered;
          button.addEventListener("click", async () => {
            button.disabled = true;
            try {
              await api("/api/notifications/ack", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: item.event.id }),
              });
              await refreshNotifications();
            } catch (e) {
              $("notification-status").textContent =
                `Acknowledgment unavailable: ${e.message}`;
              button.disabled = false;
            }
          });
          row.append(button);
        }
        return row;
      }),
    );
  } catch (e) {
    $("notification-status").textContent =
      `Notifications unavailable: ${e.message}`;
    $("notification-list").replaceChildren();
  }
}
$("notification-refresh").addEventListener("click", refreshNotifications);

const strategyFields = [
  "name",
  "hypothesis",
  "input_policy",
  "entry_rules",
  "exit_rules",
  "portfolio_policy",
  "evaluation_plan",
  "risk_per_trade_pct",
  "total_open_risk_pct",
  "daily_loss_limit_pct",
  "authorship",
  "provenance",
];
let selectedStrategy = null,
  strategyId = crypto.randomUUID(),
  strategyRetry = null;
function strategySpec() {
  return Object.fromEntries([
    ["pairs", ["EURUSD", "USDJPY"]],
    ...strategyFields.map((k) => [k, $("strategy-" + k).value]),
  ]);
}
function clearStrategy() {
  $("research-reviewed").checked = false;
  selectedStrategy = null;
  strategyId = crypto.randomUUID();
  strategyRetry = null;
  $("strategy-form").reset();
  $("strategy-selection").textContent = "New candidate · EUR/USD + USD/JPY";
  $("strategy-freeze").disabled = true;
  $("strategy-export").disabled = true;
  $("strategy-message").textContent = "";
  $("strategy-research-status").textContent =
    "Not evaluated. Freezing does not qualify a strategy.";
}
function selectStrategy(record) {
  $("research-reviewed").checked = false;
  selectedStrategy = record;
  strategyId = record.strategy_id;
  strategyRetry = null;
  strategyFields.forEach((k) => {
    $("strategy-" + k).value = record.specification[k];
  });
  $("strategy-selection").textContent =
    record.specification.name +
    " · version " +
    record.version +
    " · " +
    record.state +
    " · SHA-256 " +
    record.sha256;
  $("strategy-freeze").disabled = record.state !== "DRAFT";
  $("strategy-export").disabled = false;
  $("strategy-research-status").textContent =
    record.state +
    " · Descriptive only; not executable, evaluated or approved for paper.";
}
async function refreshStrategies() {
  try {
    await refreshResearch();
    const data = await api("/api/strategies");
    $("lifecycle-status").textContent =
      data.mode +
      " · Trading disabled · Research runs do not qualify a strategy";
    $("lifecycle-milestones").replaceChildren(
      ...data.milestones.map((m) =>
        node("p", m.id + " · " + m.title + " · " + m.status),
      ),
    );
    $("lifecycle-gaps").replaceChildren(...data.gaps.map((g) => node("li", g)));
    $("strategy-history").replaceChildren(
      ...data.records.map((record) => {
        const b = node(
          "button",
          record.specification.name +
            " · v" +
            record.version +
            " · " +
            record.state,
          "secondary",
        );
        b.type = "button";
        b.addEventListener("click", () => {
          selectStrategy(record);
        });
        return b;
      }),
    );
    if (!data.records.length)
      $("strategy-history").append(node("p", "No saved candidates."));
  } catch (e) {
    $("lifecycle-status").textContent =
      "Lifecycle records unavailable: " + e.message;
    $("strategy-history").replaceChildren();
    $("lifecycle-milestones").replaceChildren();
    $("lifecycle-gaps").replaceChildren();
    $("strategy-freeze").disabled = true;
  }
}
$("strategy-new").addEventListener("click", clearStrategy);
$("strategy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const draft = {
    strategy_id: strategyId,
    parent: selectedStrategy?.sha256 || null,
    specification: strategySpec(),
  };
  const fingerprint = JSON.stringify(draft);
  if (!strategyRetry || strategyRetry.fingerprint !== fingerprint)
    strategyRetry = {
      fingerprint,
      request: { ...draft, request_id: crypto.randomUUID() },
    };
  $("strategy-save").disabled = true;
  try {
    const record = await api("/api/strategies/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(strategyRetry.request),
    });
    selectStrategy(record);
    $("strategy-message").textContent =
      "Saved descriptive revision. No model call or trading authority.";
    await refreshStrategies();
  } catch (err) {
    $("strategy-message").textContent =
      "Save not confirmed: " +
      err.message +
      ". Retry unchanged content with the same request, or reload history.";
  } finally {
    $("strategy-save").disabled = false;
  }
});
$("strategy-freeze").addEventListener("click", async () => {
  if (!selectedStrategy) return;
  if (
    strategyFields.some(
      (k) => strategySpec()[k] !== selectedStrategy.specification[k],
    )
  ) {
    $("strategy-message").textContent =
      "Save your changed fields as a new revision before freezing.";
    return;
  }
  $("strategy-freeze").disabled = true;
  try {
    const record = await api("/api/strategies/freeze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sha256: selectedStrategy.sha256 }),
    });
    selectStrategy(record);
    $("strategy-message").textContent =
      "Frozen for research only. Backtest and qualification remain pending.";
    await refreshStrategies();
  } catch (err) {
    $("strategy-message").textContent = "Freeze not confirmed: " + err.message;
    $("strategy-freeze").disabled = false;
  }
});
$("strategy-export").addEventListener("click", () => {
  if (!selectedStrategy) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(selectedStrategy, null, 2)], {
      type: "application/json",
    }),
  );
  const a = node("a");
  a.href = url;
  a.download = "strategy-" + selectedStrategy.sha256 + ".json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

let researchRequest = null;
function researchPost(path, data) {
  return api("/api/research/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
async function researchExport(item) {
  item = await api("/api/research/item/" + item.id);
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(item, null, 2)], { type: "application/json" }),
  );
  const a = node("a");
  a.href = url;
  a.download = "research-" + item.id + ".json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function refreshResearch() {
  const data = await api("/api/research");
  $("research-generate").disabled = !data.ai_enabled;
  $("research-provider-status").textContent = data.ai_enabled
    ? "OpenAI configured: lifetime ceiling 10 requests; uncertain calls are not resent."
    : "AI disabled: configure a private research key file on the server.";
  const choice = $("research-registration").value;
  $("research-registration").replaceChildren(
    ...data.items
      .filter((x) => x.kind === "REGISTRATION")
      .map((x) => {
        const o = node(
          "option",
          x.payload.experiment.name +
            " · " +
            x.payload.experiment.symbol +
            " · " +
            x.id.slice(0, 12),
        );
        o.value = x.id;
        return o;
      }),
  );
  if ([...$("research-registration").options].some((o) => o.value === choice))
    $("research-registration").value = choice;
  $("research-results").replaceChildren(
    ...data.items
      .filter((x) => ["BACKTEST", "AI_PROPOSAL", "EXPOSURE"].includes(x.kind))
      .map((item) => {
        const box = node("article");
        box.append(node("h4", item.kind + " · " + item.id.slice(0, 12)));
        const exportButton = node("button", "Export research evidence");
        exportButton.onclick = () => researchExport(item);
        box.append(exportButton);
        if (item.kind === "AI_PROPOSAL") {
          const load = node("button", "Review proposal in form");
          load.onclick = () => {
            clearStrategy();
            const p = item.payload.proposal;
            strategyFields.forEach(
              (k) => ($("strategy-" + k).value = p.specification[k]),
            );
            $("strategy-provenance").value =
              "Verified provider receipt " +
              item.id +
              "; " +
              p.specification.provenance;
            $("research-rules").value = JSON.stringify(p.rules, null, 2);
            $("research-message").textContent =
              "Proposal loaded; review, save and freeze before registering a study.";
          };
          box.append(load);
        }
        if (item.kind === "BACKTEST") {
          const p = item.payload,
            r = p.result;
          box.append(
            node(
              "p",
              p.partition +
                " · " +
                p.verdict +
                " · Net P&L " +
                r.net_realized_pnl +
                " · Closed trades " +
                r.metrics.closed_trades +
                " · Max observed drawdown " +
                r.metrics.maximum_observed_drawdown_fraction,
            ),
          );
          box.append(node("p", p.limitations.join("; ")));
          const samples = r.equity_samples;
          if (samples.length > 1) {
            const canvas = node("canvas");
            canvas.width = 600;
            canvas.height = 160;
            canvas.setAttribute(
              "aria-label",
              "Observed equity curve, see exported samples for exact times and values",
            );
            canvas.style.maxWidth = "100%";
            const ctx = canvas.getContext("2d"),
              values = samples.map((s) => Number(s.equity)),
              lo = Math.min(...values),
              hi = Math.max(...values);
            ctx.strokeStyle = "#5ac8ae";
            ctx.beginPath();
            values.forEach((v, i) => {
              const x = 5 + (i * 590) / (values.length - 1),
                y = 150 - ((v - lo) * 140) / (hi - lo || 1);
              if (i) ctx.lineTo(x, y);
              else ctx.moveTo(x, y);
            });
            ctx.stroke();
            box.append(canvas);
          }
          const details = node("details");
          details.append(
            node("summary", "Inspect trades, costs and verdict evidence"),
            node(
              "pre",
              JSON.stringify(
                {
                  deals: r.deals,
                  fill_costs: r.fill_costs,
                  financing: r.financing,
                  metrics: r.metrics,
                },
                null,
                2,
              ),
            ),
          );
          box.append(details);
        }
        return box;
      }),
  );
}
async function researchAction(button, fn) {
  button.disabled = true;
  try {
    await fn();
    await refreshResearch();
  } catch (e) {
    $("research-message").textContent =
      "Not confirmed: " + e.message + "; refresh evidence before retrying.";
  } finally {
    button.disabled = false;
  }
}
$("research-generate").onclick = () =>
  researchAction($("research-generate"), async () => {
    const brief = $("research-brief").value;
    if (!researchRequest || researchRequest.brief !== brief)
      researchRequest = { request_id: crypto.randomUUID(), brief };
    const result = await researchPost("generate", researchRequest);
    $("research-message").textContent =
      result.kind === "AI_PROPOSAL"
        ? "Proposal retained. Select Review proposal in form."
        : result.status;
  });
$("research-register").onclick = () =>
  researchAction($("research-register"), async () => {
    if (!selectedStrategy || selectedStrategy.state !== "FROZEN_FOR_RESEARCH")
      throw new Error("Select a frozen candidate first");
    const file = $("research-file").files[0];
    if (!file || file.size > 8 * 1024 * 1024)
      throw new Error("Choose a research JSON bundle up to 8 MiB");
    const bundle = JSON.parse(await file.text());
    const item = await researchPost("register", {
      ...bundle,
      candidate_sha256: selectedStrategy.sha256,
      rules: JSON.parse($("research-rules").value),
      reviewed_mapping: $("research-reviewed").checked,
    });
    $("research-message").textContent = "Registered immutable study " + item.id;
  });
$("research-run").onclick = () =>
  researchAction($("research-run"), async () => {
    const result = await researchPost("execute", {
      registration_id: $("research-registration").value,
      partition: $("research-partition").value,
    });
    $("research-message").textContent =
      result.kind === "BACKTEST"
        ? "Backtest retained: " + result.payload.verdict
        : "Previously exposed run; inspect retained result. No silent rerun.";
  });
$("research-refresh").onclick = () =>
  researchAction($("research-refresh"), refreshResearch);

$("research-rules").addEventListener("input", () => {
  $("research-reviewed").checked = false;
});
$("research-file").addEventListener("change", () => {
  $("research-reviewed").checked = false;
});

$("logout-all").addEventListener("click", async () => {
  try {
    await api("/api/session/logout-all", { method: "POST" });
    signedOut();
    await openSession(null);
    notice("All sessions revoked. Sign in again when ready.");
  } catch (e) {
    notice("Revocation not confirmed: " + e.message);
  }
});
