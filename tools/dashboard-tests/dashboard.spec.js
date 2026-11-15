import { test, expect } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { tmpdir } from "node:os";

let child,
  url,
  root = resolve("../..");
test.beforeAll(async () => {
  const dir = mkdtempSync(resolve(tmpdir(), "fx-dashboard-"));
  const session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    [
      "-m",
      "fx_talanta.dashboard.server",
      "--state",
      resolve(dir, "state"),
      "--port",
      "0",
      "--session-file",
      session,
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: resolve(root, "src") },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  for (let i = 0; i < 100 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw new Error("Dashboard failed to start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());

test("desktop: channels, cited advisor, filters, safe calendar failure", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.getByText("SYNTHETIC TOUR", { exact: true })).toBeVisible();
  await expect(page.locator("#channel-cards .channel")).toHaveCount(3);
  await expect(page.locator("#operation-summary")).toContainText(
    "record versions",
  );
  await expect(page.locator("#usage-summary")).toContainText("not billing");
  await expect(page.locator("#qualification-gates")).toContainText(
    "eight weeks AND 100 closed trades",
  );
  await expect(page.locator("#qualification-gates")).toContainText(
    "NOT QUALIFIED",
  );
  await expect(page.locator("#channel-cards")).toContainText("30 ms");
  await expect(page.locator("#channel-cards")).toContainText("entry blocked");
  await page.getByRole("button", { name: "Why are we waiting?" }).click();
  await expect(page.locator("#messages")).toContainText(
    "This dashboard has no order route",
  );
  await page.locator("#kind").selectOption("decision");
  await expect(page.locator(".record")).toHaveCount(1);
  await page.locator("#evidence-search").fill("not-present-fixture");
  await expect(page.locator("#empty")).toBeVisible();
  await page.locator("#evidence-search").fill("HOLD");
  await expect(page.locator(".record")).toHaveCount(1);
  await page.locator(".record").click();
  await expect(page.locator("#trace-status")).toContainText("3 linked records");
  await expect(page.locator("#trace-status")).toContainText(
    "0 missing references",
  );
  await expect(page.locator("#trace-nodes")).toContainText("SHA-256");
  await page.getByRole("button", { name: "Ask advisor" }).click();
  await expect(page.locator("#messages .citation")).toContainText("SHA-256");
  await expect(page.locator("#messages")).toContainText(
    "NEWS_COVERAGE_INCOMPLETE",
  );
  const ics =
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:ui-test\r\nDTSTART:20261206T133000Z\r\nSUMMARY:Employment Situation\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
  await page.locator("#ics").setInputFiles({
    name: "bls.ics",
    mimeType: "text/calendar",
    buffer: Buffer.from(ics),
  });
  await page.locator("#upload").click();
  await expect(page.locator("#upload-result")).toContainText("Saved locally");
  await expect(page.locator("#calendar-details")).toContainText("1");
  await expect(page.locator("#calendar-events")).toContainText(
    "Employment Situation",
  );
  await expect(page.locator("#incident-events")).toContainText(
    "calendar-review",
  );
  await page.goto("about:blank");
  await page.goto(url);
  await expect(page.locator("#history-note")).toContainText("saved answers");
  await expect(page.locator("#messages")).toContainText(
    "NEWS_COVERAGE_INCOMPLETE",
  );
  await page.locator("#kind").selectOption("all");
  await page.locator("#incident-query").fill("EA-quotes");
  await page
    .getByRole("button", { name: "Search incidents", exact: true })
    .click();
  await expect(page.locator("#incident-events .incident")).toHaveCount(1);
  await page.locator("#incident-latest").click();
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export").click();
  const download = await downloadPromise;
  const report = JSON.parse(readFileSync(await download.path(), "utf8"));
  expect(report.payload.scope).toBe("OFFLINE_INSPECTION_NOT_QUALIFICATION");
  expect(report.payload.execution_enabled).toBe(false);
  expect(report.sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(JSON.stringify(report)).not.toContain(new URL(url).hash.slice(7));
  await page.locator("#kind").selectOption("decision");
  await page.locator(".record").click();
  await expect(page.locator("#trace-status")).toContainText("3 linked records");
  await page.locator("#kind").selectOption("all");
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page.locator("#ics").setInputFiles({
    name: "bad.ics",
    mimeType: "text/calendar",
    buffer: Buffer.from("bad file"),
  });
  await page.locator("#upload").click();
  await expect(page.locator("#upload-result")).toContainText("Upload rejected");
  await page.locator("#refresh").click();
  await expect(page.locator("#calendar-details")).toContainText("1");
  expect(errors).toEqual([]);
  expect(page.url()).not.toContain("token");
});

test("mobile: layout, Chinese answer, no XSS, failure shown explicitly", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(url);
  await expect(page.locator("#dashboard")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.locator("#language").selectOption("zh");
  await page.locator("#question").fill("为什么交易已禁用？");
  await page.locator("#send").click();
  await expect(page.locator("#messages .answer").last()).toContainText(
    "交易已禁用",
  );
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
  await page
    .locator("#question")
    .fill('<img src=x onerror="window.pwned=true">');
  await page.locator("#send").click();
  await expect(page.locator("#messages .question").last()).toContainText(
    "<img",
  );
  expect(await page.evaluate(() => window.pwned)).toBeUndefined();
  await page.route("**/api/overview", (route) => route.abort());
  await page.locator("#refresh").click();
  await expect(page.locator("#notice")).toContainText(
    "last received, not current",
  );
});

test("strategy workspace: save, freeze, revise, reload and export without authority", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.locator("#lifecycle-milestones p")).toHaveCount(7);
  await expect(page.locator("#lifecycle-gaps")).toContainText(
    "REJECT_FOR_PROMOTION",
  );
  await page.locator("#strategy-new").click();
  const fields = {
    name: "Research <img src=x onerror=alert(1)>",
    hypothesis: "Synthetic hypothesis for workflow validation only",
    input_policy: "Completed bars and required calendar coverage",
    entry_rules: "Explicit signal rules pending executable mapping",
    exit_rules: "Protective stops and registered time exits",
    portfolio_policy: "Bound combined signed USD exposure across both pairs",
    evaluation_plan: "Preregister holdout windows and base and stress costs",
    risk_per_trade_pct: "0.10",
    total_open_risk_pct: "0.20",
    daily_loss_limit_pct: "0.50",
    provenance: "Human-authored synthetic browser fixture",
  };
  for (const [key, value] of Object.entries(fields))
    await page.locator("#strategy-" + key).fill(value);
  await page.locator("#strategy-save").click();
  await expect(page.locator("#strategy-selection")).toContainText("version 1");
  await expect(page.locator("#strategy-message")).toContainText(
    "Saved descriptive",
  );
  await page.locator("#strategy-freeze").click();
  await expect(page.locator("#strategy-selection")).toContainText(
    "FROZEN_FOR_RESEARCH",
  );
  await expect(page.locator("#strategy-research-status")).toContainText(
    "not executable",
  );
  await page
    .locator("#strategy-entry_rules")
    .fill("Changed research signal requires a new version");
  await page.locator("#strategy-save").click();
  await expect(page.locator("#strategy-selection")).toContainText("version 2");
  await expect(page.locator("#strategy-history button")).toHaveCount(2);
  await expect(page.locator("#strategy-history img")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#strategy-history button")).toHaveCount(2);
  await page
    .locator("#strategy-history button")
    .filter({ hasText: "v1" })
    .click();
  await expect(page.locator("#strategy-entry_rules")).toHaveValue(
    fields.entry_rules,
  );
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#strategy-export").click();
  const download = await downloadPromise;
  const saved = JSON.parse(readFileSync(await download.path(), "utf8"));
  expect(saved.version).toBe(1);
  expect(saved.state).toBe("FROZEN_FOR_RESEARCH");
  expect(saved.execution_enabled).toBe(false);
  expect(saved.executable).toBe(false);
  await page
    .locator("#strategy-history button")
    .filter({ hasText: "v2" })
    .click();
  await page.locator("#strategy-risk_per_trade_pct").fill("0.30");
  await page.locator("#strategy-save").click();
  await expect(page.locator("#strategy-message")).toContainText(
    "Save not confirmed",
  );
  await expect(page.locator("#strategy-history button")).toHaveCount(2);
  await page
    .locator("#strategy-history button")
    .filter({ hasText: "v1" })
    .click();
  await page.locator("#research-rules").fill(
    JSON.stringify({
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
    }),
  );
  const bundle = execFileSync(
    process.env.FX_TEST_PYTHON || "python",
    ["-m", "tools.fixtures.candidate_research"],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: resolve(root, "src") },
      windowsHide: true,
    },
  );
  await page.locator("#research-advanced summary").click();
  await page.locator("#research-use-upload").check();
  await page.locator("#research-file").setInputFiles({
    name: "synthetic-bundle.json",
    mimeType: "application/json",
    buffer: bundle,
  });
  await page.locator("#research-reviewed").check();
  await page.locator("#research-register").click();
  await expect(page.locator("#research-message")).toContainText(
    "Registered immutable study",
  );
  await page.locator("#research-run").click();
  await expect(page.locator("#research-message")).toContainText(
    "Backtest retained",
  );
  await expect(page.locator("#research-results")).toContainText(
    "REJECT_OR_REVISE",
  );
  await expect(page.locator("#research-results canvas")).toHaveCount(1);
  await page.reload();
  await expect(page.locator("#research-results")).toContainText(
    "REJECT_OR_REVISE",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});
