import type { SVGProps } from 'react';

/**
 * Nansen compass icon — stylized orbital paths with diamond center.
 * Recreated from Nansen Brand Guidelines (Aug 2023).
 */
export function NansenIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      {/* Three crossing elliptical orbital paths */}
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(0 32 32)"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(60 32 32)"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="24"
        ry="10"
        stroke="currentColor"
        strokeWidth="2.5"
        transform="rotate(120 32 32)"
      />
      {/* Center diamond point */}
      <rect
        x="29"
        y="29"
        width="6"
        height="6"
        rx="1"
        transform="rotate(45 32 32)"
        fill="currentColor"
      />
    </svg>
  );
}
