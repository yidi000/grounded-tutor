import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { fileURLToPath } from "node:url";

for (const filename of ["slides.pptx", "workbook.xlsx"]) {
  test(`local ${filename} upload review accept and cited ASK`, async ({ page }, testInfo) => {
    test.skip(!testInfo.project.name.startsWith("local-"));
    await page.goto("/");
    await createWorkspace(page, `${filename} ${testInfo.project.name}`);
    await page.getByRole("button", { name: "＋ 添加资料" }).click();
    const dialog = page.getByRole("dialog", { name: "添加学习资料" });
    await dialog.locator('input[type="file"]').setInputFiles(fileURLToPath(new URL(`../../api/tests/fixtures/${filename}`, import.meta.url)));
    await dialog.getByRole("button", { name: "查看预计片段" }).click();
    await expect(dialog.getByText("本地估算")).toBeVisible();
    await dialog.getByRole("button", { name: "确认处理" }).click();
    await expect(dialog.getByText("实际处理结果")).toBeVisible();
    await dialog.getByRole("button", { name: "接受并用于问答" }).click();
    await dialog.getByRole("button", { name: "完成" }).click();
    await page.reload();
    await page.getByLabel("向资料提问").fill("What does this material explain?");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByRole("button", { name: `引用 1：${filename}` }).click();
    await expect(page.getByRole("complementary", { name: "上下文" })).toContainText(filename);
    await page.reload();
    await page.getByRole("button", { name: `引用 1：${filename}` }).click();
    await expect(page.getByRole("complementary", { name: "上下文" })).toContainText(filename);
    await expectDesktopContract(page);
  });
}

test("local paste review accept and keyboard-open cited ASK", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("local-"));
  await page.goto("/");
  await createWorkspace(page, `Intro Statistics ${testInfo.project.name}`);
  let uploads = 0;
  await page.route("**/sources/text", async (route) => {
    uploads += 1;
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({ response, json: { ...result, processed_preview: { ...result.processed_preview, items: [] } } });
  });
  await pasteAndAccept(page, "Week 1 notes", "Mean is an average.", testInfo);
  expect(uploads).toBe(1);

  const composer = page.getByLabel("向资料提问");
  await expect(composer).toBeEnabled();
  await composer.fill("What is a mean?");
  await page.getByRole("button", { name: "发送", exact: true }).click();

  const anchor = page.getByRole("button", { name: "引用 1：Week 1 notes" });
  await anchor.focus();
  await page.keyboard.press("Enter");
  const context = page.getByRole("complementary", { name: "上下文" });
  await expect(context).toContainText("Mean is an average.");
  await expect(context).toContainText("匹配片段 1");
  await page.getByRole("button", { name: "关闭引用详情" }).click();
  await expect(anchor).toBeFocused();
  await anchor.click();

  await expectDesktopContract(page);
  await page.screenshot({
    path: testInfo.outputPath(`grounded-tutor-task11-${testInfo.project.name}.png`),
    fullPage: false,
  });

  const originalTitle = `Intro Statistics ${testInfo.project.name}`;
  await createWorkspace(page, `Empty history ${testInfo.project.name}`);
  await expect(page.getByRole("button", { name: "引用 1：Week 1 notes" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: `Empty history ${testInfo.project.name}` })).toBeVisible();
  await page.getByRole("navigation", { name: "学习主题" }).getByText(originalTitle, { exact: true }).click();
  await page.getByRole("button", { name: "引用 1：Week 1 notes" }).click();
  await expect(page.getByRole("complementary", { name: "上下文" })).toContainText("Mean is an average.");
  await page.reload();
  await page.getByRole("button", { name: "引用 1：Week 1 notes" }).click();
  await expect(page.getByRole("complementary", { name: "上下文" })).toContainText("Mean is an average.");
  await page.screenshot({ path: testInfo.outputPath("restored-history.png") });
});

test("demo opens fixed citation and performs no write request", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("demo-"));
  const writes: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) writes.push(request.url());
  });

  await page.goto("/");
  await expect(page.getByText("示例主题")).toBeVisible();
  const anchor = page.getByRole("button", { name: /引用 1/ });
  await anchor.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "上下文" })).toContainText("RAG 学习笔记");
  await expect(page.getByText("这是预先生成的回答；真实提问请使用本地版本。")).toBeVisible();
  await expect(page.getByLabel("向资料提问")).toBeDisabled();
  expect(writes).toEqual([]);

  await page.getByRole("link", { name: "在本地使用我的资料" }).click();
  await expect(page).toHaveURL(/\/local-setup\.html$/);
  await expect(page.getByRole("heading", { name: "在本地运行 Grounded Tutor" })).toBeVisible();
  await expect(page.getByText(".venv/bin/pip install -e 'apps/api[test]'", { exact: false })).toBeVisible();
  await expect(page.getByText("make api-dev", { exact: true })).toBeVisible();
  await expect(page.getByText("npm --prefix apps/web run dev", { exact: true })).toBeVisible();
  await page.goBack();
  await page.getByRole("button", { name: /引用 1/ }).click();
  expect(writes).toEqual([]);

  await expectDesktopContract(page);
  await page.screenshot({
    path: testInfo.outputPath(`grounded-tutor-task11-${testInfo.project.name}.png`),
    fullPage: false,
  });
});

async function createWorkspace(page: Page, title: string) {
  await page.getByRole("button", { name: "创建学习主题" }).first().click();
  const dialog = page.getByRole("dialog", { name: "创建学习主题" });
  await dialog.getByLabel("主题名称").fill(title);
  await dialog.getByRole("button", { name: "创建主题", exact: true }).click();
  await page.getByRole("dialog", { name: "主题已创建" }).getByRole("button", { name: "进入主题" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
}

async function pasteAndAccept(page: Page, name: string, content: string, testInfo: TestInfo) {
  await page.getByRole("button", { name: "粘贴文本", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "添加学习资料" });
  await dialog.getByRole("button", { name: "粘贴文本", exact: true }).click();
  await dialog.getByLabel("资料名称").fill(name);
  await dialog.getByLabel("资料内容").fill(content);
  await dialog.getByRole("button", { name: "查看预计片段" }).click();
  await expect(dialog.getByText("本地估算")).toBeVisible();
  await dialog.getByRole("button", { name: "确认处理" }).click();
  await expect(dialog.getByText("实际处理结果")).toBeVisible();
  await expect(dialog.getByText(/可能仍在处理/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "接受并用于问答" })).toBeDisabled();
  await expectDesktopContract(page);
  await page.screenshot({ path: testInfo.outputPath("pending-source-preview.png") });
  await dialog.getByRole("button", { name: "刷新处理结果" }).click();
  await expect(dialog.getByText(content, { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "接受并用于问答" }).click();
  await expect(dialog.getByText("资料已准备好")).toBeVisible();
  await dialog.getByRole("button", { name: "完成" }).click();
}

async function expectDesktopContract(page: Page) {
  const layout = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
    center: document.querySelector(".conversation-surface")?.getBoundingClientRect().width ?? 0,
  }));
  expect(layout.scroll).toBe(layout.viewport);
  expect(layout.center).toBeGreaterThanOrEqual(640);
}
