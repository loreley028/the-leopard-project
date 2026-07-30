import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { Link, MemoryRouter, Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "../routes/router";

function Detail() {
  const { sectorKey } = useParams<{ sectorKey: string }>();
  const location = useLocation();
  const [query] = useSearchParams();
  return <p>{sectorKey}|{query.get("tab")}|{String((location.state as { from?: string } | null)?.from)}</p>;
}

test("internal router preserves parameters, query strings and link state", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/"]}>
    <Link to="/sectors/hotel_catering?tab=lineage" state={{ from: "matrix" }}>酒店餐饮</Link>
    <Routes><Route path="/sectors/:sectorKey" element={<Detail />} /></Routes>
  </MemoryRouter>);
  await user.click(screen.getByRole("link", { name: "酒店餐饮" }));
  expect(screen.getByText("hotel_catering|lineage|matrix")).toBeInTheDocument();
});

test("internal router redirects with replace semantics", async () => {
  render(<MemoryRouter initialEntries={["/private"]}>
    <Routes>
      <Route path="/private" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<h1>登录</h1>} />
    </Routes>
  </MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "登录" })).toBeInTheDocument();
});
