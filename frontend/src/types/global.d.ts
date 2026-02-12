/**
 * Type declarations for external modules
 * This file provides type definitions when node_modules is not installed locally
 * The actual types come from Docker container during build
 */

// React core types
declare module 'react' {
  export type ReactNode = any;
  export type ReactElement = any;
  export type FC<P = {}> = (props: P & { children?: ReactNode }) => ReactElement | null;
  export type ComponentType<P = {}> = FC<P>;
  export type RefObject<T> = { current: T | null };
  export type MutableRefObject<T> = { current: T };
  export type Dispatch<A> = (value: A) => void;
  export type SetStateAction<S> = S | ((prevState: S) => S);
  export type SVGProps<T> = any;
  export type FormEvent<T = Element> = any;
  export type ChangeEvent<T = Element> = any;
  export type MouseEvent<T = Element> = any;
  export type KeyboardEvent<T = Element> = any;
  export type Context<T> = any;
  
  export function useState<S>(initialState: S | (() => S)): [S, Dispatch<SetStateAction<S>>];
  export function useState<S = undefined>(): [S | undefined, Dispatch<SetStateAction<S | undefined>>];
  export function useEffect(effect: () => void | (() => void), deps?: readonly any[]): void;
  export function useRef<T>(initialValue: T): MutableRefObject<T>;
  export function useRef<T>(initialValue: T | null): RefObject<T>;
  export function useRef<T = undefined>(): MutableRefObject<T | undefined>;
  export function useCallback<T extends (...args: any[]) => any>(callback: T, deps: readonly any[]): T;
  export function useMemo<T>(factory: () => T, deps: readonly any[]): T;
  export function useContext<T>(context: Context<T>): T;
  export function createContext<T>(defaultValue: T): Context<T>;
  
  export default {} as any;
}

declare module 'react-dom' {
  export function createRoot(container: Element | DocumentFragment): any;
  export function render(element: any, container: Element | DocumentFragment | null): void;
  export default {} as any;
}

// Next.js
declare module 'next/navigation' {
  export function useRouter(): {
    push: (url: string) => void;
    replace: (url: string) => void;
    back: () => void;
    forward: () => void;
    refresh: () => void;
    prefetch: (url: string) => void;
  };
  export function usePathname(): string | null;
  export function useSearchParams(): URLSearchParams;
  export function useParams(): Record<string, string | string[]>;
  export function redirect(url: string): never;
}

declare module 'next/link' {
  import { FC, ReactNode } from 'react';
  interface LinkProps {
    href: string;
    as?: string;
    replace?: boolean;
    scroll?: boolean;
    shallow?: boolean;
    passHref?: boolean;
    prefetch?: boolean;
    locale?: string | false;
    className?: string;
    children?: ReactNode;
    onClick?: (e: any) => void;
  }
  const Link: FC<LinkProps>;
  export default Link;
}

// Lucide React Icons
declare module 'lucide-react' {
  import { FC, SVGProps } from 'react';
  
  interface IconProps extends SVGProps<SVGSVGElement> {
    size?: number | string;
    color?: string;
    strokeWidth?: number | string;
    className?: string;
  }
  
  type Icon = FC<IconProps>;
  
  export const Activity: Icon;
  export const AlertCircle: Icon;
  export const AlertTriangle: Icon;
  export const ArrowDown: Icon;
  export const ArrowUp: Icon;
  export const Award: Icon;
  export const BarChart3: Icon;
  export const Bell: Icon;
  export const Bot: Icon;
  export const Calendar: Icon;
  export const Check: Icon;
  export const ChevronDown: Icon;
  export const ChevronUp: Icon;
  export const Clock: Icon;
  export const Copy: Icon;
  export const Database: Icon;
  export const Eye: Icon;
  export const EyeOff: Icon;
  export const FileText: Icon;
  export const Info: Icon;
  export const Layers: Icon;
  export const LayoutDashboard: Icon;
  export const Loader2: Icon;
  export const Lock: Icon;
  export const LogOut: Icon;
  export const Mail: Icon;
  export const MapPin: Icon;
  export const Maximize2: Icon;
  export const Menu: Icon;
  export const MessageSquare: Icon;
  export const Mic: Icon;
  export const MicOff: Icon;
  export const Minimize2: Icon;
  export const Minus: Icon;
  export const Package: Icon;
  export const RefreshCw: Icon;
  export const RotateCcw: Icon;
  export const Send: Icon;
  export const Settings: Icon;
  export const Shield: Icon;
  export const ShoppingBag: Icon;
  export const Sparkles: Icon;
  export const Store: Icon;
  export const Tag: Icon;
  export const Target: Icon;
  export const Trash2: Icon;
  export const TrendingDown: Icon;
  export const TrendingUp: Icon;
  export const User: Icon;
  export const Users: Icon;
  export const Volume2: Icon;
  export const VolumeX: Icon;
  export const X: Icon;
  export const Zap: Icon;
}

// Recharts
declare module 'recharts' {
  import { FC, ReactNode } from 'react';
  
  interface BaseProps {
    children?: ReactNode;
    className?: string;
  }
  
  interface ChartProps extends BaseProps {
    data?: any[];
    width?: number | string;
    height?: number | string;
    margin?: { top?: number; right?: number; bottom?: number; left?: number };
    layout?: 'horizontal' | 'vertical';
  }
  
  export const AreaChart: FC<ChartProps>;
  export const BarChart: FC<ChartProps>;
  export const LineChart: FC<ChartProps>;
  export const PieChart: FC<ChartProps>;
  export const ComposedChart: FC<ChartProps>;
  export const ResponsiveContainer: FC<{ width?: number | string; height?: number | string; children?: ReactNode; className?: string }>;
  
  export const Area: FC<any>;
  export const Bar: FC<any>;
  export const Line: FC<any>;
  export const Pie: FC<any>;
  export const Cell: FC<any>;
  export const XAxis: FC<any>;
  export const YAxis: FC<any>;
  export const CartesianGrid: FC<any>;
  export const Tooltip: FC<any>;
  export const Legend: FC<any>;
  export const ReferenceLine: FC<any>;
}

// Date-fns
declare module 'date-fns' {
  export function format(date: Date | number, formatStr: string, options?: any): string;
  export function parseISO(dateString: string): Date;
  export function subDays(date: Date | number, amount: number): Date;
  export function addDays(date: Date | number, amount: number): Date;
  export function startOfDay(date: Date | number): Date;
  export function endOfDay(date: Date | number): Date;
  export function isToday(date: Date | number): boolean;
  export function differenceInDays(dateLeft: Date | number, dateRight: Date | number): number;
}

// Extend JSX namespace for intrinsic HTML elements
declare global {
  namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}

export {};
