"use strict";
window.fxSessions = {
  render(report) {
    const el = (tag, text) => {
      const n = document.createElement(tag);
      n.textContent = text || "";
      if (["h3", "th", "summary"].includes(tag)) n.dataset.uiLabel = "";
      return n;
    };
    const box = el("section");
    box.dataset.sessionResults = report.symbol;
    box.append(
      el("h3", "Session results"),
      el("p", report.symbol + " · " + report.partition),
      el(
        "p",
        "Trades are grouped by entry session; overlaps are counted once. Small samples do not establish an edge.",
      ),
    );
    const table = el("table");
    const headings = [
      "Session / overlap",
      "Closed trades",
      "Net P&L",
      "Closed-trade drawdown",
      "Sample status",
    ];
    const head = el("tr");
    headings.forEach((x) => head.append(el("th", x)));
    table.append(head);
    for (const b of report.buckets) {
      const row = el("tr");
      [
        b.regime,
        b.closed_trades,
        Number(b.net_pnl).toFixed(6),
        Number(b.closed_trade_drawdown).toFixed(6),
        b.sample_status,
      ].forEach((x) => row.append(el("td", String(x))));
      table.append(row);
    }
    box.append(
      table,
      el("p", "Unattributed realized P&L: " + report.unattributed_realized_pnl),
    );
    const details = el("details");
    details.append(el("summary", "Session definitions and limitations"));
    for (const [name, d] of Object.entries(report.conventions))
      details.append(
        el(
          "p",
          name +
            " · " +
            d.timezone +
            " · " +
            d.open_hour +
            ":00–" +
            d.close_hour +
            ":00",
        ),
      );
    details.append(
      el("p", "DST-aware · " + report.version + " · tzdata " + report.tzdata),
    );
    report.limitations.forEach((t) => details.append(el("p", t)));
    for (const b of report.buckets)
      details.append(
        el(
          "p",
          b.regime +
            " · Evaluations: " +
            b.evaluations +
            " · Candidates: " +
            b.candidates +
            " · Candidates before/after halt: " +
            b.candidates_before_halt +
            "/" +
            b.candidates_after_halt +
            " · " +
            JSON.stringify(b.holds),
        ),
      );
    box.append(details);
    return box;
  },
};
window.addEventListener("DOMContentLoaded", () => {
  document
    .querySelector("#research-session-settings summary")
    .addEventListener("click", () => {
      if (document.getElementById("research-session-settings").open) return;
      try {
        const rules = JSON.parse(
          document.getElementById("research-rules").value,
        );
        document.getElementById("research-entry-session").value =
          rules.entry_session || "UTC_WINDOW";
        document.getElementById("research-reference-window").value =
          rules.reference_window || "ROLLING";
      } catch (_) {
        /* Keep invalid JSON untouched for explicit review. */
      }
    });
  document.getElementById("research-session-apply").onclick = () => {
    const field = document.getElementById("research-rules");
    try {
      const rules = JSON.parse(field.value);
      rules.entry_session = document.getElementById(
        "research-entry-session",
      ).value;
      rules.reference_window = document.getElementById(
        "research-reference-window",
      ).value;
      if (
        rules.reference_window !== "ROLLING" &&
        rules.family !== "TREND_BREAKOUT"
      )
        throw Error("Session ranges require breakout rules");
      if (
        rules.reference_window === "CURRENT_SESSION" &&
        rules.entry_session === "UTC_WINDOW"
      )
        throw Error("Choose a named entry session");
      field.value = JSON.stringify(rules, null, 2);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      document.getElementById("research-message").textContent =
        "Session settings applied to the rules. Review again before running.";
    } catch (e) {
      document.getElementById("research-message").textContent =
        "Not applied: " + e.message;
    }
  };
});
