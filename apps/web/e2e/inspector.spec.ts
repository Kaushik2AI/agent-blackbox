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
  await expect(page.getByRole("heading", { name: "invalid_inventory_argument" })).toBeVisible();
  await expect(page.getByText("budget_exhausted").first()).toBeVisible();

  // Click the exact failing tool span in the graph.
  const failing = page.locator('[data-testid=graph-node][data-error="SKU_REQUIRED"]').first();
  await expect(failing).toBeVisible();
  await failing.click();

  const inspector = page.getByTestId("span-inspector");
  await expect(inspector).toContainText("execute_tool lookup_inventory");
  await expect(page.getByTestId("error-code")).toHaveText("SKU_REQUIRED");
  await expect(inspector).toContainText("product_name");
  await expect(inspector).toContainText("validation_error");
});

test("overview numbers come from the API, not placeholders", async ({ page, request }) => {
  await page.goto("./");
  await expect(page.getByTestId("kpis")).toBeVisible();
  const api = await request.get("backend/api/v1/overview");
  const data = await api.json();
  await expect(page.getByTestId("kpis")).toContainText(String(data.total));
});

test("system page shows live readiness", async ({ page }) => {
  await page.goto("system");
  await expect(page.getByTestId("summary")).toHaveText("All systems ready", { timeout: 15_000 });
});
