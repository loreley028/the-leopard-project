import type { ReactNode } from "react";
import { Modal } from "animal-island-ui";
import { IslandButton } from "./IslandButton";

export function IslandDialog({ open, title, children, onClose }: { open: boolean; title: string; children: ReactNode; onClose: () => void }) {
  return <Modal open={open} title={title} onClose={onClose} maskClosable footer={<IslandButton className="secondary" onClick={onClose}>关闭</IslandButton>} typewriter={false}>{children}</Modal>;
}
