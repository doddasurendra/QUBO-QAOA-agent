import { test as base, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// package.json is "type": "module", so specs load as ES modules: no __dirname
export const AUTH_DIR = join(dirname(fileURLToPath(import.meta.url)), ".auth");
export const ADMIN = { email: "e2e-admin@example.com", password: "e2e-admin-password-1", name: "E2E Admin" };
export const RESEARCHER = { email: "e2e-researcher@example.com", password: "e2e-researcher-pass-1" };

export function token(role: "admin" | "researcher"): string {
  return JSON.parse(readFileSync(join(AUTH_DIR, `${role}.json`), "utf-8")).token;
}

/** Sign a page in by placing the session token where the SPA keeps it (sessionStorage). */
export async function signIn(page: Page, role: "admin" | "researcher" = "admin") {
  const t = token(role);
  await page.addInitScript((tok) => sessionStorage.setItem("qopt.token", tok), t);
}

type Problems = { console: string[]; server: string[]; allow4xx: RegExp[] };

export const test = base.extend<{ problems: Problems; signedIn: Page }>({
  // Every test fails if the page logs JS errors, throws, or the API returns 5xx (or an unexpected 4xx).
  problems: [async ({ page }, use) => {
    const p: Problems = { console: [], server: [], allow4xx: [] };
    page.on("console", (m) => { if (m.type() === "error") p.console.push(m.text()); });
    page.on("pageerror", (e) => p.console.push(`pageerror: ${e.message}`));
    page.on("response", (r) => {
      const u = r.url();
      if (!u.includes("/api/")) return;
      const s = r.status();
      if (s >= 500) p.server.push(`${s} ${r.request().method()} ${u}`);
      else if (s >= 400 && !p.allow4xx.some((re) => re.test(`${s} ${u}`))) p.server.push(`${s} ${r.request().method()} ${u}`);
    });
    await use(p);
    // Browsers also log every failed fetch as a console error. 4xx responses are already judged above
    // (against the per-test allow-list), so drop only those duplicate lines; everything else counts.
    const consoleErrors = p.console.filter((c) => !/Failed to load resource: the server responded with a status of 4\d\d/.test(c));
    expect.soft(p.server, "unexpected API error responses").toEqual([]);
    expect.soft(consoleErrors, "browser console errors").toEqual([]);
  }, { auto: true }],
  signedIn: async ({ page }, use) => {
    await signIn(page, "admin");
    await use(page);
  },
});

export { expect };

/** Select a model as the "active model" via the custom-spec JSON editor. */
export async function useCustomSpec(page: Page, spec?: object) {
  const card = page.locator("section", { hasText: "Active model" }).first();
  if (await card.getByRole("button", { name: "Change" }).isVisible().catch(() => false)) {
    await card.getByRole("button", { name: "Change" }).click();
  }
  await card.getByRole("button", { name: "Custom spec (JSON)" }).click();
  if (spec) await card.locator("textarea").fill(JSON.stringify(spec));
  await card.getByRole("button", { name: "Use this model" }).click();
  await expect(card).toContainText("Using");
}

/** Click something that downloads a file, wait for the file to be fully written, and return its name + text.
 *  (Closing a context while a download is still in flight crashed the installed Edge in this suite.) */
export async function download(page: Page, click: () => Promise<void>) {
  const pending = page.waitForEvent("download");
  await click();
  const d = await pending;
  const path = await d.path();                 // resolves only once the download has completed
  expect(await d.failure()).toBeNull();
  return { name: d.suggestedFilename(), text: readFileSync(path, "utf-8") };
}

/** Pick a saved experiment as the active model (the active model is per browser tab, so each test sets it). */
export async function useExperiment(page: Page, name: string) {
  const card = page.locator("section", { hasText: "Active model" }).first();
  if (await card.getByRole("button", { name: "Change" }).isVisible().catch(() => false)) {
    await card.getByRole("button", { name: "Change" }).click();
  }
  await card.getByRole("button", { name: "Saved experiment" }).click();
  const select = card.getByLabel("Experiment");
  const option = select.locator("option", { hasText: name }).first();
  await expect(option).toBeAttached();
  await select.selectOption(await option.getAttribute("value") as string);
  await expect(card).toContainText(`Using Experiment #`);
}

export const KNAPSACK = {
  name: "e2e-knapsack", variables: ["a", "b", "c"], sense: "max",
  objective: { linear: { a: 5, b: 4, c: 3 } },
  constraints: [{ label: "cap", lhs: { linear: { a: 4, b: 3, c: 2 } }, sense: "<=", rhs: 5 }],
};
