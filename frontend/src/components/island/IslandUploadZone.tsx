import { useRef, useState } from "react";
import { IslandButton } from "./IslandButton";
export function IslandUploadZone({ onFile, buttonLabel = "选择 PDF", disabled = false }: { onFile: (file: File) => void; buttonLabel?: string; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null); const [name, setName] = useState("");
  const accept = (file?: File) => { if (file) { setName(file.name); onFile(file); } };
  return <div className="upload-zone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!disabled) accept(event.dataTransfer.files[0]); }}><input ref={input} type="file" accept="application/pdf,.pdf" disabled={disabled} onChange={event => accept(event.target.files?.[0])} /><IslandButton type="button" disabled={disabled} onClick={() => input.current?.click()}>{buttonLabel}</IslandButton><p>{name || "拖放 PDF 到这里，或使用键盘选择文件"}</p></div>;
}
