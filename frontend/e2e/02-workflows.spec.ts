import { KNAPSACK, download, expect, tag, test, useCustomSpec, useExperiment } from "./fixtures";

// End-to-end optimisation workflows, exactly as a user clicks through them. Tests run in order and
// share state: the experiment saved in the first test (named per browser project) is the model used later.
test.describe.configure({ mode: "serial" });

const modelName = () => `my-model-${tag()}`;

test("model builder: compile the default model, then save it as the active experiment", async ({ signedIn: page }) => {
  await page.goto("/builder");
  await page.getByLabel("Model name").fill(modelName());
  await page.getByRole("button", { name: "Compile to QUBO" }).click();
  const compiled = page.locator("section", { hasText: "Compiled QUBO" });
  await expect(compiled).toContainText("Decision variables: 3; slack variables: 0");
  await expect(page.getByRole("img", { name: "QUBO matrix heatmap" })).toBeVisible();
  await expect(page.getByText(/verified on all 8 assignments/)).toBeVisible();
  await page.getByRole("button", { name: "Save as experiment & make active" }).click();
  await expect(page.getByText(/Saved as experiment #\d+ and set as the active model/)).toBeVisible();
});

test("builder rejects invalid input with a clear message", async ({ signedIn: page }) => {
  await page.goto("/builder");
  await page.getByPlaceholder("new variable name").fill("9bad name");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("variable names");
});

test("validation proves the active model's QUBO is exact", async ({ signedIn: page }) => {
  await page.goto("/validation");
  await useExperiment(page, modelName());
  await page.getByRole("button", { name: "Run validation" }).click();
  await expect(page.getByText("All exhaustive checks passed.")).toBeVisible();
  await expect(page.locator("section", { hasText: "Exhaustive checks over 8" })).toContainText("pass");
});

test("matrix explorer, reduction and CSV export", async ({ signedIn: page }) => {
  await page.goto("/matrix");
  await useExperiment(page, modelName());
  await page.getByRole("button", { name: "Load matrix of active model" }).click();
  await expect(page.getByRole("img", { name: "QUBO matrix heatmap" })).toBeVisible();
  const csv = await download(page, () => page.getByRole("button", { name: "CSV" }).click());
  expect(csv.name).toBe("qubo-upper.csv");
  expect(csv.text.split("\n")[0]).toBe(",x0,x1,x2");             // header row = variable names
  await page.getByRole("button", { name: "Run safe variable reduction" }).click();
  await expect(page.locator("section", { hasText: "Variable reduction" })).toContainText("variables fixed");
});

test("ising explorer evaluates an assignment in both forms", async ({ signedIn: page }) => {
  await page.goto("/ising");
  await useExperiment(page, modelName());
  await page.getByRole("button", { name: "Load Ising form" }).click();
  await expect(page.getByText(/Fields h \(offset c =/)).toBeVisible();
  await page.getByLabel(/Bitstring/).fill("110");
  await page.getByRole("button", { name: "Evaluate" }).click();
  await expect(page.locator("pre").last()).toContainText('"feasible": true');
});

test("circuit designer draws the circuit and exports QASM 3", async ({ signedIn: page }) => {
  await page.goto("/circuit");
  await useExperiment(page, modelName());
  await page.getByRole("button", { name: "Build" }).click();
  await expect(page.getByRole("img", { name: "QAOA circuit" })).toBeVisible();
  await expect(page.getByText("two-qubit gates")).toBeVisible();
  const qasm = await download(page, () => page.getByRole("button", { name: "QASM 3" }).click());
  expect(qasm.name).toBe("qaoa.qasm");
  expect(qasm.text).toContain("OPENQASM 3");
});

test("QAOA execution runs as a background job and is labelled SIMULATOR", async ({ signedIn: page }) => {
  await page.goto("/qaoa");
  await useExperiment(page, modelName());
  await page.getByLabel("Restarts").fill("1");
  await page.getByLabel("Max iterations").fill("40");
  await page.getByRole("button", { name: "Run QAOA" }).click();
  await expect(page.getByText("SIMULATOR · statevector_simulator")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("approximation ratio")).toBeVisible();
  await expect(page.getByText("Convergence (best restart)")).toBeVisible();
  await expect(page.locator("section", { hasText: "Measured samples" }).locator("tbody tr").first()).toBeVisible();
});

test("quantum simulator shows the state and the p=1 landscape", async ({ signedIn: page }) => {
  await page.goto("/simulator");
  await useExperiment(page, modelName());
  await page.getByRole("button", { name: "Simulate state" }).click();
  await expect(page.getByText("Most probable basis states")).toBeVisible();
  await page.getByRole("button", { name: "Scan p=1 landscape" }).click();
  await expect(page.getByText("p = 1 landscape ⟨H⟩(γ, β)")).toBeVisible();
  await expect(page.getByText(/Minimum on the grid/)).toBeVisible();
});

test("classical exhaustive solver proves optimality on a custom spec", async ({ signedIn: page }) => {
  await page.goto("/classical");
  await useCustomSpec(page, KNAPSACK);
  await page.getByLabel("Solver").selectOption("exhaustive");
  await page.getByRole("button", { name: "Solve" }).click();
  const proven = page.locator("section", { hasText: "proven optimal" });
  await expect(proven).toContainText("yes", { timeout: 60_000 });
  await expect(page.locator("section", { hasText: /^objective/ })).toContainText("7");   // b + c, weight 5 ≤ 5
  await expect(page.locator("section", { hasText: "Best assignment" })).toContainText("011");
});

test("hybrid optimization ranks solvers against the proven optimum", async ({ signedIn: page }) => {
  await page.goto("/hybrid");
  await useExperiment(page, modelName());
  await expect(page.locator("section", { hasText: "Solver selection" }).locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "Run hybrid workflow" }).click();
  const ranking = page.locator("section", { hasText: "Ranking" });
  await expect(ranking).toContainText("proven optimum", { timeout: 90_000 });
  await expect(page.getByText(/No quantum advantage is claimed/)).toBeVisible();
});

test("industry solution: formulate the SAMPLE portfolio and solve it end to end", async ({ signedIn: page }) => {
  await page.goto("/industry");
  await page.getByRole("button", { name: "Risk-aware portfolio asset selection" }).click();
  await expect(page.getByText(/The pre-filled example is SAMPLE data/)).toBeVisible();
  await page.getByRole("button", { name: "Formulate & inspect" }).click();
  await expect(page.locator("section", { hasText: "Formulation" }).last()).toContainText("decision");
  await page.getByRole("button", { name: "Solve (auto hybrid)" }).click();
  const domain = page.locator("section", { hasText: "What this means for your problem" });
  await expect(domain).toContainText("satisfies every original constraint", { timeout: 120_000 });
  await expect(domain).toContainText("selected assets");
});

test("industry page lists every sector with its templates", async ({ signedIn: page }) => {
  await page.goto("/industry");
  for (const sector of ["Finance", "Healthcare", "Telecommunications", "Energy", "Logistics", "Manufacturing", "Supply chain"]) {
    await expect(page.getByRole("heading", { name: sector, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: /Two-echelon network design/ })).toBeVisible();
});

test("benchmarking runs a small reproducible study", async ({ signedIn: page }) => {
  await page.goto("/benchmarks");
  await page.getByLabel("Sizes n (comma-separated)").fill("5");
  await page.getByLabel("QAOA depths p (empty = none)").fill("1");
  await page.getByLabel("Seeds per instance").fill("1");
  await page.getByRole("checkbox", { name: "number_partitioning" }).uncheck();
  await page.getByRole("button", { name: "Run benchmark" }).click();
  await expect(page.getByText("Optimum hit rate by instance")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText(/do not demonstrate quantum advantage/)).toBeVisible();
});

test("results page lists jobs and downloads a Markdown report", async ({ signedIn: page }) => {
  await page.goto("/results");
  const first = page.locator("section", { hasText: "Jobs" }).getByRole("button", { name: /^#\d+$/ }).first();
  await first.click();
  await expect(page.getByRole("button", { name: "Report (.md)" })).toBeVisible();
  const report = await download(page, () => page.getByRole("button", { name: "Report (.md)" }).click());
  expect(report.name).toMatch(/^job-\d+-report\.md$/);
  expect(report.text).toContain("Real quantum hardware used: **NO");
});

test("experiments page shows the saved experiment with its job history", async ({ signedIn: page }) => {
  await page.goto("/experiments");
  await page.getByRole("button", { name: new RegExp(`^#\\d+ ${modelName()}$`) }).click();
  // jobs run with this experiment as the active model (validation-free ones: QAOA, hybrid, …) must be linked to it
  const detail = page.locator("section", { hasText: "Built in the QUBO Model Builder" });
  await expect(detail).not.toContainText("No jobs yet.");
  await expect(detail.locator("tr", { hasText: "qaoa" }).first()).toContainText("done");
  await expect(detail.locator("tr", { hasText: "hybrid" }).first()).toContainText("done");
});
