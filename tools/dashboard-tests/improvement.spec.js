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
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page
    .getByRole("button", { name: "Diagnose and improve", exact: true })
    .click();
  await expect(page).toHaveURL(/strategies\/improve/);
  await page
    .getByRole("button", { name: "Generate AI diagnosis", exact: true })
    .click();
  const diagnosis = page.locator("[data-diagnosis]");
  await expect(diagnosis).toContainText("shorter signal lookback");
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
  const revision = page.locator("[data-revision]");
  await expect(revision).toBeVisible();
  await revision.getByRole("checkbox").check();
  await revision
    .getByRole("button", {
      name: "Freeze revision and run comparison",
      exact: true,
    })
    .click();
  const comparison = page.locator("[data-comparison]");
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
  await expect(page.locator("[data-comparison]")).toContainText(
    "Reused training data",
  );
  expect(errors).toEqual([]);
});
