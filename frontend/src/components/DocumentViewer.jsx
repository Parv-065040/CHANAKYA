import { useMemo } from "react";
import { ArrowSquareOut, DownloadSimple, FileText, X } from "@phosphor-icons/react";

const API = import.meta.env.VITE_API_URL || "";

export function DocumentViewer({ document, page = 1, onClose }) {
  const url = useMemo(() => {
    if (!document?.document_id) return "";
    return API + "/documents/" + document.document_id + "/file";
  }, [document]);

  const ext = (document?.name || "").split(".").pop()?.toLowerCase();
  const isPdf = ext === "pdf";
  const isCsv = ext === "csv";
  const pageUrl = url + (isPdf ? "#page=" + page : "");

  const download = () => {
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = document?.name || "document";
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    anchor.click();
  };

  return (
    <div className="viewer-overlay">
      <section className="document-viewer" role="dialog" aria-modal="true" aria-label="Document viewer">
        <header className="viewer-header">
          <div className="viewer-title">
            <div className="file-badge"><FileText size={18} /></div>
            <div><b>{document?.name || "Document"}</b><span>{document?.department || "—"} · page {page}</span></div>
          </div>
          <div className="viewer-actions">
            <button onClick={download} title="Download document"><DownloadSimple size={17} /><span>Download</span></button>
            <a href={pageUrl} target="_blank" rel="noreferrer" title="Open in browser"><ArrowSquareOut size={17} /><span>Open tab</span></a>
            <button onClick={onClose} title="Close"><X size={18} /></button>
          </div>
        </header>

        <div className="viewer-body">
          {isPdf ? (
            <iframe title={document?.name || "PDF"} src={pageUrl} className="pdf-frame" />
          ) : isCsv ? (
            <div className="non-pdf-view"><div className="non-pdf-icon"><FileText size={34} /></div><h2>CSV source</h2><p>This file is indexed as structured evidence. Open it in a new browser tab or download it to inspect the full table.</p><div className="viewer-cta"><a href={url} target="_blank" rel="noreferrer">Open file</a><button onClick={download}>Download CSV</button></div></div>
          ) : (
            <div className="non-pdf-view"><div className="non-pdf-icon"><FileText size={34} /></div><h2>Spreadsheet source</h2><p>Browser preview for XLSX is not reliable. Use the native file or download it for full inspection.</p><div className="viewer-cta"><a href={url} target="_blank" rel="noreferrer">Open file</a><button onClick={download}>Download XLSX</button></div></div>
          )}
        </div>
      </section>
    </div>
  );
}
