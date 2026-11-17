import { test, expect } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { tmpdir } from "node:os";
let child, url, dir;
const root = resolve("../..");
async function start(resume = false) {
  const session = resolve(dir, resume ? "second.txt" : "first.txt");
  const port = resume ? new URL(url).port : "0";
  const args = [
    "-m",
    "fx_talanta.dashboard.server",
    "--state",
    resolve(dir, "state"),
    "--local-workspace",
    "--research-datasets",
    dir,
    "--port",
    port,
    "--session-file",
    session,
  ];
  if (resume) args.push("--resume");
  child = spawn(process.env.FX_TEST_PYTHON || "python", args, {
    cwd: root,
    env: { ...process.env, PYTHONPATH: resolve(root, "src") },
    stdio: "ignore",
    windowsHide: true,
  });
  for (let i = 0; i < 100 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Local sign-in fixture did not start");
  url = readFileSync(session, "utf8").trim();
}

test.beforeAll(async () => {
  dir = mkdtempSync(resolve(tmpdir(), "fx-language-"));
  writeFileSync(
    resolve(dir, "synthetic-bundle.json"),
    execFileSync(
      process.env.FX_TEST_PYTHON || "python",
      ["-m", "tools.fixtures.candidate_research"],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: resolve(root, "src") },
        windowsHide: true,
      },
    ),
  );
  await start();
});
test.afterAll(() => child?.kill());
test("language labels preserve inputs and ephemeral translation", async ({
  page,
}) => {
  await page.goto(url);
  await expect(page.locator("#login")).toBeHidden();
  await page.locator("#strategy-name").fill("中文策略 EURUSD");
  await page.locator('#ui-language [data-language="zh"]').click();
  await expect(page.locator("#strategy-save")).toHaveText("保存新版本");
  await expect(page.locator("#research-partition")).toHaveValue("training");
  await expect(page.locator("#strategy-name")).toHaveValue("中文策略 EURUSD");
  await page.route("**/api/translate", async (route) => {
    expect(route.request().postDataJSON()).toEqual({
      text: "风险 0.10%",
      target: "en",
    });
    await route.fulfill({
      json: { text: "Risk 0.10%", target: "en", persisted: false },
    });
  });
  await page.locator("#proposal-workflow details").evaluate((el) => {
    el.open = true;
  });
  await page.locator("#translation-input").fill("风险 0.10%");
  await page.locator("#translate-input").click();
  await expect(page.locator("#translation-output")).toHaveValue("Risk 0.10%");
  await expect(page.locator("#strategy-name")).toHaveValue("中文策略 EURUSD");
  await page.locator('#ui-language [data-language="en"]').click();
  await expect(page.locator("#strategy-save")).toHaveText("Save new revision");
  await page.reload();
  await expect(page.locator("#translation-input")).toHaveValue("");
  await expect(page.locator("#translation-output")).toHaveValue("");
});

test("brief precedes candidate and backtest; proposal fills review form", async ({
  page,
}) => {
  const specification = {
    name: "AI research candidate",
    risk_per_trade_pct: "0.10",
    total_open_risk_pct: "0.20",
    daily_loss_limit_pct: "0.50",
    authorship: "AI_IMPORTED",
  };
  for (const key of [
    "hypothesis",
    "input_policy",
    "entry_rules",
    "exit_rules",
    "portfolio_policy",
    "evaluation_plan",
    "provenance",
  ])
    specification[key] = "Unvalidated research fixture description";
  let generated = false;
  await page.route("**/api/research", (route) =>
    route.fulfill({
      json: {
        ai_enabled: true,
        items: generated
          ? [
              {
                id: "a".repeat(64),
                kind: "AI_PROPOSAL",
                payload: {
                  proposal: {
                    specification,
                    rules: { family: "TREND_BREAKOUT" },
                  },
                },
              },
            ]
          : [],
        jobs: [],
      },
    }),
  );
  await page.route("**/api/research/generate", (route) => {
    generated = true;
    return route.fulfill({ json: { kind: "AI_PROPOSAL" } });
  });
  await page.goto(url);
  for (const id of [
    "proposal-workflow",
    "candidate-review",
    "research-workflow",
  ])
    await expect(page.locator("#" + id)).toBeVisible();
  await expect(page.locator("#research-generate")).toBeEnabled();
  const order = await page.evaluate(() =>
    ["proposal-workflow", "candidate-review", "research-workflow"].map(
      (id) => document.getElementById(id).getBoundingClientRect().top,
    ),
  );
  expect(order[0]).toBeLessThan(order[1]);
  expect(order[1]).toBeLessThan(order[2]);
  await expect(page.locator("#strategy-name")).toHaveValue("");
  await page
    .locator("#research-brief")
    .fill("Explore a simple forex breakout strategy");
  await page.locator("#research-generate").click();
  await page
    .locator("#proposal-results")
    .getByRole("button", { name: "Review proposal in form" })
    .click();
  await expect(page.locator("#strategy-name")).toHaveValue(
    "AI research candidate",
  );
  await expect(page.locator("#strategy-name")).toBeFocused();
  await expect(
    page.locator("#research-results [data-research-kind=AI_PROPOSAL]"),
  ).toHaveCount(0);
});

test("select dataset and backtest without uploading a file", async ({
  page,
}) => {
  const ruleFixture = {
    family: "TREND_BREAKOUT",
    trend_period: 50,
    signal_period: 20,
    atr_period: 14,
    stop_atr: "1.5",
    reward_risk: "2",
    hold_bars: 16,
    start_hour_utc: 0,
    end_hour_utc: 23,
    calendar_policy: "REQUIRE_MARKET_HEALTH",
  };
  await page.route("**/api/research", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.items.push({
      id: "b".repeat(64),
      kind: "AI_PROPOSAL",
      payload: {
        proposal: {
          specification: { name: "Saved rule fixture" },
          rules: ruleFixture,
        },
      },
    });
    await route.fulfill({ json: data });
  });
  let submissions = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/research/select_dataset")) submissions++;
  });
  await page.goto(url);
  await expect(page.locator("#research-dataset option")).toHaveCount(2);
  await page.locator("#strategy-new").click();
  const fields = {
    name: "Catalog browser candidate",
    risk_per_trade_pct: "0.10",
    total_open_risk_pct: "0.20",
    daily_loss_limit_pct: "0.50",
  };
  for (const key of [
    "hypothesis",
    "input_policy",
    "entry_rules",
    "exit_rules",
    "portfolio_policy",
    "evaluation_plan",
    "provenance",
  ])
    fields[key] = "Synthetic research workflow validation only";
  for (const [key, value] of Object.entries(fields))
    await page.locator("#strategy-" + key).fill(value);
  await page.locator("#strategy-save").click();
  await expect(page.locator("#strategy-message")).toContainText(
    "Saved descriptive",
  );
  await page.locator("#strategy-freeze").click();
  await expect(page.locator("#strategy-selection")).toContainText(
    "FROZEN_FOR_RESEARCH",
  );
  await page.reload();
  await page
    .locator("#strategy-history button")
    .filter({ hasText: "Catalog browser candidate" })
    .click();
  await page.locator("#research-register").click();
  await expect(page.locator("#research-message")).toContainText(
    "Not submitted: Executable rules is empty",
  );
  await expect(page.locator("#research-message")).toBeFocused();
  await expect(page.locator("#research-message")).toBeInViewport();
  expect(submissions).toBe(0);
  await page.locator("#research-rules").fill("{");
  await page.locator("#research-register").click();
  await expect(page.locator("#research-message")).toContainText(
    "is not valid JSON",
  );
  expect(submissions).toBe(0);
  const frozen = await page.locator("#strategy-selection").textContent();
  await page.locator("#research-load-rules").click();
  await expect(page.locator("#strategy-selection")).toHaveText(frozen);
  await expect(page.locator("#research-reviewed")).not.toBeChecked();
  expect(
    JSON.parse(await page.locator("#research-rules").inputValue()),
  ).toEqual(ruleFixture);
  await page.locator("#research-dataset").selectOption({ index: 1 });
  await expect(page.locator("#research-dataset-details")).toContainText(
    "SYNTHETIC",
  );
  await expect(page.locator("#research-file")).toBeHidden();
  await page.locator("#research-reviewed").check();
  let releaseRegistration;
  const gate = new Promise((resolve) => {
    releaseRegistration = resolve;
  });
  await page.route("**/api/research/select_dataset", async (route) => {
    await gate;
    await route.continue();
  });
  await page.locator("#research-register").click();
  await expect(page.locator("#research-register")).toHaveText("Registering…");
  await expect(page.locator("#research-register")).toBeDisabled();
  await expect(page.locator("#research-register")).toHaveAttribute(
    "aria-busy",
    "true",
  );
  releaseRegistration();
  await expect(page.locator("#research-message")).toContainText(
    "Registered immutable study",
  );
  await expect(page.locator("#research-register")).toBeEnabled();
  await expect(page.locator("#research-registration")).not.toHaveValue("");
  await expect(page.locator("#research-message")).toBeInViewport();
  await page.locator("#research-run").click();
  await expect(page.locator("#research-message")).toContainText(
    "Backtest retained",
  );
  await expect(page.locator("#research-results")).toContainText(
    "REJECT_OR_REVISE",
  );
  await page.reload();
  await expect(page.locator("#research-results")).toContainText(
    "REJECT_OR_REVISE",
  );
});
