import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IslandButton } from "../components/island/IslandButton";
import { IslandCard } from "../components/island/IslandCard";
import { IslandDialog } from "../components/island/IslandDialog";
import { IslandField } from "../components/island/IslandField";
import { IslandTag } from "../components/island/IslandTag";
import { IslandSelect } from "../components/island/IslandSelect";

describe("animal-island-ui adapter boundary", () => {
  it("loads the pinned library stylesheet once at the app entry", () => {
    const source = readFileSync(resolve(process.cwd(), "src/main.tsx"), "utf8");
    expect(source.match(/animal-island-ui\/style/g)).toHaveLength(1);
    expect(source).toContain("import 'animal-island-ui/style';");
  });

  it("wraps Button while preserving native submit semantics", () => {
    render(<IslandButton type="submit">保存</IslandButton>);
    const button = screen.getByRole("button", { name: "保存" });
    expect(button).toHaveAttribute("type", "submit");
    expect(button).toHaveClass("island-button");
  });

  it("wraps Card and Tag without changing their business content", () => {
    render(<IslandCard title="研究记录"><IslandTag>半导体</IslandTag></IslandCard>);
    expect(screen.getByRole("heading", { name: "研究记录" })).toBeVisible();
    expect(screen.getByText("半导体").closest(".island-tag")).not.toBeNull();
  });

  it("uses the library Modal with Escape close and focus restoration", async () => {
    const close = vi.fn();
    const user = userEvent.setup();
    function Example() {
      return <><button>打开者</button><IslandDialog open title="确认撤回" onClose={close}><p>请输入原因</p></IslandDialog></>;
    }
    render(<Example />);
    await waitFor(() => expect(screen.getByRole("dialog", { name: "确认撤回" })).toBeVisible());
    await user.keyboard("{Escape}");
    expect(close).toHaveBeenCalledOnce();
  });

  it("keeps form labels associated with library Input and native textarea", () => {
    render(<><IslandField label="报告标题" aria-invalid="true" /><IslandField label="核心观点" multiline /></>);
    expect(screen.getByLabelText("报告标题")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("核心观点").tagName).toBe("TEXTAREA");
  });

  it("adapts the controlled Select with an accessible label", async () => {
    const change = vi.fn();
    const user = userEvent.setup();
    render(<IslandSelect label="绑定板块" value="" options={[{ value: "semiconductor", label: "半导体" }]} onChange={change} />);
    const select = screen.getByRole("combobox", { name: "绑定板块" });
    await user.click(select);
    await user.keyboard("{Enter}");
    expect(change).toHaveBeenCalledWith("semiconductor");
  });

  it("does not close the dialog when ordinary content is clicked", () => {
    const close = vi.fn();
    render(<IslandDialog open title="复核" onClose={close}><button>内部操作</button></IslandDialog>);
    fireEvent.click(screen.getByRole("button", { name: "内部操作" }));
    expect(close).not.toHaveBeenCalled();
  });
});
