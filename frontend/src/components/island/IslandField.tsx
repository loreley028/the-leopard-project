import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { Input } from "animal-island-ui";
type Props = { label: string; multiline?: boolean } & InputHTMLAttributes<HTMLInputElement> & TextareaHTMLAttributes<HTMLTextAreaElement>;
export function IslandField({ label, multiline, ...props }: Props) {
  const id = props.id ?? label.replaceAll(" ", "-");
  return <label className="island-field" htmlFor={id}><span>{label}</span>{multiline ? <textarea id={id} {...props} /> : <Input id={id} {...props} size="middle" />}</label>;
}
