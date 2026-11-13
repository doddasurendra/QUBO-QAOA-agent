import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ADMIN, AUTH_DIR, RESEARCHER, expect, test } from "./fixtures";

test("first visit bootstraps the administrator through the UI", async ({ page, request }) => {
  mkdirSync(AUTH_DIR, { recursive: true });
  await page.goto("/");
  await expect(page.getByText("No users exist yet")).toBeVisible();
  await page.getByLabel("Name").fill(ADMIN.name);
  await page.getByLabel("Email").fill(ADMIN.email);
  await page.getByLabel("Password").fill(ADMIN.password);
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText(ADMIN.email)).toBeVisible();
  const tok = await page.evaluate(() => sessionStorage.getItem("qopt.token"));
  expect(tok).toBeTruthy();
  writeFileSync(join(AUTH_DIR, "admin.json"), JSON.stringify({ token: tok }));

  // bootstrap must now be closed
  const again = await request.post("/api/auth/bootstrap", { data: { email: "x@example.com", password: "another-pass-12" } });
  expect(again.status()).toBe(403);

  // researcher account for the RBAC tests (created through the admin API, logged in once)
  const auth = { Authorization: `Bearer ${tok}` };
  const created = await request.post("/api/users", { headers: auth, data: { ...RESEARCHER, role: "researcher", name: "E2E Researcher" } });
  expect(created.ok()).toBeTruthy();
  const login = await request.post("/api/auth/login", { data: RESEARCHER });
  expect(login.ok()).toBeTruthy();
  writeFileSync(join(AUTH_DIR, "researcher.json"), JSON.stringify({ token: (await login.json()).access_token }));
});
