import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { resolve, delimiter } from "node:path";
import { tmpdir } from "node:os";
let child, url;
const root = resolve("../..");
test.beforeAll(async () => {
  const dir = mkdtempSync(resolve(tmpdir(), "fx-runner-ui-"));
  const session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    ["tools/dashboard-tests/runner_fixture.py", dir, session],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [resolve(root, "src"), root].join(delimiter),
      },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  for (let i = 0; i < 150 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Runner fixture did not start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());
test("direct runner view shows simulation authority and clears unavailable evidence", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.locator("#workflow-status")).toContainText("STOPPED");
  await expect(page.locator("#workflow-status")).toContainText(
    "simulation runner (direct read)",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "6 observations",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "RECORDED_MODEL_RESPONSES",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "not quote latency or entry readiness",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "0 open / 1 closed simulated positions",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "No broker trades",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "6 queued / 6 acknowledged / 0 pending",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "Producer liveness UNVERIFIED",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "6 normalized inputs",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "Source provenance is not independently qualified",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "6 recorded replies",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "no verified model calls",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "Model cost is separate from trade P&L",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "12/12 calls reserved",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "0 unresolved reserved calls",
  );
  await expect(page.locator("#workflow-details")).toContainText(
    "No automatic refunds or resends",
  );
  await page.route("**/api/overview", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.matched_workflow = { status: "UNAVAILABLE", execution_enabled: false };
    await route.fulfill({ response, json: body });
  });
  await page.locator("#refresh").click();
  await expect(page.locator("#workflow-details")).toBeEmpty();
  await page.unroute("**/api/overview");
  await page.locator("#refresh").click();
  await expect(page.locator("#workflow-details")).toContainText(
    "6 observations",
  );
  expect(errors).toEqual([]);
});
