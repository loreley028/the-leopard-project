import { Select } from "animal-island-ui";

export interface IslandSelectOption {
  value: string;
  label: string;
}

export function IslandSelect({ label, value, options, onChange, disabled = false }: { label: string; value: string; options: IslandSelectOption[]; onChange: (value: string) => void; disabled?: boolean }) {
  return <label className="island-field island-select"><span>{label}</span><Select aria-label={label} value={value} options={options.map(option => ({ key: option.value, label: option.label }))} onChange={onChange} disabled={disabled} placeholder="请选择" /></label>;
}
