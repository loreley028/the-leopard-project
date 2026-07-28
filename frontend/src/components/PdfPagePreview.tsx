import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";

export function PdfPagePreview({ reportId, initialPage }: { reportId: string; initialPage?: number }) {
  const [pages, setPages] = useState<string[]>();
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.pdfPreview(reportId)
      .then(result => setPages(result.page_urls))
      .catch(error => setMessage(error instanceof ApiError ? error.message : "PDF预览暂不可用"));
  }, [reportId]);

  if (!pages) return <p role={message ? "alert" : "status"}>{message || "正在生成逐页预览…"}</p>;
  const ordered = initialPage && pages[initialPage - 1]
    ? [pages[initialPage - 1], ...pages.filter((_, index) => index !== initialPage - 1)]
    : pages;
  return <div className="pdf-page-preview" aria-label="原始PDF逐页预览">
    {ordered.map((url, index) => <figure key={url}>
      <img src={url} alt={`原始PDF第${initialPage && index === 0 ? initialPage : pages.indexOf(url) + 1}页`} loading="lazy" />
      <figcaption>第 {initialPage && index === 0 ? initialPage : pages.indexOf(url) + 1} 页</figcaption>
    </figure>)}
  </div>;
}
