import { expect, test } from "@playwright/test";

test("delete confirms, retries, preserves another topic and clears the selected history", async ({ page }, info) => {
  test.skip(!info.project.name.startsWith("local-"));
  const kept = await (await page.request.post("/api/workspaces", { data: { title: "保留的主题" } })).json();
  const removed = await (await page.request.post("/api/workspaces", { data: { title: "待删除主题" } })).json();
  await page.goto(`/?workspace=${removed.id}`);
  await page.getByRole("button", { name: "删除学习主题：待删除主题", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "删除“待删除主题”？" });
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(page.getByRole("button", { name: "删除学习主题：待删除主题", exact: true })).toBeFocused();
  await page.route(`**/api/workspaces/${removed.id}`, async (route) => {
    if (route.request().method() === "DELETE") await route.fulfill({ status: 502, body: '{}' });
    else await route.continue();
  });
  await page.getByRole("button", { name: "删除学习主题：待删除主题", exact: true }).click();
  await dialog.getByRole("button", { name: "永久删除" }).click();
  await expect(dialog.getByRole("alert")).toContainText("重试");
  await page.unroute(`**/api/workspaces/${removed.id}`);
  await dialog.getByRole("button", { name: "永久删除" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "删除学习主题：待删除主题", exact: true })).toHaveCount(0);
  expect((await page.request.get(`/api/workspaces/${kept.id}`)).ok()).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("button", { name: "删除学习主题：待删除主题", exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("after-delete.png") });
});
