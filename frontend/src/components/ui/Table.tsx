import { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

export function Table({ className, children, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line">
      <table className={cn('w-full text-sm', className)} {...props}>
        {children}
      </table>
    </div>
  );
}

export interface TableHeadProps extends HTMLAttributes<HTMLTableSectionElement> {
  /** Stick the header to the top of a scrolling container. */
  sticky?: boolean;
}

export function TableHead({ className, children, sticky, ...props }: TableHeadProps) {
  return (
    <thead
      className={cn('bg-surface-2/70', sticky && 'sticky top-0 z-10 backdrop-blur supports-[backdrop-filter]:bg-surface-2/80', className)}
      {...props}
    >
      {children}
    </thead>
  );
}

export function TableBody({ className, children, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody className={cn('divide-y divide-line', className)} {...props}>
      {children}
    </tbody>
  );
}

export interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {
  /** Subtle zebra tint for odd rows (token-based, RTL-safe). */
  zebra?: boolean;
}

export function TableRow({ className, children, zebra, ...props }: TableRowProps) {
  return (
    <tr
      className={cn('transition-colors hover:bg-teal-50/40', zebra && 'even:bg-surface-2/40', className)}
      {...props}
    >
      {children}
    </tr>
  );
}

export function Th({ className, children, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn('px-4 py-3 text-start text-xs font-semibold uppercase tracking-wide text-ink-muted', className)}
      {...props}
    >
      {children}
    </th>
  );
}

export function Td({ className, children, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={cn('px-4 py-3 text-ink', className)} {...props}>
      {children}
    </td>
  );
}
