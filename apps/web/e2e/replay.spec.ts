import { expect, type APIRequestContext, test } from "@playwright/test";

type Summary = { id: string; task_id: string; parent_execution_id: string | null };

async function findRun(request: APIRequestContext, capture: "content" | "metadata_only") {
  const page = await (await request.get("backend/api/v1/executions", {
    params: { task_id: "invalid_inventory_argument", limit: 100 },
  })).json();
  for (const r of page.items as Summary[]) {
    if (r.parent_execution_id) continue;
    const detail = await (await request.get(`backend/api/v1/executions/${r.id}`)).json();
    if (detail.attributes.capture_policy === capture) return r.id;
  }
  throw new Error(`no ${capture} invalid_inventory_argument run seeded; run make test-e2e`);
}

test("flagship: fix the SKU argument from a checkpoint and get a verifier-confirmed fork", async ({ page, request }) => {
  const id = await findRun(request, "content");
  await page.goto(`runs/${id}`);
  await expect(page.getByTestId("finding").first()).toBeVisible();
  await expect(page.locator('[data-testid=finding][data-category="tool_schema_mismatch"]')).toBeVisible();

  await page.getByTestId("open-replay-studio").click();
  await expect(page.getByRole("heading", { name: "Replay Studio" })).toBeVisible();
  const cp1 = page.locator('[data-testid=checkpoint-option][data-step="1"]');
  await expect(cp1.locator("input")).toBeChecked();
  await expect(cp1).toContainText("lookup_inventory");

  const editor = page.getByTestId("intervention-editor");
  await expect(editor).toHaveValue(/product_name/);
  await editor.fill('{"sku": "SKU-RED-004"}');
  await page.getByTestId("replay-submit").click();
  await page.getByTestId("replay-confirm").click();

  await expect(page.getByTestId("replay-job")).toHaveAttribute("data-status", "succeeded", { timeout: 30_000 });
  await expect(page.getByTestId("fork-verdict")).toContainText("passed");

  await page.getByTestId("open-comparison").click();
  await expect(page.getByTestId("comparison")).toBeVisible();
  await expect(page.getByTestId("fork-outcome").getByTestId("verifier")).toHaveText("passed");
  await expect(page.getByTestId("steps")).toContainText("SKU_REQUIRED");
  await expect(page.getByTestId("steps")).toContainText("SKU-RED-004");
  await expect(page.getByTestId("state-diff")).toContainText("added");
});

test("runs without captured state cannot be replayed: controls are disabled", async ({ page, request }) => {
  const id = await findRun(request, "metadata_only");
  await page.goto(`runs/${id}/replay`);
  await expect(page.getByTestId("replay-unavailable")).toBeVisible();
  await expect(page.getByTestId("replay-unavailable")).toContainText("metadata-only");
  await expect(page.getByRole("button", { name: "Run replay" })).toBeDisabled();
});
