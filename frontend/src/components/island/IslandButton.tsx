import type { ButtonHTMLAttributes } from "react";
import { Button } from "animal-island-ui";

export function IslandButton({ className = "", type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const secondary = className.split(/\s+/).includes("secondary");
  return <Button className={`island-button ${className}`.trim()} type={secondary ? "default" : "primary"} htmlType={type} {...props} />;
}
