import { useRef, useState } from "react";
import { IslandButton } from "./IslandButton";
export function IslandUploadZone({ onFile }: { onFile: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null); const [name, setName] = useState("");
  const accept = (file?: File) => { if (file) { setName(file.name); onFile(file); } };
  return <div className="upload-zone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); accept(event.dataTransfer.files[0]); }}><input ref={input} type="file" accept="application/pdf,.pdf" onChange={event => accept(event.target.files?.[0])} /><IslandButton type="button" onClick={() => input.current?.click()}>选择 PDF</IslandButton><p>{name || "拖放 PDF 到这里，或使用键盘选择文件"}</p></div>;
}
