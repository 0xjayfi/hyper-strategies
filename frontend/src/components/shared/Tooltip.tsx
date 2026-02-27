import { type ReactNode, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
  text: string;
  children: ReactNode;
}

export function Tooltip({ text, children }: TooltipProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const show = () => {
    const rect = ref.current?.getBoundingClientRect();
    if (rect) setPos({ x: rect.left + rect.width / 2, y: rect.top });
  };

  const hide = () => setPos(null);

  return (
    <span
      ref={ref}
      className="inline-flex cursor-help"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {pos &&
        createPortal(
          <span
            role="tooltip"
            className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded border border-border bg-[#1c2128] px-2.5 py-1.5 text-xs font-normal text-text-primary shadow-lg text-center leading-snug"
            style={{ left: pos.x, top: pos.y - 6 }}
          >
            {text}
          </span>,
          document.body,
        )}
    </span>
  );
}
