import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IslandStatusBadge } from "../components/island/IslandStatusBadge";
import { IslandUploadZone } from "../components/island/IslandUploadZone";
import { IslandDialog } from "../components/island/IslandDialog";

describe("island accessibility primitives", () => {
  it("announces status with visible text", () => { render(<IslandStatusBadge status="unsupported" />); expect(screen.getByText("暂不支持")).toBeVisible(); });
  it("keeps upload available as a real button", () => { render(<IslandUploadZone onFile={() => undefined} />); expect(screen.getByRole("button", { name: "选择 PDF" })).toBeEnabled(); });
  it("gives the adapted modal an accessible name", () => { render(<IslandDialog open title="许可复核" onClose={() => undefined}>内容</IslandDialog>); expect(screen.getByRole("dialog", { name: "许可复核" })).toHaveAttribute("aria-modal", "true"); });
});
