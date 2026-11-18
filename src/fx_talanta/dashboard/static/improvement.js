"use strict";
(() => {
  const root = document.getElementById("strategy-improvement");
  let baseline = sessionStorage.getItem("fx-improvement-baseline") || "";
  let busy = false;
  let poll = null;
  let generation = 0;
  const el = (tag, text = "") => {
    const n = document.createElement(tag);
    n.textContent = text;
    if (["h3", "h4", "th", "summary"].includes(tag)) n.dataset.uiLabel = "";
    return n;
  };
  const message = el("p");
  message.setAttribute("role", "status");
  message.id = "improvement-message";
  const content = el("div");
  root.append(
    el("h2", "Diagnosis → Revision → Comparison"),
    el(
      "p",
      "Research only. Risk limits, costs, data and training dates stay unchanged. No trading or promotion.",
    ),
    message,
    content,
  );
  const action = (label, fn) => {
    const b = el("button", label);
    b.onclick = async () => {
      if (busy) return;
      busy = true;
      b.disabled = true;
      content.inert = true;
      message.textContent = "Working…";
      try {
        const value = await fn();
        await render();
        message.textContent =
          value?.status || "Saved. Original evidence preserved.";
      } catch (e) {
        message.textContent =
          "Not confirmed: " + e.message + ". Refresh evidence before retrying.";
      } finally {
        busy = false;
        content.inert = false;
        b.disabled = false;
      }
    };
    return b;
  };
  function review(label) {
    const wrapper = el("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    wrapper.append(input, document.createTextNode(label));
    return [wrapper, input];
  }
  async function render() {
    const current = ++generation;
    clearTimeout(poll);
    const data = await api("/api/research");
    if (current !== generation) return;
    content.replaceChildren();
    const back = el("a", "Back to results");
    back.href = "/strategies/results";
    content.append(
      back,
      action("Refresh improvement evidence", async () => ({})),
    );
    if (!baseline) {
      content.append(
        el("p", "Choose Diagnose and improve on a training result."),
      );
      return;
    }
    const original = await api("/api/research/item/" + baseline);
    if (current !== generation) return;
    const p = original.payload,
      r = p.result;
    const facts = el("article");
    facts.append(
      el("h3", "1. Verified backtest facts"),
      el("p", "Baseline " + baseline.slice(0, 12)),
      el(
        "p",
        p.partition +
          " · " +
          p.verdict +
          " · Closed trades: " +
          r.metrics.closed_trades +
          " · Net P&L: " +
          Number(r.net_realized_pnl).toFixed(2),
      ),
      el(
        "p",
        r.integrity_halt
          ? "Risk halt recorded. The AI cannot relax this limit."
          : "No integrity halt recorded.",
      ),
      el("p", p.limitations.join("; ")),
    );
    content.append(facts);
    const sessions = await researchPost("analyze_sessions", {
      result_id: baseline,
    });
    if (current !== generation) return;
    const sessionBox = window.fxSessions.render(sessions.payload.sessions);
    sessionBox.append(el("p", sessions.payload.scope));
    sessionBox.append(
      action("Export session results", () => researchExport(sessions)),
    );
    content.append(sessionBox);
    if (r.risk_halt?.limits?.aggregate_risk) {
      facts.append(
        action("Investigate risk halt", () =>
          researchPost("investigate_halt", { result_id: baseline }),
        ),
      );
    }
    for (const item of data.items.filter(
      (x) => x.kind === "RISK_DIAGNOSIS" && x.payload.baseline_id === baseline,
    )) {
      const d = item.payload,
        replay = d.replay;
      const box = el("article");
      box.dataset.riskDiagnosis = item.id;
      box.append(
        el("h3", "Verified risk-halt diagnosis"),
        el("p", d.explanation),
      );
      const table = el("table");
      const rows = [
        ["Trade", "Symbol", "Volume", "Net P&L", "Exit reason"],
        ...d.trades.map((t) => [
          t.trade,
          t.symbol,
          t.volume,
          Number(t.net_pnl).toFixed(6),
          t.exit_reason,
        ]),
      ];
      rows.forEach((cells, i) => {
        const row = el("tr");
        cells.forEach((value) =>
          row.append(el(i ? "td" : "th", String(value))),
        );
        table.append(row);
      });
      const timing = el("details");
      timing.append(el("summary", "Trade timing and entry risk"));
      for (const t of d.trades)
        timing.append(
          el(
            "p",
            t.trade +
              " · " +
              t.opened_at +
              " → " +
              t.closed_at +
              " · " +
              t.side +
              " · " +
              t.admitted_risk,
          ),
        );
      box.append(table, timing, el("h4", "Risk at the halt boundary"));
      const risk = el("table");
      [
        ["Measurement", "Before", "Trigger"],
        [
          "Aggregate risk",
          replay.before.aggregate_risk,
          replay.trigger.aggregate_risk,
        ],
        [
          "Aggregate limit",
          replay.before.aggregate_limit,
          replay.trigger.aggregate_limit,
        ],
        [
          "Pending reservation risk",
          replay.before.pending_reservation_risk,
          replay.trigger.pending_reservation_risk,
        ],
      ].forEach((cells, i) => {
        const row = el("tr");
        cells.forEach((value) =>
          row.append(el(i ? "td" : "th", String(value))),
        );
        risk.append(row);
      });
      box.append(risk);
      for (const p of replay.trigger.positions) {
        box.append(
          el(
            "p",
            "Entry-to-stop loss + unrealized profit + exit buffer: " +
              p.entry_to_stop_loss +
              " + " +
              p.unrealized_pnl +
              " + " +
              p.incremental_exit_buffer +
              " = " +
              p.aggregate_contribution,
          ),
        );
      }
      box.append(
        el(
          "p",
          "Targeted replay: " +
            replay.historical_observations +
            " historical quotes over " +
            replay.elapsed_seconds +
            " seconds · " +
            replay.final_state +
            " · Open positions: " +
            replay.remaining_positions,
        ),
        el(
          "p",
          "Recorded protective close reproduced. Risk limits unchanged. Trading disabled.",
        ),
        el("p", d.next_action),
        action("Export risk-halt evidence", () => researchExport(item)),
      );
      content.append(box);
    }
    const label = el("label", "Instructions (English or Chinese)");
    const instructions = document.createElement("textarea");
    instructions.id = "improvement-instructions";
    instructions.value =
      "Explain why this failed and propose one testable change without changing risk limits.";
    label.append(instructions);
    content.append(label);
    const generate = action("Generate AI diagnosis", async () => {
      const identity = JSON.stringify([
        baseline,
        instructions.value,
        sessions.id,
        data.items
          .filter(
            (x) =>
              x.kind === "RISK_DIAGNOSIS" && x.payload.baseline_id === baseline,
          )
          .map((x) => x.id),
      ]);
      const stored = JSON.parse(
        sessionStorage.getItem("fx-diagnosis-request") || "null",
      );
      const request =
        stored?.identity === identity
          ? stored
          : { identity, id: crypto.randomUUID() };
      sessionStorage.setItem("fx-diagnosis-request", JSON.stringify(request));
      return researchPost("diagnose", {
        request_id: request.id,
        result_id: baseline,
        instruction: instructions.value,
      });
    });
    generate.disabled = !data.ai_enabled;
    content.append(generate);
    const diagnoses = data.items.filter(
      (x) =>
        x.kind === "AI_DIAGNOSIS" &&
        x.payload.evidence.baseline_id === baseline,
    );
    for (const item of diagnoses) {
      const d = item.payload.proposal;
      const box = el("article");
      box.dataset.diagnosis = item.id;
      box.append(el("h3", "2. AI hypothesis — review before revising"));
      if (item.payload.evidence.baseline_engine_current === false)
        box.append(
          el(
            "p",
            "This baseline uses an older engine. A new matched baseline is required before running a revision comparison; the saved result stays unchanged.",
          ),
        );
      for (const [title, value] of [
        ["Explanation", d.explanation],
        ["Hypothesis", d.hypothesis],
        ["Proposed change", d.proposed_change],
        ["Falsification criterion", d.falsification],
        ["Uncertainty", d.uncertainty],
      ]) {
        if (
          ["Explanation", "Falsification criterion", "Uncertainty"].includes(
            title,
          )
        ) {
          const details = el("details");
          details.append(el("summary", title), el("p", value));
          box.append(details);
        } else box.append(el("h4", title), el("p", value));
      }
      const changes = Object.entries(d.rules).filter(
        ([k, v]) => String(v) !== String(p.rules[k]),
      );
      const diff = el("table");
      for (const cells of [
        ["Rule", "Original", "Proposed"],
        ...changes.map(([field, to]) => [field, p.rules[field], to]),
      ]) {
        const row = el("tr");
        cells.forEach((v) => row.append(el("td", String(v))));
        diff.append(row);
      }
      box.append(diff);
      box.append(action("Export diagnosis", () => researchExport(item)));
      const [check, input] = review(
        "I reviewed the hypothesis and single rule change. Risk limits remain unchanged.",
      );
      box.append(check);
      const create = action("Create reviewed revision", () => {
        if (!input.checked) throw Error("Review the diagnosis first");
        return researchPost("revise_diagnosis", {
          diagnosis_id: item.id,
          reviewed: true,
        });
      });
      create.disabled =
        d.recommendation !== "REVISE_RULES" || changes.length !== 1;
      box.append(el("p", d.recommendation), create);
      content.append(box);
    }
    for (const item of data.items.filter(
      (x) =>
        x.kind === "RESEARCH_REVISION" && x.payload.baseline_id === baseline,
    )) {
      const box = el("article");
      box.dataset.revision = item.id;
      box.append(
        el("h3", "3. Compare the reviewed revision"),
        el(
          "p",
          "Same training inputs and risk policy. Original and revision remain separate. Reused data cannot establish independent validation.",
        ),
        el("pre", JSON.stringify(item.payload.rules, null, 2)),
      );
      const [check, input] = review(
        "Freeze this revision and compare it on the original training inputs.",
      );
      box.append(
        check,
        action("Freeze revision and run comparison", () => {
          if (!input.checked) throw Error("Review the comparison scope first");
          return researchPost("compare_revision", {
            revision_id: item.id,
            reviewed: true,
          });
        }),
      );
      content.append(box);
    }
    const comparisons = data.items.filter(
      (x) => x.kind === "COMPARISON_PLAN" && x.payload.baseline_id === baseline,
    );
    for (const plan of comparisons) {
      const result = await researchPost("improvement_status", {
        comparison_id: plan.id,
      });
      if (current !== generation) return;
      const box = el("article");
      box.dataset.comparison = plan.id;
      box.append(el("h3", "4. Measured comparison"));
      if (result.kind === "COMPARISON") {
        const p = result.payload;
        const table = el("table");
        for (const cells of [
          ["Metric", "Original", "Revision"],
          ["Net P&L", p.original.net_pnl, p.revised.net_pnl],
          ["Closed trades", p.original.closed_trades, p.revised.closed_trades],
          [
            "Drawdown fraction",
            p.original.maximum_observed_drawdown_fraction,
            p.revised.maximum_observed_drawdown_fraction,
          ],
          [
            "Risk halt",
            String(p.original.integrity_halt),
            String(p.revised.integrity_halt),
          ],
          ["Verdict", p.original.verdict, p.revised.verdict],
        ]) {
          const row = el("tr");
          cells.forEach((v) => row.append(el("td", String(v))));
          table.append(row);
        }
        box.append(
          table,
          el("p", p.assessment),
          el("p", p.warning),
          action("Export comparison", () => researchExport(result)),
        );
      } else {
        box.append(el("p", result.status));
        if (result.status === "RUNNING")
          poll = setTimeout(() => {
            if (location.pathname === "/strategies/improve" && !busy)
              render().catch((e) => {
                message.textContent = e.message;
              });
          }, 5000);
      }
      content.append(box);
    }
  }
  window.fxImprovement = {
    open: async (id) => {
      baseline = id;
      sessionStorage.setItem("fx-improvement-baseline", id);
      window.fxPages.navigate("/strategies/improve");
      try {
        await render();
      } catch (e) {
        message.textContent = e.message;
      }
    },
  };
  if (location.pathname === "/strategies/improve")
    render().catch((e) => {
      message.textContent = e.message;
    });
  window.addEventListener("fx-page-change", () => {
    if (location.pathname === "/strategies/improve" && !busy)
      render().catch((e) => {
        message.textContent = e.message;
      });
  });
})();
