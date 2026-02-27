import type { ReactNode } from 'react';

interface TooltipProps {
  text: string;
  children: ReactNode;
}

export function Tooltip({ text, children }: TooltipProps) {
  return (
    <span className="group relative inline-flex cursor-help">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded border border-border bg-[#1c2128] px-2.5 py-1.5 text-xs font-normal text-text-primary opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 text-center leading-snug"
      >
        {text}
      </span>
    </span>
  );
}
