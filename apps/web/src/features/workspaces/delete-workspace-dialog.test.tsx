import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DeleteWorkspaceDialog } from "./delete-workspace-dialog";

const workspace = { id: "00000000-0000-4000-8000-000000000001", title: "统计学", source_count: 2 };

it("names the destructive scope, focuses cancel, and sends no request on cancellation", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  const close = vi.fn();
  render(<DeleteWorkspaceDialog workspace={workspace} onClose={close} onDeleted={vi.fn()} />);
  expect(screen.getByText(/2 份资料/)).toBeVisible();
  expect(screen.getByText(/对话和学习进度/)).toBeVisible();
  await vi.waitFor(() => expect(screen.getByRole("button", { name: "取消" })).toHaveFocus());
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(close).toHaveBeenCalledOnce(); expect(fetchMock).not.toHaveBeenCalled();
});

it("retains confirmation after failure and completes only after a successful retry", async () => {
  const user = userEvent.setup(); const deleted = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 502 })).mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<DeleteWorkspaceDialog workspace={workspace} onClose={vi.fn()} onDeleted={deleted} />);
  await user.click(screen.getByRole("button", { name: "永久删除" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("重试");
  expect(deleted).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "永久删除" }));
  await vi.waitFor(() => expect(deleted).toHaveBeenCalledWith(workspace.id));
  expect(fetchMock).toHaveBeenLastCalledWith(`/api/workspaces/${workspace.id}`, expect.objectContaining({ method: "DELETE" }));
});
