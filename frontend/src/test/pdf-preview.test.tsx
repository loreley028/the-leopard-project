import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PdfPagePreview } from "../components/PdfPagePreview";
import { api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

describe("PDF preview failure boundary", () => {
  it("keeps the original PDF available when metadata fails", async () => {
    vi.spyOn(api, "pdfPreview").mockRejectedValue(new Error("worker crashed"));
    render(<PdfPagePreview reportId="report-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("PDF预览暂不可用，可打开原始PDF");
    expect(screen.getByRole("link", { name: "打开原始PDF" })).toHaveAttribute("href", "/api/v1/reports/report-1/pdf/open");
    expect(screen.getByRole("link", { name: "下载PDF" })).toHaveAttribute("href", "/api/v1/reports/report-1/pdf/download");
  });

  it("replaces failed page images with a local fallback without retrying or failing the report", async () => {
    const request = vi.spyOn(api, "pdfPreview").mockResolvedValue({ page_count: 2, page_urls: ["/page/1", "/page/2"], render_mode: "server_memory_png" });
    render(<><h1>报告概览仍可见</h1><PdfPagePreview reportId="report-1" /></>);
    const image = await screen.findByRole("img", { name: "原始PDF第1页" });
    expect(image).toHaveAttribute("loading", "lazy");
    fireEvent.error(image);
    expect(screen.getByRole("alert")).toHaveTextContent("PDF预览暂不可用");
    expect(screen.queryAllByRole("img")).toHaveLength(0);
    expect(screen.getByRole("heading")).toHaveTextContent("报告概览仍可见");
    expect(screen.getByRole("link", { name: "打开原始PDF" })).toHaveAttribute("href", "/api/v1/reports/report-1/pdf/open");
    expect(screen.getByRole("link", { name: "下载PDF" })).toHaveAttribute("href", "/api/v1/reports/report-1/pdf/download");
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("does not keep old report pages or a stale failure after report navigation", async () => {
    const request = vi.spyOn(api, "pdfPreview").mockResolvedValue({ page_count: 1, page_urls: ["/first/1"], render_mode: "server_memory_png" });
    const { rerender } = render(<PdfPagePreview reportId="first" />);
    fireEvent.error(await screen.findByRole("img"));
    request.mockResolvedValue({ page_count: 1, page_urls: ["/second/1"], render_mode: "server_memory_png" });
    rerender(<PdfPagePreview reportId="second" />);
    await waitFor(() => expect(screen.getByRole("img")).toHaveAttribute("src", "/second/1"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
