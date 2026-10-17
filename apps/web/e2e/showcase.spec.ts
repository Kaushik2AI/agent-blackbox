import { expect, test } from "@playwright/test";

// The static showcase (NEXT_PUBLIC_SHOWCASE=1, served as plain files). Run with
// E2E_SHOWCASE=1 E2E_BASE_URL=http://127.0.0.1:<port>/agent-blackbox/ npx playwright test e2e/showcase.spec.ts
// (`make test-showcase` builds, serves and runs it). Skipped against the full app.
test.skip(!process.env.E2E_SHOWCASE, "showcase-only test");

test("recorded live run plays back, is diagnosed and fixed, with no server", async ({ page }) => {
  const failed: string[] = [];
  page.on("response", (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("./");
  await expect(page.getByTestId("showcase-banner")).toBeVisible();
  // Live AI is offered only on a real server.
  await expect(page.getByRole("radio", { name: /Live AI/ })).toBeDisabled();
  await page.getByRole("radio", { name: /Scripted/ }).click();
  await page.getByTestId("scenario-bug_wrong_input").check({ force: true });
  await page.getByTestId("run-agent").click();

  const tape = page.getByTestId("tape").first();
  await expect(tape).toHaveAttribute("data-complete", "true", { timeout: 30_000 });
  await expect(page.getByTestId("repeat-group")).toContainText("6 more times");
  await expect(page.getByTestId("root-cause")).toContainText("Wrong input to the stock check");
  await expect(page.locator("[data-testid=fix-panel][data-phase=ready]")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("run-fix").click();
  await expect(page.getByTestId("fix-result")).toContainText("Fixed by one change", { timeout: 30_000 });
  await page.getByTestId("open-comparison").click();
  await expect(page.getByTestId("comparison")).toBeVisible();
  expect(failed).toEqual([]);
});

test("stale data scenario: detected and fixed with the current record", async ({ page }) => {
  await page.goto("./");
  await page.getByRole("radio", { name: /Scripted/ }).click();
  await page.getByTestId("scenario-stale_stock").check({ force: true });
  await page.getByTestId("run-agent").click();
  await expect(page.getByTestId("tape").first()).toHaveAttribute("data-complete", "true", { timeout: 30_000 });
  await expect(page.getByTestId("root-cause")).toContainText("out-of-date data");
  await page.getByTestId("run-fix").click();
  await expect(page.getByTestId("fix-result")).toContainText("Fixed by one change", { timeout: 30_000 });
});

test("runs, a run page, Replay Studio and the benchmark load from the snapshot", async ({ page }) => {
  const failed: string[] = [];
  page.on("response", (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("runs/");
  const first = page.locator("table a[href*='/runs/']").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByTestId("run-title")).toBeVisible();
  await page.getByTestId("open-replay-studio").first().click();
  await expect(page).toHaveURL(/\/replay\/?$/);

  await page.goto("benchmark/");
  await expect(page.getByTestId("benchmark-kpis")).toContainText("Baseline success");
  await expect(page.getByTestId("family-table")).toContainText("Wrong input (product name)");
  // Real-model results are committed without their (large) traces, so only the scripted
  // results link to recorded runs. Pick those when several results are loaded.
  const picker = page.getByLabel("Benchmark results");
  if (await picker.count()) {
    const scripted = await picker.locator("option", { hasText: "stub" }).first().getAttribute("value");
    await picker.selectOption(scripted ?? "");
    await expect(page.getByTestId("benchmark-kpis")).toContainText("Baseline success");
  }
  await page.getByTestId("case-table").locator("summary").click();
  await page.getByTestId("case-table").getByRole("link", { name: "baseline" }).first().click();
  await expect(page.getByTestId("run-title")).toBeVisible();

  await page.goto("system/");
  await expect(page.getByText(/static snapshot/)).toBeVisible();
  expect(failed).toEqual([]);
});
