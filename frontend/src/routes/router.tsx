import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

type LocationState = { pathname: string; search: string; state: unknown };
type NavigateOptions = { replace?: boolean; state?: unknown };
type RouterContextValue = LocationState & { navigate: (to: string, options?: NavigateOptions) => void };

const RouterContext = createContext<RouterContextValue | null>(null);
const ParamsContext = createContext<Record<string, string>>({});

function parseTarget(target: string, state: unknown): LocationState {
  const url = new URL(target, "http://leopard.local");
  return { pathname: url.pathname, search: url.search, state };
}

function useRouter(): RouterContextValue {
  const value = useContext(RouterContext);
  if (!value) throw new Error("Router context is unavailable");
  return value;
}

export function BrowserRouter({ children }: { children: ReactNode }) {
  const current = () => ({ pathname: window.location.pathname, search: window.location.search, state: window.history.state });
  const [location, setLocation] = useState<LocationState>(current);
  useEffect(() => {
    const onPopState = () => setLocation(current());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const value = useMemo<RouterContextValue>(() => ({
    ...location,
    navigate: (to, options = {}) => {
      const next = parseTarget(to, options.state ?? null);
      window.history[options.replace ? "replaceState" : "pushState"](next.state, "", `${next.pathname}${next.search}`);
      setLocation(next);
    },
  }), [location]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function MemoryRouter({ children, initialEntries = ["/"] }: { children: ReactNode; initialEntries?: string[] }) {
  const [location, setLocation] = useState<LocationState>(() => parseTarget(initialEntries[0] ?? "/", null));
  const value = useMemo<RouterContextValue>(() => ({
    ...location,
    navigate: (to, options = {}) => setLocation(parseTarget(to, options.state ?? null)),
  }), [location]);
  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export function Link({ to, state, onClick, ...props }: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: string; state?: unknown }) {
  const { navigate } = useRouter();
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to, { state });
  };
  return <a {...props} href={to} onClick={handleClick} />;
}

export function useNavigate() {
  return useRouter().navigate;
}

export function useLocation(): Pick<LocationState, "pathname" | "search" | "state"> {
  const { pathname, search, state } = useRouter();
  return { pathname, search, state };
}

export function useParams<T extends Record<string, string | undefined> = Record<string, string | undefined>>(): T {
  return useContext(ParamsContext) as T;
}

export function useSearchParams(): [URLSearchParams, (next: URLSearchParams | string) => void] {
  const router = useRouter();
  return [
    useMemo(() => new URLSearchParams(router.search), [router.search]),
    next => router.navigate(`${router.pathname}?${String(next)}`),
  ];
}

type RouteProps = { path: string; element: ReactNode };
export function Route(props: RouteProps) {
  void props;
  return null;
}

function matchRoute(pattern: string, pathname: string): Record<string, string> | null {
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = pathname.split("/").filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;
  const params: Record<string, string> = {};
  for (let index = 0; index < patternParts.length; index += 1) {
    const expected = patternParts[index];
    const actual = pathParts[index];
    if (expected.startsWith(":")) params[expected.slice(1)] = decodeURIComponent(actual);
    else if (expected !== actual) return null;
  }
  return params;
}

export function Routes({ children }: { children: ReactNode }) {
  const { pathname } = useRouter();
  for (const child of Children.toArray(children)) {
    if (!isValidElement<RouteProps>(child)) continue;
    const params = matchRoute(child.props.path, pathname);
    if (params) return <ParamsContext.Provider value={params}>{child.props.element}</ParamsContext.Provider>;
  }
  return null;
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate();
  useEffect(() => navigate(to, { replace }), [navigate, replace, to]);
  return null;
}
