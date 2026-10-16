import { expect, test } from "@playwright/test";

// Numbers on the page come from imported result files, through the API.
test("benchmark page shows computed results with intervals and opens a recorded run", async ({ page, request }) => {
  const sources = await (await request.get("backend/api/v1/evaluations")).json();
  expect(sources.length).toBeGreaterThan(0);
  await page.goto("benchmark");
  await expect(page.getByTestId("benchmark-kpis")).toContainText("Baseline success");
  await expect(page.getByTestId("recovery-chart")).toContainText("FlightPath's suggested change");
  await expect(page.getByTestId("family-table")).toContainText("Wrong input (product name)");
  await page.getByTestId("case-table").locator("summary").click();
  const run = page.getByTestId("case-table").getByRole("link", { name: "baseline" }).first();
  await run.click();
  await expect(page.getByTestId("run-title")).toBeVisible();
});
