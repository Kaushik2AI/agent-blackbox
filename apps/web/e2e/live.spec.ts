import { expect, test } from "@playwright/test";

// The home page flow a visitor follows: run the agent, see where it broke, fix it.
test("live demo: scripted bug -> plain-language diagnosis -> one-click fix", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByTestId("how-it-works")).toBeVisible();
  await page.getByRole("radio", { name: /Scripted/ }).click();
  await page.getByTestId("scenario-bug_wrong_input").check({ force: true });
  await page.getByTestId("run-agent").click();

  const tape = page.getByTestId("tape").first();
  await expect(tape).toHaveAttribute("data-complete", "true", { timeout: 30_000 });
  // The 7 identical rejected calls are folded into one line after the run ends.
  await expect(page.getByTestId("repeat-group")).toContainText("6 more times");
  await expect(page.getByTestId("verdict")).toHaveAttribute("data-passed", "false");
  await expect(page.getByTestId("root-cause")).toContainText("Wrong input to the stock check");
  await expect(page.getByTestId("root-cause")).toContainText("stuck in a loop");

  await expect(page.locator("[data-testid=fix-panel][data-phase=ready]")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("run-fix").click();
  await expect(page.getByTestId("fix-result")).toContainText("Fixed by one change", { timeout: 60_000 });
  await page.getByTestId("open-comparison").click();
  await expect(page.getByTestId("comparison")).toBeVisible();
  await expect(page.getByTestId("caveat")).toContainText("Deterministic");
});
