import { useEffect, useState } from "react";
import { api, publicResourcePath } from "../api/client";

const unavailable = "PDF预览暂不可用，可打开原始PDF";

export function PdfPagePreview({ reportId, initialPage }: { reportId: string; initialPage?: number }) {
  return <PdfPreviewPages key={reportId} reportId={reportId} initialPage={initialPage} />;
}

function PdfPreviewPages({ reportId, initialPage }: { reportId: string; initialPage?: number }) {
  const [pages, setPages] = useState<string[]>();
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    api.pdfPreview(reportId)
      .then(result => { if (active) setPages(result.page_urls); })
      .catch(() => { if (active) setMessage(unavailable); });
    return () => { active = false; };
  }, [reportId]);

  if (message) return <div role="alert"><p>{unavailable}</p><p className="pdf-preview-fallback-actions"><a href={publicResourcePath(`/api/v1/reports/${reportId}/pdf/open`)} target="_blank" rel="noreferrer">打开原始PDF</a><a href={publicResourcePath(`/api/v1/reports/${reportId}/pdf/download`)}>下载PDF</a></p></div>;
  if (!pages) return <p role="status">正在生成逐页预览…</p>;
  const ordered = initialPage && pages[initialPage - 1]
    ? [pages[initialPage - 1], ...pages.filter((_, index) => index !== initialPage - 1)]
    : pages;
  return <div className="pdf-page-preview" aria-label="原始PDF逐页预览">
    {ordered.map((url, index) => <figure key={url}>
      <img src={publicResourcePath(url)} alt={`原始PDF第${initialPage && index === 0 ? initialPage : pages.indexOf(url) + 1}页`} loading="lazy" onError={() => setMessage(unavailable)} />
      <figcaption>第 {initialPage && index === 0 ? initialPage : pages.indexOf(url) + 1} 页</figcaption>
    </figure>)}
  </div>;
}
