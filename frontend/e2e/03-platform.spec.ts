import { KNAPSACK, expect, signIn, test } from "./fixtures";

test.describe.configure({ mode: "serial" });

test("admin creates a user; the role change is reflected in the table", async ({ signedIn: page }) => {
  await page.goto("/users");
  await page.getByPlaceholder("email").fill("e2e-viewer@example.com");
  await page.getByPlaceholder("initial password (≥10)").fill("viewer-password-1");
  await page.locator("section", { hasText: "Create user" }).locator("select").selectOption("viewer");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("cell", { name: "e2e-viewer@example.com" })).toBeVisible();
});

test("RBAC: a researcher cannot see or open admin pages", async ({ page }) => {
  await signIn(page, "researcher");
  await page.goto("/");
  await expect(page.getByText("role: researcher")).toBeVisible();
  await expect(page.locator("aside").getByRole("link", { name: "Users & Roles" })).toHaveCount(0);
  await expect(page.locator("aside").getByRole("link", { name: "Administration" })).toHaveCount(0);
  await page.goto("/users");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});

test("API key is shown exactly once and listed by prefix", async ({ signedIn: page }) => {
  await page.goto("/api-keys");
  await page.getByPlaceholder("key name (e.g. notebook)").fill("e2e-key");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByText("Copy this key now")).toBeVisible();
  const key = await page.locator("code").first().innerText();
  expect(key).toMatch(/^qopt_/);
  await page.reload();
  await expect(page.getByText("Copy this key now")).toHaveCount(0);
  await expect(page.getByRole("cell", { name: "e2e-key" })).toBeVisible();
  await expect(page.getByText(key)).toHaveCount(0);
});

test("datasets: SAMPLE data for every template is clearly labelled", async ({ signedIn: page }) => {
  await page.goto("/datasets");
  await expect(page.getByText("SAMPLE", { exact: true }).first()).toBeVisible();
  expect(await page.getByText("SAMPLE", { exact: true }).count()).toBeGreaterThanOrEqual(27);
  await page.getByRole("row", { name: /Two-echelon network design/ }).getByRole("button", { name: "View" }).click();
  await expect(page.getByText(/Synthetic sample data/)).toBeVisible();
});

test("research library: upload a note and find it by search", async ({ signedIn: page }) => {
  await page.goto("/research");
  await page.getByLabel("Title").fill("E2E mixer notes");
  await page.locator('input[type="file"]').setInputFiles({
    name: "mixers.md", mimeType: "text/markdown",
    buffer: Buffer.from("The XY ring mixer preserves Hamming weight, so one-hot constraints stay satisfied. ".repeat(4)),
  });
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByRole("button", { name: "E2E mixer notes" })).toBeVisible();
  await page.getByPlaceholder("e.g. constraint-preserving mixer").fill("Hamming weight mixer");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.locator("section", { hasText: "Search" })).toContainText("E2E mixer notes");
});

test("AI agents report unavailable without credentials and disable sending", async ({ signedIn: page }) => {
  await page.goto("/assistant");
  await expect(page.getByText(/AI agents are/)).toContainText("unavailable");
  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.goto("/agents");
  await expect(page.getByText("Credentials on server: no")).toBeVisible();
  expect(await page.getByRole("button", { name: "Chat" }).count()).toBe(10);
});

test("hardware: providers report honest status; an approval request can be rejected by the admin", async ({ signedIn: page }) => {
  await page.goto("/providers");
  const ibm = page.getByRole("row", { name: /ibm_quantum/ });
  await expect(ibm).toContainText("no");               // not available
  await ibm.getByRole("button", { name: "Backends" }).click();
  await expect(page.locator("section", { hasText: "Backends · ibm_quantum" })).toContainText(/not installed|missing/);

  const form = page.locator("section", { hasText: "Request a real-hardware job" });
  await form.getByLabel("Experiment").selectOption({ index: 1 });
  await form.getByLabel("Backend / device ARN").fill("ibm_e2e_backend");
  await form.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.locator("section", { hasText: "Hardware requests" })).toContainText("pending");

  await page.goto("/admin");
  const req = page.locator("section", { hasText: "Hardware job approvals" }).getByRole("row", { name: /ibm_e2e_backend/ });
  await req.getByPlaceholder("note").fill("no IBM credentials in E2E");
  await req.getByRole("button", { name: "Reject" }).click();
  await expect(req).toContainText("rejected");
});

test("approving a job for an unavailable provider is refused with an explanation", async ({ signedIn: page, problems }) => {
  problems.allow4xx.push(/409 .*\/api\/approvals\/\d+\/approve/);
  page.on("dialog", (d) => d.accept());                // "Approve? This will submit a job…" confirm
  await page.goto("/providers");
  const form = page.locator("section", { hasText: "Request a real-hardware job" });
  await form.getByLabel("Experiment").selectOption({ index: 1 });
  await form.getByLabel("Backend / device ARN").fill("ibm_e2e_approve");
  await form.getByRole("button", { name: "Submit for approval" }).click();
  await page.goto("/admin");
  const req = page.locator("section", { hasText: "Hardware job approvals" }).getByRole("row", { name: /ibm_e2e_approve/ });
  await req.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("alert")).toContainText("unavailable");
  await expect(req).toContainText("pending");          // nothing was submitted
});

test("administration shows config without secrets and an audit trail", async ({ signedIn: page }) => {
  await page.goto("/admin");
  await expect(page.locator("section", { hasText: "Audit log" })).toContainText("bootstrap_admin");
  const cfg = page.locator("section", { hasText: "Configuration" }).locator("pre");
  await expect(cfg).toContainText('"jwt_secret_configured": true');
  await expect(cfg).not.toContainText("e2e-only-secret");
});

test("usage page and docs render real content", async ({ signedIn: page }) => {
  await page.goto("/usage");
  await expect(page.getByText("Compute time")).toBeVisible();
  await page.goto("/docs");
  await expect(page.locator("article").getByRole("heading", { name: "User guide" })).toBeVisible();
  await page.getByRole("button", { name: "Deployment" }).click();
  await expect(page.locator("article").getByRole("heading", { name: "Deployment", level: 1 })).toBeVisible();
});

test("viewer role can browse but cannot run jobs", async ({ page, request, problems }) => {
  problems.allow4xx.push(/403 /);
  const login = await request.post("/api/auth/login", { data: { email: "e2e-viewer@example.com", password: "viewer-password-1" } });
  const tok = (await login.json()).access_token;
  await page.addInitScript((t) => sessionStorage.setItem("qopt.token", t), tok);
  await page.goto("/classical");
  await expect(page.getByText("role: viewer")).toBeVisible();
  const card = page.locator("section", { hasText: "Active model" }).first();
  await card.getByRole("button", { name: "Custom spec (JSON)" }).click();
  await card.locator("textarea").fill(JSON.stringify(KNAPSACK));
  await card.getByRole("button", { name: "Use this model" }).click();
  await page.getByRole("button", { name: "Solve" }).click();
  await expect(page.getByRole("alert")).toContainText("403");
});

test("signing out returns to the login screen and clears the session", async ({ signedIn: page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("qopt.token"))).toBeNull();
});

test.describe("mobile viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("menu button opens the navigation and closes it after choosing a page", async ({ signedIn: page }) => {
    await page.goto("/");
    const nav = page.locator("aside");
    await expect(nav).toBeHidden();
    await page.getByRole("button", { name: "menu" }).click();
    await expect(nav).toBeVisible();
    await nav.getByRole("link", { name: "Industry Solutions" }).click();
    await expect(page.getByRole("heading", { name: "Industry Solutions" })).toBeVisible();
    await expect(nav).toBeHidden();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "no horizontal page scroll on phones").toBeLessThanOrEqual(1);
  });
});
