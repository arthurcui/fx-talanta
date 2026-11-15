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
