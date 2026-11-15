import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
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
