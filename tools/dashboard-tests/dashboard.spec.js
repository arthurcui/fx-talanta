import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
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
  await expect(page.locator("#channel-cards")).toContainText("30 ms");
  await expect(page.locator("#channel-cards")).toContainText("entry blocked");
  await page.getByRole("button", { name: "Why are we waiting?" }).click();
  await expect(page.locator("#messages")).toContainText(
    "This dashboard has no order route",
  );
  await page.locator("#kind").selectOption("decision");
  await expect(page.locator(".record")).toHaveCount(1);
  await page.locator(".record").click();
  await page.getByRole("button", { name: "Ask advisor" }).click();
  await expect(page.locator("#messages .citation")).toContainText("SHA-256");
  await expect(page.locator("#messages")).toContainText(
    "NEWS_COVERAGE_INCOMPLETE",
  );
  const ics =
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:ui-test\r\nDTSTART:20261206T133000Z\r\nSUMMARY:Employment Situation\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n";
  await page
    .locator("#ics")
    .setInputFiles({
      name: "bls.ics",
      mimeType: "text/calendar",
      buffer: Buffer.from(ics),
    });
  await page.locator("#upload").click();
  await expect(page.locator("#upload-result")).toContainText("Saved locally");
  await expect(page.locator("#calendar-details")).toContainText("1");
  await page.locator("#kind").selectOption("all");
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page
    .locator("#ics")
    .setInputFiles({
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
