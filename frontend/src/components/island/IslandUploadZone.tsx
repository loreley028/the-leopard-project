import { useRef, useState } from "react";
import { IslandButton } from "./IslandButton";
export function IslandUploadZone({ onFile, buttonLabel = "选择 PDF", acceptTypes = "application/pdf,.pdf", emptyLabel = "拖放 PDF 到这里，或使用键盘选择文件", disabled = false }: { onFile: (file: File) => void; buttonLabel?: string; acceptTypes?: string; emptyLabel?: string; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null); const [name, setName] = useState("");
  const accept = (file?: File) => { if (file) { setName(file.name); onFile(file); } };
  return <div className="upload-zone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!disabled) accept(event.dataTransfer.files[0]); }}><input ref={input} type="file" accept={acceptTypes} disabled={disabled} onChange={event => accept(event.target.files?.[0])} /><IslandButton type="button" disabled={disabled} onClick={() => input.current?.click()}>{buttonLabel}</IslandButton><p>{name || emptyLabel}</p></div>;
}
