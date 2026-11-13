import { expect, test } from "./fixtures";

// sidebar link → page heading (all 24 pages)
const PAGES: [string, string][] = [
  ["Overview", "Overview"],
  ["AI Quantum Assistant", "AI Quantum Assistant"],
  ["AI Agents", "AI Agent Management"],
  ["Model Builder", "QUBO Model Builder"],
  ["Matrix Explorer", "QUBO Matrix Explorer"],
  ["Validation", "QUBO Validation"],
  ["Ising Explorer", "Ising Model Explorer"],
  ["QAOA Circuit Designer", "QAOA Circuit Designer"],
  ["QAOA Execution", "QAOA Execution"],
  ["Quantum Simulator", "Quantum Simulator"],
  ["Hardware Providers", "Quantum Hardware Providers"],
  ["Classical Solvers", "Classical Solvers"],
  ["Hybrid Optimization", "Hybrid Optimization"],
  ["Industry Solutions", "Industry Solutions"],
  ["Benchmarking", "Benchmarking"],
  ["Experiments", "Experiment Management"],
  ["Datasets", "Dataset Management"],
  ["Research Library", "Quantum Research Library"],
  ["Results & Reports", "Results and Reports"],
  ["API Management", "API Management"],
  ["Users & Roles", "User and Role Management"],
  ["Administration", "Administration"],
  ["Usage & Cost", "Usage and Cost Monitoring"],
  ["Docs & Tutorials", "Documentation and Tutorials"],
];

test("every one of the 24 pages opens from the sidebar and renders without errors", async ({ signedIn: page }) => {
  await page.goto("/");
  const nav = page.locator("aside nav");
  for (const [link, heading] of PAGES) {
    await nav.getByRole("link", { name: link, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: link, exact: true })).toHaveClass(/bg-indigo-50/);   // active state
  }
  expect(PAGES.length).toBe(24);
});

test("deep links load directly and unknown routes fall back to the overview", async ({ signedIn: page }) => {
  await page.goto("/qaoa");
  await expect(page.getByRole("heading", { name: "QAOA Execution" })).toBeVisible();
  await page.goto("/definitely-not-a-page");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("overview shows live counts and honest execution environment", async ({ signedIn: page }) => {
  await page.goto("/");
  await expect(page.getByText("Live figures from this installation's database.")).toBeVisible();
  await expect(page.getByText("AI agents:")).toContainText("unavailable");
  await expect(page.getByText("Real hardware providers configured:")).toContainText("none (SIMULATOR mode)");
});
