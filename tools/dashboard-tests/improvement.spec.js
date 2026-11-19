import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { resolve, delimiter } from "node:path";
import { tmpdir } from "node:os";
let child, url;
test.beforeAll(async () => {
  if (process.env.FX_IMPROVEMENT_URL) {
    url = process.env.FX_IMPROVEMENT_URL;
    return;
  }
  const root = resolve("../.."),
    dir = mkdtempSync(resolve(tmpdir(), "fx-improvement-")),
    session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    [
      "tools/dashboard-tests/improvement_fixture.py",
      resolve(dir, "state"),
      session,
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [root, resolve(root, "src"), resolve(root, "tests")].join(
          delimiter,
        ),
      },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  for (let i = 0; i < 100 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Improvement fixture did not start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());
test("diagnose, review, compare, export and reload with real backend and synthetic provider", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.stack || e.message));
  await page.goto(url);
  // Pages retain their mounted evidence. Ensure the background Results panel
  // has rendered too, so this regression cannot pass only because of timing.
  await expect(
    page.locator("#research-results [data-session-results]"),
  ).toHaveCount(1);
  await page
    .getByRole("button", { name: "Diagnose and improve", exact: true })
    .click();
  await expect(page).toHaveURL(/strategies\/improve/);
  const improvement = page.locator("#strategy-improvement");
  await expect(improvement).toBeVisible();
  await expect(improvement.locator("[data-session-results]")).toContainText(
    "INSUFFICIENT_SESSION_SAMPLE",
  );
  await expect(page.locator("[data-session-results]")).toHaveCount(2);
  const sessionDownload = page.waitForEvent("download");
  await improvement
    .getByRole("button", { name: "Export session results", exact: true })
    .click();
  const sessionReport = JSON.parse(
    readFileSync(await (await sessionDownload).path(), "utf8"),
  );
  expect(sessionReport.payload.sessions.symbol).toBe("EURUSD");
  expect(sessionReport.payload.sessions.execution_enabled).toBe(false);
  await improvement
    .getByRole("button", { name: "Generate AI diagnosis", exact: true })
    .click();
  const diagnosis = improvement.locator("[data-diagnosis]");
  await expect(diagnosis).toContainText("London-only filter");
  await diagnosis
    .getByRole("button", { name: "Create reviewed revision", exact: true })
    .click();
  await expect(page.locator("#improvement-message")).toContainText(
    "Review the diagnosis first",
  );
  await diagnosis.getByRole("checkbox").check();
  await diagnosis
    .getByRole("button", { name: "Create reviewed revision", exact: true })
    .click();
  const revision = improvement.locator("[data-revision]");
  await expect(revision).toBeVisible();
  await revision.getByRole("checkbox").check();
  await revision
    .getByRole("button", {
      name: "Freeze revision and run comparison",
      exact: true,
    })
    .click();
  const comparison = improvement.locator("[data-comparison]");
  await expect(comparison).toContainText("Reused training data");
  const download = page.waitForEvent("download");
  await comparison
    .getByRole("button", { name: "Export comparison", exact: true })
    .click();
  const file = await (await download).path();
  const exported = JSON.parse(readFileSync(file, "utf8"));
  expect(exported.payload.inputs_identical).toBe(true);
  expect(exported.payload.risk_limits_unchanged).toBe(true);
  expect(exported.payload.execution_enabled).toBe(false);
  expect(exported.payload.qualified_for_paper).toBe(false);
  await page.reload();
  await expect(improvement.locator("[data-comparison]")).toContainText(
    "Reused training data",
  );
  expect(errors).toEqual([]);
});

test("session controls update reviewed rules without altering risk parameters and survive reload", async ({
  page,
}) => {
  const target = new URL(url);
  target.pathname = "/strategies/backtest";
  await page.goto(target.href);
  await expect(page.locator("#research-candidate")).toHaveValue(
    target.searchParams.get("candidate"),
  );
  const rules = await page.evaluate(async () => {
    const data = await api("/api/research");
    return data.items.find((x) => x.kind === "REGISTRATION").payload.rules;
  });
  await page.locator("#research-rules").fill(JSON.stringify(rules));
  await page.locator("#research-session-settings summary").click();
  await page.locator("#research-entry-session").selectOption("LONDON");
  await page
    .locator("#research-reference-window")
    .selectOption("CURRENT_SESSION");
  await page
    .getByRole("button", {
      name: "Apply session settings to rules",
      exact: true,
    })
    .click();
  const updated = JSON.parse(
    await page.locator("#research-rules").inputValue(),
  );
  expect(updated.entry_session).toBe("LONDON");
  expect(updated.reference_window).toBe("CURRENT_SESSION");
  for (const key of Object.keys(rules).filter(
    (k) => !["entry_session", "reference_window"].includes(k),
  ))
    expect(updated[key]).toEqual(rules[key]);
  await expect(page.locator("#research-reviewed")).not.toBeChecked();
  await page.reload();
  await expect(page.locator("#research-rules")).toHaveValue(
    JSON.stringify(updated, null, 2),
  );
  await expect(
    page.getByText("Trading disabled", { exact: true }),
  ).toBeVisible();
});
