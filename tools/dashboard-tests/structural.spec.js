import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync, readFileSync } from "node:fs";
import { resolve, delimiter } from "node:path";
import { tmpdir } from "node:os";
let child, url;
test.beforeAll(async () => {
  const root = resolve("../.."),
    dir = mkdtempSync(resolve(tmpdir(), "fx-structural-"));
  const session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    [
      "tools/dashboard-tests/structural_fixture.py",
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
  for (let i = 0; i < 150 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Structural fixture did not start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());
test("structural rules, causal charts, matched control, export and reload", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.locator("#research-candidate")).not.toHaveValue("");
  await page.locator("#research-manual").evaluate((el) => {
    el.open = true;
  });
  await page.locator("#structural-research-settings summary").click();
  await page.locator("#structural-apply").click();
  await expect(page.locator("#research-rules")).toHaveValue(
    /STRUCTURAL_PULLBACK/,
  );
  await page.locator("#research-dataset").selectOption({ index: 1 });
  await page.locator("#research-reviewed").check();
  await page.locator("#research-start").click();
  await expect(page).toHaveURL(/strategies\/results/);
  const box = page.locator("[data-structural-setups]").first();
  await expect(box).toContainText("watched levels");
  await box.getByText("Inspect opportunity", { exact: true }).click();
  await expect(box.locator("[data-setup-timeline]")).toContainText(
    "LEVEL_KNOWN",
  );
  await expect(box.locator("[data-setup-timeline]")).not.toContainText(
    "CONFIRMED ·",
  );
  const slider = box.getByRole("slider");
  await slider.evaluate((el) => {
    el.value = el.max;
    el.dispatchEvent(new Event("input"));
  });
  await expect(box.locator("[data-setup-timeline]")).toContainText(
    "SHORT_REVERSAL_CLOSED_PAST_RETEST",
  );
  expect(
    await box
      .locator("svg")
      .evaluateAll((nodes) =>
        nodes.every((svg) =>
          [...svg.querySelectorAll("[data-bar-at]")].every(
            (b) =>
              Date.parse(b.dataset.availableAt) <=
              Date.parse(svg.dataset.cutoff),
          ),
        ),
      ),
  ).toBe(true);
  const dl = page.waitForEvent("download");
  await page
    .locator("[data-research-kind='BACKTEST']")
    .first()
    .getByRole("button", { name: "Export research evidence", exact: true })
    .click();
  const report = JSON.parse(readFileSync(await (await dl).path(), "utf8"));
  expect(JSON.stringify(report)).toContain("FINITE_TARGET_90_PERCENT");
  await page
    .getByRole("button", {
      name: "Run matched first-touch control",
      exact: true,
    })
    .click();
  await expect(page.locator("[data-structural-comparison]")).toContainText(
    "FIRST_TOUCH",
  );
  await expect(page.locator("[data-structural-setups]")).toHaveCount(2);
  await page.reload();
  await expect(page.locator("[data-structural-comparison]")).toBeVisible();
  await page.locator("[data-language='zh']").click();
  await expect(page.locator("[data-structural-setups]").first()).toContainText(
    "结构化交易机会",
  );
  await page.screenshot({
    path: "test-results/structural-workflow.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
