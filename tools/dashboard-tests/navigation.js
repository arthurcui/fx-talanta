export async function openPage(page, path) {
  if (new URL(page.url()).pathname === path) {
    if (path === "/strategies/backtest")
      await page.locator("#research-manual").evaluate((el) => {
        el.open = true;
      });
    return;
  }
  if (
    path.startsWith("/strategies/") &&
    (await page.locator("#strategy-flow").isVisible())
  ) {
    await page.locator(`#strategy-flow a[href="${path}"]`).click();
    if (path === "/strategies/backtest")
      await page.locator("#research-manual").evaluate((el) => {
        el.open = true;
      });
    return;
  }
  const section = path.startsWith("/strategies/") ? "/strategies" : path;
  await page.locator(`.sidebar nav a[href="${section}"]`).click();
  if (path.startsWith("/strategies/")) {
    await page.locator("#strategy-resume").click();
    if (path !== "/strategies/review")
      await page.locator(`#strategy-flow a[href="${path}"]`).click();
  }
  if (path === "/strategies/backtest")
    await page.locator("#research-manual").evaluate((el) => {
      el.open = true;
    });
}
