import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { resolve, delimiter } from "node:path";
import { tmpdir } from "node:os";
let child, url;
const root = resolve("../..");
test.use({ ignoreHTTPSErrors: true }); // Ephemeral fixture CA only, never product configuration.
test.beforeAll(async () => {
  const dir = mkdtempSync(resolve(tmpdir(), "fx-owner-ui-"));
  const session = resolve(dir, "session.txt");
  child = spawn(
    process.env.FX_TEST_PYTHON || "python",
    [
      "tools/dashboard-tests/fixture_server.py",
      resolve(dir, "state"),
      session,
      "--owner",
    ],
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
  for (let i = 0; i < 150 && !existsSync(session); i++)
    await new Promise((r) => setTimeout(r, 100));
  if (!existsSync(session)) throw Error("Owner fixture did not start");
  url = readFileSync(session, "utf8");
});
test.afterAll(() => child?.kill());
test("owner signs in, reloads and revokes the browser session without trading authority", async ({
  page,
  context,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await expect(page.locator("#login-form")).toBeVisible();
  await expect(page.getByLabel("Session token", { exact: true })).toHaveCount(
    0,
  );
  await page.getByLabel("Username", { exact: true }).fill("owner");
  await page.getByLabel("Passphrase", { exact: true }).fill("incorrect");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("#notice")).toContainText("Sign-in denied");
  await expect(page.locator("#dashboard")).toBeHidden();
  await page
    .getByLabel("Passphrase", { exact: true })
    .fill("fixture-only-long-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator("#dashboard")).toBeVisible();
  expect(await page.evaluate(() => document.cookie)).toBe("");
  const cookies = await context.cookies();
  expect(cookies).toHaveLength(1);
  expect(cookies[0].httpOnly).toBe(true);
  expect(cookies[0].secure).toBe(true);
  expect(cookies[0].sameSite).toBe("Strict");
  expect(page.url()).not.toContain("token");
  await page.reload();
  await expect(page.locator("#dashboard")).toBeVisible();
  await expect(
    page.getByText("Trading disabled", { exact: true }),
  ).toBeVisible();
  await page.locator("#operator-read").click();
  await expect(page.locator("#operator-result")).toContainText("denied");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.locator("#dashboard")).toBeHidden();
  await page.reload();
  await expect(page.locator("#login-form")).toBeVisible();
  await expect(page.locator("#dashboard")).toBeHidden();
  expect(await context.cookies()).toHaveLength(0);
  expect(errors).toEqual([]);
});
