import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { resolve, delimiter } from "node:path";
import { tmpdir } from "node:os";
let child, url;
const root = resolve("../..");
test.beforeAll(async () => {
  const dir = mkdtempSync(resolve(tmpdir(), "fx-model-ui-"));
  const session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    ["tools/dashboard-tests/fixture_server.py", resolve(dir, "state"), session],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONPATH: [resolve(root, "src"), resolve(root, "tests")].join(
          delimiter,
        ),
      },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  for (let i = 0; i < 100 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Fixture server did not start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());
test("bounded model and offline study integrate without trading capability", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.locator("#model-status")).toContainText("0/1");
  await page.locator("#use-model").check();
  await page.locator("#question").fill("Explain the available evidence");
  await page.locator("#send").click();
  await expect(page.locator("#messages")).toContainText(
    "M4 bounded evidence selection",
  );
  await expect(page.locator("#retry-explanation")).toBeHidden();
  await page.locator("#question").fill("Explain again");
  await page.locator("#send").click();
  await expect(page.locator("#messages")).toContainText("BUDGET_EXHAUSTED");
  await page
    .locator("#study-file")
    .setInputFiles(resolve(root, "tests/fixtures/m5/matched-study.json"));
  await page.locator("#study-upload").click();
  await expect(page.locator("#study-results")).toContainText("SYNTHETIC");
  await expect(page.locator("#study-message")).toContainText(
    "No qualification or execution enabled",
  );
  const original = await page.locator("#study-results").innerText();
  await page.locator("#study-file").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from("{}"),
  });
  await page.locator("#study-upload").click();
  await expect(page.locator("#study-message")).toContainText(
    "previous result retained",
  );
  await expect(page.locator("#study-results")).toHaveText(original, {
    useInnerText: true,
  });
  await page.goto(url);
  await expect(page.locator("#model-status")).toContainText("1/1");
  await expect(page.locator("#study-results")).toContainText("SYNTHETIC");
  expect(errors).toEqual([]);
});

test("sampled alert and broker outage clear stale displayed details", async ({
  page,
}) => {
  let changed = false,
    failed = false;
  await page.route("**/api/overview", async (route) => {
    const upstream = await route.fetch();
    const body = await upstream.json();
    body.broker_view_enabled = true;
    if (changed)
      body.incidents.events.unshift({
        id: 99999,
        kind: "EA-quotes",
        state: "STALE",
        at: body.captured_at,
        evidence: "fixture",
      });
    await route.fulfill({ json: body });
  });
  await page.route("**/api/broker", async (route) => {
    if (failed)
      await route.fulfill({
        status: 503,
        json: { error: "Fixture source unavailable" },
      });
    else
      await route.fulfill({
        json: {
          label: "Fixture broker",
          state: "HEALTHY",
          reason: "CURRENT",
          recorded_at: "2026-11-06T00:00:00Z",
          transport_at_capture: "CONNECTED",
          recorded_clock_policy: "NOT_VERIFIED",
          quote_freshness: "UNVERIFIED",
          channels: {
            Python: "RECENT_RECEIPT",
            EA: "NOT_OBSERVED",
            MCP: "NOT_OBSERVED",
          },
          current_positions: "UNKNOWN",
          snapshot: { display_status: "STALE_RECORDED" },
        },
      });
  });
  await page.goto(url);
  await expect(page.locator("#broker-details")).toContainText("STALE_RECORDED");
  await expect(page.locator("#broker-details")).toContainText(
    "quote freshness: UNVERIFIED",
  );
  await expect(page.locator("#broker-details")).toContainText("NOT_OBSERVED");
  await page.locator("#alert-changes").check();
  changed = true;
  failed = true;
  await expect(page.locator("#incident-alert")).toContainText(
    "EA-quotes: STALE",
    { timeout: 12000 },
  );
  await expect(page.locator("#broker-details")).toBeEmpty();
});

test("operator confirmation, viewer denial, replay and revocation", async ({
  page,
}) => {
  await page.goto(url);
  await expect(page.locator("#operator-panel")).toBeVisible();
  await page
    .locator("#operator-token")
    .fill("fixture-token-local-only-at-least-32-characters");
  await page.locator("#operator-read").click();
  await expect(page.locator("#operator-state")).toHaveText("Unavailable");
  await page
    .locator("#operator-token")
    .fill("isolated-operator-fixture-" + "z".repeat(40));
  await page.locator("#operator-read").click();
  await expect(page.locator("#operator-state")).toContainText("SIMULATOR");
  await page.locator("#operator-preview").click();
  await expect(page.locator("#operator-preview-text")).toContainText(
    "SIMULATOR ONLY",
  );
  await page.locator("#operator-confirmation").fill("yes");
  await page.locator("#operator-confirm").click();
  await expect(page.locator("#operator-result")).toContainText("Invalid");
  await page.locator("#operator-confirmation").fill("SIMULATOR ONLY");
  await page.locator("#operator-confirm").click();
  await expect(page.locator("#operator-result")).toContainText("COMPLETED");
  await page.locator("#operator-confirm").click();
  await expect(page.locator("#operator-result")).toContainText("COMPLETED");
  await page.locator("#operator-read").click();
  await expect(page.locator("#operator-state")).toContainText(
    '"administrative_pause": true',
  );
  await page.locator("#operator-revoke").click();
  await expect(page.locator("#operator-result")).toContainText("revoked");
  await expect(page.locator("#operator-token")).toHaveValue("");
});

test("local notifications remain acknowledged after reopening", async ({
  page,
}) => {
  await page.goto(url);
  await expect(page.locator("#service-status")).toContainText("RECENT", {
    timeout: 12000,
  });
  await page.locator("#notification-refresh").click();
  await expect(page.locator("#notification-list")).toContainText(
    "Local file verified",
  );
  await page.locator("#notification-list button").first().click();
  await expect(page.locator("#notification-list")).toContainText(
    "Acknowledged",
  );
  await page.goto(url);
  await page.locator("#notification-refresh").click();
  await expect(page.locator("#notification-list")).toContainText(
    "Acknowledged",
  );
  await expect(page.locator("#notification-status")).toContainText(
    "0 undelivered",
  );
});
