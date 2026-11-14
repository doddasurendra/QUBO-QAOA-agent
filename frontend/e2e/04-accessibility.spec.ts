import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test, useCustomSpec } from "./fixtures";

// Automated WCAG 2.0 / 2.1 level A + AA checks with axe-core on every page and on key result views.
// axe evaluates the DOM/ARIA tree, which is engine-independent, so this spec runs in chromium only.
test.skip(({ browserName }) => browserName !== "chromium", "accessibility audit runs once, in chromium");

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function audit(page: Page, label: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const report = violations.map((v) =>
    `[${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node${v.nodes.length > 1 ? "s" : ""})\n` +
    v.nodes.slice(0, 12).map((n) => {
      const d = (n.any[0]?.data ?? {}) as { fgColor?: string; bgColor?: string; contrastRatio?: number };
      const colours = d.fgColor ? `  fg ${d.fgColor} on ${d.bgColor} = ${d.contrastRatio}:1` : "";
      return `    ${n.target.join(" ")}${colours}\n      ${n.html.slice(0, 140)}`;
    }).join("\n"));
  expect(report, `axe WCAG A/AA violations on ${label}:\n${report.join("\n")}`).toEqual([]);
}

const PAGES: [string, string][] = [
  ["/", "Overview"], ["/assistant", "AI Quantum Assistant"], ["/agents", "AI Agent Management"],
  ["/builder", "QUBO Model Builder"], ["/matrix", "QUBO Matrix Explorer"], ["/validation", "QUBO Validation"],
  ["/ising", "Ising Model Explorer"], ["/circuit", "QAOA Circuit Designer"], ["/qaoa", "QAOA Execution"],
  ["/simulator", "Quantum Simulator"], ["/providers", "Quantum Hardware Providers"], ["/classical", "Classical Solvers"],
  ["/hybrid", "Hybrid Optimization"], ["/industry", "Industry Solutions"], ["/benchmarks", "Benchmarking"],
  ["/experiments", "Experiment Management"], ["/datasets", "Dataset Management"], ["/research", "Quantum Research Library"],
  ["/results", "Results and Reports"], ["/api-keys", "API Management"], ["/users", "User and Role Management"],
  ["/admin", "Administration"], ["/usage", "Usage and Cost Monitoring"], ["/docs", "Documentation and Tutorials"],
];

test("login screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await audit(page, "login screen");
});

for (const [path, heading] of PAGES) {
  test(`page ${path} (${heading})`, async ({ signedIn: page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await audit(page, `${path} (${heading})`);
  });
}

test("result views: compiled QUBO, validation report, circuit diagram", async ({ signedIn: page }) => {
  await page.goto("/builder");
  await page.getByRole("button", { name: "Compile to QUBO" }).click();
  await expect(page.getByRole("img", { name: "QUBO matrix heatmap" })).toBeVisible();
  await audit(page, "builder with compiled QUBO");

  await page.goto("/validation");
  await useCustomSpec(page);
  await page.getByRole("button", { name: "Run validation" }).click();
  await expect(page.getByText("All exhaustive checks passed.")).toBeVisible();
  await audit(page, "validation report");

  await page.goto("/circuit");
  await useCustomSpec(page);
  await page.getByRole("button", { name: "Build" }).click();
  await expect(page.getByRole("img", { name: "QAOA circuit" })).toBeVisible();
  await audit(page, "circuit diagram");
});

test("hover states of primary and danger buttons keep AA contrast", async ({ signedIn: page }) => {
  await page.goto("/builder");
  await page.getByRole("button", { name: "Save as experiment & make active" }).click();
  await expect(page.getByText(/Saved as experiment #\d+/)).toBeVisible();
  await page.getByRole("button", { name: "Compile to QUBO" }).hover();          // .btn
  await audit(page, "primary button hovered");
  await page.goto("/experiments");
  await page.getByRole("button", { name: /^#\d+ my-model$/ }).first().click();
  await page.getByRole("button", { name: "Delete" }).hover();                    // .btn-danger (not clicked)
  await audit(page, "danger button hovered");
});

test("result views: industry formulation and mobile navigation", async ({ signedIn: page }) => {
  await page.goto("/industry");
  await page.getByRole("button", { name: "Risk-aware portfolio asset selection" }).click();
  await page.getByRole("button", { name: "Formulate & inspect" }).click();
  await expect(page.getByText(/decision \+/)).toBeVisible();
  await audit(page, "industry formulation");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "menu" }).click();
  await expect(page.locator("aside")).toBeVisible();
  await audit(page, "mobile navigation open");
});
