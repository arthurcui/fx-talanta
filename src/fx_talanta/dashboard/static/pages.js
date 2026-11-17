"use strict";
// Keep mounted forms while changing real routes; navigation never submits work.
(() => {
  const byId = (id) => document.getElementById(id);
  const root = byId("dashboard");
  const routes = {
    "/overview": [
      "Overview",
      "Your strategy research and current trading boundaries.",
    ],
    "/strategies": [
      "Strategies",
      "Create a strategy or continue a saved version.",
    ],
    "/strategies/describe": [
      "Create a strategy",
      "Describe your idea in English or Chinese, then review a proposal.",
    ],
    "/strategies/review": [
      "Review your strategy",
      "Review the rules and risk limits. Save a revision, then freeze it for research.",
    ],
    "/strategies/backtest": [
      "Backtest your strategy",
      "Review executable rules and historical data before running a study.",
    ],
    "/strategies/results": [
      "Review backtest results",
      "Inspect outcomes and limitations before revising your strategy.",
    ],
    "/market": [
      "Market & Data",
      "Inspect data channels, quote freshness, calendar and news.",
    ],
    "/advisor": [
      "Advisor",
      "Ask questions about recorded evidence. The advisor cannot place orders.",
    ],
    "/activity": [
      "Activity",
      "Review evidence, incidents and service activity.",
    ],
  };
  const pages = {};
  for (const path of Object.keys(routes)) {
    const section = document.createElement("section");
    section.className = "app-page";
    section.dataset.page = path;
    section.hidden = true;
    pages[path] = section;
    root.append(section);
  }
  function move(path, selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element) pages[path].append(element);
    }
  }
  move("/overview", [
    ".source-banner",
    ".metrics",
    "#lifecycle-overview",
    "#blockers",
  ]);
  // Move the entire safety panel, retaining its heading and qualification gates.
  const gates = byId("qualification-gates");
  pages["/overview"].append(gates);
  move("/strategies/describe", ["#proposal-workflow"]);
  move("/strategies/review", ["#candidate-review"]);
  move("/strategies/backtest", ["#research-workflow"]);
  move("/strategies/results", ["#research-results"]);
  move("/strategies", ["#strategy-history"]);
  move("/market", ["#channels", "#calendar"]);
  move("/advisor", ["#advisor"]);
  move("/activity", [
    "#notifications-panel",
    "#operator-panel",
    "#broker-panel",
    "#operations",
    "#journal",
    "#trace-panel",
    "#comparison",
    "#incidents",
  ]);
  byId("strategy-workspace").remove();
  document.querySelector(".workspace-grid").remove();
  for (const id of [
    "proposal-workflow",
    "candidate-review",
    "research-workflow",
  ])
    byId(id).classList.add("panel");
  // Saved versions have their own page; remove obsolete single-page instructions.
  const review = byId("candidate-review");
  for (const heading of [...review.querySelectorAll("h3")]) {
    if (heading.textContent === "Saved versions") {
      heading.nextElementSibling?.remove();
      heading.remove();
    }
  }
  review.querySelector("ul")?.remove();
  byId("proposal-workflow").querySelector("h3").textContent =
    "Describe your strategy";
  review.querySelector("h3").textContent = "Review rules and risk limits";
  byId("research-workflow").querySelector("h3").textContent =
    "Choose data and run a backtest";
  const intro = document.createElement("div");
  intro.className = "panel";
  intro.innerHTML =
    '<a class="primary-link" href="/strategies/describe">Create a strategy</a><h2>Saved strategies</h2><p>Choose a version to review, revise or backtest. Freezing preserves a research version; it does not approve trading.</p>';
  pages["/strategies"].prepend(intro);
  intro.append(byId("strategy-history"));
  intro
    .querySelector("a")
    .addEventListener("click", () => byId("strategy-new").click());
  const resume = document.createElement("a");
  resume.href = "/strategies/review";
  resume.textContent = "Continue current strategy";
  resume.className = "secondary-link";
  resume.id = "strategy-resume";
  intro.prepend(resume);
  const manual = document.createElement("a");
  manual.href = "/strategies/review";
  manual.textContent = "Write a strategy manually";
  manual.className = "secondary-link";
  manual.addEventListener("click", () => byId("strategy-new").click());
  byId("proposal-workflow").prepend(manual);
  const continueButton = document.createElement("button");
  continueButton.id = "strategy-continue";
  continueButton.type = "button";
  continueButton.textContent = "Continue to backtest";
  continueButton.disabled = true;
  continueButton.addEventListener("click", () =>
    navigate("/strategies/backtest"),
  );
  review.append(continueButton);
  const start = document.createElement("button");
  start.id = "research-start";
  start.type = "button";
  start.textContent = "Run backtest";
  byId("research-message").before(start);
  // Explicit two-stage registration remains available for inspection, not required in the normal flow.
  const advanced = document.createElement("details");
  advanced.id = "registration-advanced";
  advanced.innerHTML = "<summary>Advanced: registered studies</summary>";
  byId("research-workflow").append(advanced);
  advanced.append(
    byId("research-register"),
    byId("research-registration").closest("label"),
    byId("research-run"),
  );
  start.before(byId("research-partition").closest("label"));
  const datasetDetails = document.createElement("details");
  datasetDetails.innerHTML =
    "<summary>Dataset windows and cost assumptions</summary>";
  byId("research-dataset-details").before(datasetDetails);
  datasetDetails.append(byId("research-dataset-details"));
  const resultsLink = document.createElement("a");
  resultsLink.href = "/strategies/review";
  resultsLink.textContent = "Revise this strategy";
  resultsLink.className = "primary-link";
  pages["/strategies/results"].prepend(resultsLink);
  const empty = document.createElement("p");
  empty.id = "results-empty";
  empty.textContent =
    "No backtest results for this strategy yet. Complete Backtest to see outcomes here.";
  pages["/strategies/results"].append(empty);
  const flow = document.createElement("div");
  flow.id = "strategy-flow";
  flow.innerHTML =
    '<p id="strategy-context" role="status">No strategy selected</p><nav aria-label="Strategy steps">' +
    ["Describe", "Review", "Backtest", "Results"]
      .map(
        (label) => `<a href="/strategies/${label.toLowerCase()}">${label}</a>`,
      )
      .join("") +
    "</nav>";
  root.append(document.querySelector("footer"));
  root.prepend(flow);
  flow.append(byId("research-message"));
  const legacy = {
    workspace: "/overview",
    "strategy-workspace": "/strategies",
    channels: "/market",
    calendar: "/market",
    advisor: "/advisor",
    journal: "/activity",
    incidents: "/activity",
  };
  function render() {
    const path = routes[location.pathname] ? location.pathname : "/overview";
    for (const [key, section] of Object.entries(pages))
      section.hidden = key !== path;
    flow.hidden = !path.startsWith("/strategies/");
    document.querySelector(".eyebrow").hidden = path.startsWith("/strategies");
    byId("refresh").hidden = path.startsWith("/strategies");
    byId("export").hidden = path.startsWith("/strategies");
    document.querySelector(".heading h1").textContent = routes[path][0];
    document.querySelector(".heading .subtitle").textContent = routes[path][1];
    byId("page-breadcrumb").textContent = path.startsWith("/strategies")
      ? "Strategies"
      : routes[path][0];
    document.title = "FX-Talanta · " + routes[path][0];
    for (const link of document.querySelectorAll(
      ".sidebar nav a, #strategy-flow a",
    )) {
      const active =
        link.pathname === path ||
        (link.pathname === "/strategies" && path.startsWith("/strategies/"));
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    window.dispatchEvent(new Event("fx-page-change"));
  }
  function navigate(path, replace = false) {
    if (!routes[path]) return;
    history[replace ? "replaceState" : "pushState"](
      null,
      "",
      path + location.search,
    );
    render();
    window.scrollTo(0, 0);
    const heading = document.querySelector("h1");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a");
    if (
      !link ||
      event.button ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      link.origin !== location.origin
    )
      return;
    const path =
      legacy[link.hash.slice(1)] ||
      (routes[link.pathname] && !link.hash ? link.pathname : null);
    if (path) {
      event.preventDefault();
      navigate(path);
    }
  });
  window.addEventListener("popstate", render);
  window.fxPages = { navigate, render };
  if (legacy[location.hash.slice(1)])
    history.replaceState(
      null,
      "",
      legacy[location.hash.slice(1)] + location.search,
    );
  // Preserve launch tokens until the authentication code consumes them.
  render();
})();
