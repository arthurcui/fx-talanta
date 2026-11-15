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
    "--local-signin",
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
  dir = mkdtempSync(resolve(tmpdir(), "fx-local-auth-"));
  await start();
});
test.afterAll(() => child?.kill());
test("normal signup, persistent restart session, revoke all, sign in again", async ({
  page,
  browser,
}) => {
  await page.goto(url);
  await expect(page.locator("#login-title")).toHaveText(
    "Create your workspace sign-in",
  );
  await page.locator("#username").fill("fixture-owner");
  await page.locator("#password").fill("fixture-only-long-passphrase");
  await page.locator("#password-confirm").fill("different-password");
  await page.locator("#login-submit").click();
  await expect(page.locator("#notice")).toHaveText("Passphrases do not match.");
  await page.locator("#password-confirm").fill("fixture-only-long-passphrase");
  await page.locator("#login-submit").click();
  await expect(page.locator("#dashboard")).toBeVisible();
  const saved = await page.context().storageState();
  const cookies = saved.cookies.filter((c) => c.name.startsWith("fx_session_"));
  expect(cookies).toHaveLength(1);
  expect(cookies[0].httpOnly).toBe(true);
  expect(cookies[0].expires > Date.now() / 1000 + 29 * 86400).toBe(true);
  const exit = new Promise((r) => child.once("exit", r));
  child.kill();
  await exit;
  await start(true);
  const other = await browser.newContext({ storageState: saved });
  const second = await other.newPage();
  await second.goto(url);
  await expect(second.locator("#dashboard")).toBeVisible();
  await second.locator("#logout-all").click();
  await expect(second.locator("#login-form")).toBeVisible();
  await page.reload();
  await expect(page.locator("#login-title")).toHaveText(
    "Sign in to your workspace",
  );
  await expect(page.locator("#dashboard")).toBeHidden();
  await page.locator("#username").fill("fixture-owner");
  await page.locator("#password").fill("fixture-only-long-passphrase");
  await page.locator("#login-submit").click();
  await expect(page.locator("#dashboard")).toBeVisible();
  await page.locator("#logout").click();
  await expect(page.locator("#login-form")).toBeVisible();
  await other.close();
});
