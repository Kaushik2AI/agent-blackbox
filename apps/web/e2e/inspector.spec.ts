import { expect, test } from "@playwright/test";

test("find the real invalid-inventory-argument failure and inspect the failing span", async ({ page }) => {
  await page.goto("runs");
  await page.getByLabel("Status").selectOption("failed");
  const row = page.locator('[data-testid=run-row][data-task="invalid_inventory_argument"]').first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("SKU_REQUIRED");

  // Keyboard path: focus the row and open it with Enter.
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run-title")).toBeVisible();
  // Plain-language step list first; the failing step says why it was rejected.
  await expect(page.locator('[data-testid=tape-step][data-error="SKU_REQUIRED"]').first()).toContainText("product code");

  // The raw trace is one click away: open it and click the failing tool span in the graph.
  await page.getByTestId("tab-trace").click();
  const failing = page.locator('[data-testid=graph-node][data-error="SKU_REQUIRED"]').first();
  await expect(failing).toBeVisible();
  await failing.click();

  const inspector = page.getByTestId("span-inspector");
  await expect(inspector).toContainText("execute_tool lookup_inventory");
  await expect(page.getByTestId("error-code")).toHaveText("SKU_REQUIRED");
  await expect(inspector).toContainText("product_name");
  await expect(inspector).toContainText("validation_error");
});

test("run counts come from the API, not placeholders", async ({ page, request }) => {
  await page.goto("runs");
  await expect(page.getByTestId("kpis")).toContainText("recorded");
  const api = await request.get("backend/api/v1/overview", { params: { project: "demo" } });
  const data = await api.json();
  await expect(page.getByTestId("kpis")).toContainText(String(data.total));
});

test("system page shows live readiness", async ({ page }) => {
  await page.goto("system");
  await expect(page.getByTestId("summary")).toHaveText("All systems ready", { timeout: 15_000 });
});
