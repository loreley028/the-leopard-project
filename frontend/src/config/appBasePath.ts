const normalizeBasePath = (value: string): string => {
  const trimmed = value.trim() || "/";
  const withLeadingSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const compact = withLeadingSlash.replace(/\/{2,}/g, "/");
  return compact.endsWith("/") ? compact : `${compact}/`;
};

/**
 * The build-time public mount path. The default keeps local development and a
 * future dedicated domain at the origin root; an IP subpath build sets
 * VITE_APP_BASE_PATH=/leopard/.
 */
export const APP_BASE_PATH = normalizeBasePath(import.meta.env.BASE_URL);

export function appPath(path = "/", basePath = APP_BASE_PATH): string {
  if (!path.startsWith("/")) return path;
  const normalizedBase = normalizeBasePath(basePath);
  const suffix = path.replace(/^\/+/, "");
  return normalizedBase === "/" ? `/${suffix}` : `${normalizedBase}${suffix}`;
}

export function appRoute(pathname: string, basePath = APP_BASE_PATH): string {
  const normalizedBase = normalizeBasePath(basePath);
  const baseWithoutTrailingSlash = normalizedBase.slice(0, -1);
  if (normalizedBase === "/") return pathname || "/";
  if (pathname === baseWithoutTrailingSlash || pathname === normalizedBase) return "/";
  if (pathname.startsWith(normalizedBase)) return `/${pathname.slice(normalizedBase.length)}`;
  return pathname || "/";
}

export function apiPath(path: string): string {
  return appPath(`/api/v1${path}`);
}
