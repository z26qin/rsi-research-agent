import { test, expect } from "@playwright/test";
test("desktop reading, search, review and Demo playback", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Good evening, Aaron." }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Open research" })).toHaveCount(
    3,
  );
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: "qa/dashboard-desktop.png" });
  await page.getByRole("link", { name: "Open research" }).first().click();
  await page.getByRole("tab", { name: /^Evidence/i }).click();
  await page.getByRole("button", { name: "Inspect evidence" }).first().click();
  await expect(page.getByText("EVIDENCE INSPECTOR")).toBeVisible();
  await page.screenshot({ path: "qa/evidence-desktop.png" });
  await page.getByRole("tab", { name: /^Verification/i }).click();
  await expect(page.getByRole("main")).toContainText("pass with caveats");
  await page.getByRole("link", { name: "Gaps", exact: true }).click();
  await expect(page.getByRole("main")).toContainText("OPEN");
  await page.getByRole("link", { name: "Research", exact: true }).click();
  await page
    .getByLabel("What would you like to investigate?")
    .fill("What is changing in momentum risk?");
  await page.getByRole("button", { name: "Start demo", exact: true }).click();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByRole("main")).toContainText("Paused");
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Continue", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Research complete" }),
  ).toBeVisible({ timeout: 22000 });
  await page.screenshot({ path: "qa/demo-desktop.png", fullPage: true });
  expect(errors).toEqual([]);
});
test("responsive pages and drawer have no body overflow", async ({ page }) => {
  for (const width of [1280, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Good evening, Aaron." }),
    ).toBeVisible();
    const sizes = await page.evaluate(() => ({
      inner: innerWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    expect(sizes.scroll).toBeLessThanOrEqual(sizes.inner);
    await page.screenshot({ path: `qa/home-${width}.png` });
  }
  const drawer = page.getByRole("button", { name: "Open research inspector" });
  await drawer.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeFocused();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "Sessions", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
