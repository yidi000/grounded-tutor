import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./app";
import { demoFixture } from "./demo/fixture";

const ids = ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"];
const history = (name: string) => ({ exchanges: [{ question: `Question ${name}`, response: { ...demoFixture.exchange.response, answer_blocks: [{ ...demoFixture.exchange.response.answer_blocks[0], text: `Answer ${name}` }] }, legacy_content: null }] });
function serve(read: (id: string) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("capabilities")) return Response.json({ accepted_extensions: [".txt"], max_upload_bytes: 10000, settings: [], workspace_models: [], read_only_demo: false });
    if (url === "/api/workspaces") return Response.json(ids.map((id, i) => ({ id, title: `Topic ${i}`, source_count: 1, ready_source_count: 1, model_choices: { vector_model: null, agent_model: null, vlm_model: null }, created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z" })));
    if (url.endsWith("/sources")) return Response.json([]);
    if (url.endsWith("/chat/history")) return read(url.split("/")[3]);
    throw new Error(`Unexpected request ${url}`);
  }));
}
afterEach(() => window.history.replaceState(null, "", "/"));
async function selectTopic(index: number) {
  await userEvent.click(within(screen.getByRole("navigation", { name: "学习主题" })).getByText(`Topic ${index}`));
}
it("restores saved answers and citations after remount and retains the selected topic", async () => {
  serve((id) => Response.json(history(id === ids[0] ? "A" : "B")));
  const first = render(<App mode="local" />);
  expect(await screen.findByText("Answer A")).toBeVisible();
  await selectTopic(1);
  expect(await screen.findByText("Answer B")).toBeVisible();
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  first.unmount();
  render(<App mode="local" />);
  expect(await screen.findByText("Answer B")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: /引用 1/ }));
  expect(screen.getByRole("complementary", { name: "上下文" })).toHaveTextContent(demoFixture.exchange.response.citations[0].excerpt);
  await selectTopic(0);
  expect(await screen.findByText("Answer A")).toBeVisible();
  expect(screen.queryByText("Answer B")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "关闭引用详情" })).not.toBeInTheDocument();
});
it("does not allow a late history response to replace the selected topic", async () => {
  let resolveA!: (response: Response) => void;
  serve((id) => id === ids[0] ? new Promise(resolve => { resolveA = resolve; }) : Response.json(history("B")));
  render(<App mode="local" />);
  await screen.findByRole("heading", { name: "Topic 0" });
  await waitFor(() => expect(resolveA).toBeDefined());
  expect(screen.getByLabelText("向资料提问")).toBeDisabled();
  await selectTopic(1);
  expect(await screen.findByText("Answer B")).toBeVisible();
  await act(async () => resolveA(Response.json(history("A"))));
  expect(screen.queryByText("Answer A")).not.toBeInTheDocument();
  expect(screen.getByText("Answer B")).toBeVisible();
});
it("distinguishes history loading failure from empty history and supports retry", async () => {
  let failed = true;
  serve(() => failed ? Response.json({ detail: { code: "persistence_error" } }, { status: 500 }) : Response.json({ exchanges: [] }));
  render(<App mode="local" />);
  expect(await screen.findByText("暂时无法读取历史对话")).toBeVisible();
  expect(screen.getByLabelText("向资料提问")).toBeDisabled();
  failed = false;
  await userEvent.click(screen.getByRole("button", { name: "重新加载对话" }));
  await waitFor(() => expect(screen.getByLabelText("向资料提问")).toBeEnabled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "对话" })).not.toBeInTheDocument();
});
it("continues the restored conversation without duplicating its old answer", async () => {
  serve(() => Response.json(history("A")));
  const read = globalThis.fetch;
  let payload: Record<string, unknown> | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/chat") && init?.method === "POST") {
      payload = JSON.parse(String(init.body));
      return Response.json({ ...demoFixture.exchange.response, message_id: "00000000-0000-4000-8000-000000000099", answer_blocks: [{ ...demoFixture.exchange.response.answer_blocks[0], text: "New answer" }] });
    }
    return read(input, init);
  }));
  render(<App mode="local" />);
  await screen.findByText("Answer A");
  await userEvent.type(screen.getByLabelText("向资料提问"), "Follow up");
  await userEvent.click(screen.getByRole("button", { name: "发送" }));
  expect(await screen.findByText("New answer")).toBeVisible();
  expect(payload?.conversation_id).toBe(demoFixture.exchange.response.conversation_id);
  expect(screen.getAllByText("Answer A")).toHaveLength(1);
});
