import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { Link, MemoryRouter, Route, Routes } from "../routes/router";

test("links keep route matching internal while exposing the configured public prefix", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/"]}>
    <Link to="/sectors/cpo">CPO</Link>
    <Routes><Route path="/sectors/:sectorKey" element={<p>sector route</p>} /></Routes>
  </MemoryRouter>);
  const link = screen.getByRole("link", { name: "CPO" });
  expect(link).toHaveAttribute("href", "/sectors/cpo");
  await user.click(link);
  expect(screen.getByText("sector route")).toBeInTheDocument();
});
