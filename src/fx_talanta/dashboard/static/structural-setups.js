// Evidence renderer only. No broker capability, model call or generated code.
(() => {
  const views = new Map();
  const explanations = {
    CONFIRMED_H1_SWING_AND_TREND:
      "The H1 swing is confirmed and the trend agrees; watch for a later pullback.",
    FIRST_TOUCH_CLOSED:
      "Price touched the frozen zone and this M15 bar closed without crossing the stop.",
    LATER_CLOSE_OUTSIDE_ZONE:
      "A later bar closed back outside the zone in the trend direction.",
    LATER_RETEST_HELD_STOP:
      "Price returned to the zone while holding the structural stop.",
    SHORT_REVERSAL_CLOSED_PAST_RETEST:
      "A short reversal candle closed past the retest extreme.",
    STRUCTURAL_STOP_CROSSED:
      "Price crossed structural invalidation; this opportunity is rejected.",
    PULLBACK_NOT_WEAKENING:
      "Pullback ranges did not contract under the frozen rule.",
    SETUP_OR_SESSION_DEADLINE: "The setup or London entry window expired.",
    H1_TREND_LOST: "The hourly trend no longer supports this setup.",
    GAPPED_OR_STALE_INPUTS:
      "Required bar history is missing or stale; the setup is blocked.",
    REVISED_OR_INCOMPLETE_INPUTS:
      "Consumed history changed or completeness is unverified.",
    END_OF_STUDY_WINDOW: "The study ended before this setup completed.",
  };
  const el = (tag, text) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (["h3", "label", "summary", "th"].includes(tag)) n.dataset.uiLabel = "";
    return n;
  };
  const svgEl = (tag, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    return n;
  };
  function chart(bars, setup, cutoff, frame) {
    const area = el("figure");
    const visible = bars.filter(
      (b) =>
        Date.parse(b.available_at) <= cutoff &&
        Date.parse(b.close_at) <= cutoff,
    );
    area.append(
      el(
        "figcaption",
        frame + " · " + visible.length + " available closed bars · UTC",
      ),
    );
    const svg = svgEl("svg", {
      viewBox: "0 0 760 230",
      role: "img",
      "aria-label": frame + " closed candles, level zone and fixed stop",
    });
    svg.style.width = "100%";
    svg.dataset.cutoff = new Date(cutoff).toISOString();
    if (!visible.length) return area;
    const values = visible
      .flatMap((b) => [Number(b.low), Number(b.high)])
      .concat([
        Number(setup.stop),
        Number(setup.zone_low),
        Number(setup.zone_high),
      ]);
    const lo = Math.min(...values),
      hi = Math.max(...values);
    const y = (v) => 195 - ((Number(v) - lo) * 170) / (hi - lo || 1);
    svg.append(
      svgEl("rect", {
        x: 15,
        y: y(setup.zone_high),
        width: 620,
        height: Math.max(1, y(setup.zone_low) - y(setup.zone_high)),
        fill: "#00a896",
        opacity: 0.12,
      }),
    );
    for (const [name, value, color] of [
      ["Level", setup.level, "#007f73"],
      ["Stop", setup.stop, "#b6373d"],
    ]) {
      svg.append(
        svgEl("line", {
          x1: 15,
          x2: 635,
          y1: y(value),
          y2: y(value),
          stroke: color,
          "stroke-dasharray": "5 3",
        }),
      );
      const label = svgEl("text", {
        x: 640,
        y: y(value) + 4,
        fill: color,
        "font-size": 12,
      });
      label.textContent = name + " " + Number(value).toFixed(5);
      svg.append(label);
    }
    const step = 610 / visible.length;
    visible.forEach((b, i) => {
      const x = 20 + step * (i + 0.5),
        color = Number(b.close) >= Number(b.open) ? "#007f73" : "#b6373d";
      const group = svgEl("g", {
        "data-bar-at": b.close_at,
        "data-available-at": b.available_at,
      });
      const title = svgEl("title", {});
      title.textContent =
        b.close_at +
        " · O " +
        b.open +
        " H " +
        b.high +
        " L " +
        b.low +
        " C " +
        b.close;
      group.append(
        title,
        svgEl("line", {
          x1: x,
          x2: x,
          y1: y(b.high),
          y2: y(b.low),
          stroke: color,
        }),
        svgEl("rect", {
          x: x - step * 0.3,
          y: Math.min(y(b.open), y(b.close)),
          width: Math.max(1, step * 0.6),
          height: Math.max(1, Math.abs(y(b.open) - y(b.close))),
          fill: color,
        }),
      );
      svg.append(group);
      const transitions =
        frame === "M15"
          ? setup.transitions.filter(
              (t) =>
                Date.parse(t.at) === Date.parse(b.available_at) &&
                Date.parse(t.at) <= cutoff,
            )
          : [];
      if (transitions.length) {
        const mark = svgEl("circle", {
          cx: x,
          cy: y(b.close),
          r: 4,
          fill: "#b16a00",
          "data-transition": transitions.at(-1).state,
        });
        const tip = svgEl("title", {});
        tip.textContent = transitions.map((t) => t.state).join(" / ");
        mark.append(tip);
        svg.append(mark);
      }
    });
    area.append(svg);
    area.append(
      el("small", visible[0].close_at + " → " + visible.at(-1).close_at),
    );
    return area;
  }
  function render(report) {
    const box = el("section");
    box.dataset.structuralSetups = "true";
    box.append(
      el("h3", "Structural opportunities"),
      el(
        "p",
        report.rules.arm +
          " · " +
          report.opportunities.length +
          " watched levels · INSUFFICIENT_EVIDENCE",
      ),
    );
    if (!report.opportunities.length) {
      box.append(
        el(
          "p",
          "No eligible confirmed H1 level was watched. Inspect input/session reasons in the study export.",
        ),
      );
      return box;
    }
    const key =
      report.rules.arm + report.opportunities.map((s) => s.setup_id).join();
    const state = views.get(key) || {
      open: false,
      index: 0,
      cutoff: 0,
      frame: "M15",
    };
    views.set(key, state);
    const inspector = el("details");
    inspector.open = state.open;
    inspector.append(el("summary", "Inspect opportunity"));
    inspector.ontoggle = () => {
      state.open = inspector.open;
    };
    box.append(inspector);
    const label = el("label", "Watched level"),
      selector = el("select");
    report.opportunities.forEach((s, i) => {
      const o = el(
        "option",
        i + 1 + " · " + s.known_at + " · " + s.side + " · final: " + s.state,
      );
      o.value = String(i);
      selector.append(o);
    });
    selector.value = String(state.index);
    label.append(selector);
    inspector.append(label);
    const detail = el("div");
    inspector.append(detail);
    function selected() {
      const s = report.opportunities[Number(selector.value)];
      detail.replaceChildren();
      const times = [
        ...new Set([
          s.known_at,
          ...s.transitions.map((t) => t.at),
          ...s.m15
            .filter((b) => Date.parse(b.available_at) >= Date.parse(s.known_at))
            .map((b) => b.available_at),
        ]),
      ].sort((a, b) => Date.parse(a) - Date.parse(b));
      const cutoffLabel = el("label", "As-of evidence cutoff"),
        slider = el("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = String(times.length - 1);
      slider.step = "1";
      slider.value = String(Math.min(state.cutoff, times.length - 1));
      cutoffLabel.append(slider);
      const frameLabel = el("label", "Chart timeframe"),
        frame = el("select");
      for (const name of ["M15", "H1"]) {
        const option = el("option", name);
        option.value = name;
        frame.append(option);
      }
      frame.value = state.frame;
      frameLabel.append(frame);
      const view = el("div");
      detail.append(cutoffLabel, frameLabel, view);
      function draw() {
        state.cutoff = Number(slider.value);
        state.frame = frame.value;
        const at = times[Number(slider.value)],
          cutoff = Date.parse(at);
        view.replaceChildren(el("p", "Only information available by " + at));
        view.append(
          el(
            "p",
            "H1 swing: " +
              s.pivot_close +
              " · confirmed: " +
              s.pivot_confirmed_at,
          ),
        );
        view.append(
          chart(frame.value === "H1" ? s.h1 : s.m15, s, cutoff, frame.value),
        );
        const timeline = el("ol");
        timeline.dataset.setupTimeline = "true";
        s.transitions
          .filter((t) => Date.parse(t.at) <= cutoff)
          .forEach((t) =>
            timeline.append(
              el(
                "li",
                t.at +
                  " · " +
                  t.state +
                  " · " +
                  t.reason +
                  " — " +
                  (explanations[t.reason] || t.reason),
              ),
            ),
          );
        view.append(timeline);
        if (s.entry && Date.parse(s.entry.at) <= cutoff) {
          // Final fills are deliberately separated from the causal chart view.
          const facts = el("details"),
            summary = el("summary", "Final account outcome (after study)");
          const e = s.entry;
          facts.append(
            summary,
            el("p", e.disposition + (e.reason ? " · " + e.reason : "")),
          );
          if (e.reservation)
            facts.append(
              el(
                "p",
                "Filled volume: " +
                  (e.deals || [])
                    .filter((d) => d.action === "ENTER")
                    .reduce((total, d) => total + Number(d.volume), 0)
                    .toFixed(2) +
                  " lot · Planned peak giveback: " +
                  Number(
                    e.reservation.lifecycle_bound.peak_planned_giveback,
                  ).toFixed(2) +
                  " USD",
              ),
            );
          if (e.net_realized !== undefined)
            facts.append(
              el(
                "p",
                "Net realized: " +
                  Number(e.net_realized).toFixed(2) +
                  " USD · Open volume: " +
                  e.open_volume,
              ),
            );
          for (const exit of e.exit_context || [])
            facts.append(
              el("p", exit.at + " · " + exit.observed_conditions.join(" / ")),
            );
          if (e.last_veto)
            facts.append(el("p", "Last entry veto: " + e.last_veto));
          view.append(facts);
        }
      }
      slider.oninput = draw;
      frame.onchange = draw;
      draw();
    }
    selector.onchange = () => {
      state.index = Number(selector.value);
      state.cutoff = 0;
      selected();
    };
    selected();
    return box;
  }
  window.fxStructural = { render };
  const apply = document.getElementById("structural-apply");
  apply.onclick = () => {
    document.getElementById("research-rules").value = JSON.stringify(
      {
        family: "STRUCTURAL_PULLBACK",
        arm: "RETEST_CONFIRMATION",
        trend_period: 50,
        atr_period: 14,
        swing_bars: 2,
        level_hours: 8,
        zone_atr: "0.25",
        stop_buffer_atr: "0.25",
        confirmation_bars: 8,
        reward_risk: 2,
        hold_bars: 16,
        entry_session: "LONDON",
        calendar_policy: "REQUIRE_MARKET_HEALTH",
        lifecycle_policy: "FINITE_TARGET_90_PERCENT",
      },
      null,
      2,
    );
    document.getElementById("research-reviewed").checked = false;
    document.getElementById("research-symbol").value = "EURUSD";
    document
      .getElementById("research-symbol")
      .dispatchEvent(new Event("change"));
    document.getElementById("research-message").textContent =
      "Structural rules loaded. Review the frozen candidate mapping before registration. Risk limits are unchanged.";
  };
})();
