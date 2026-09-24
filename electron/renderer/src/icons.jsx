// Inline SVG icons (no icon font: the app is offline and the CSP blocks remote loads).
const stroke = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round', strokeLinejoin: 'round' };

// The Klaro mark from the Stitch design exports, coloured by tokens.
export function Mark({ size = 24 }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="4" fill="var(--accent)" />
      <g stroke="var(--on-accent)" strokeWidth="1.5" strokeLinecap="round" fill="none">
        <rect x="7" y="7" width="18" height="18" rx="2" />
        <line x1="11" y1="12" x2="21" y2="12" />
        <line x1="11" y1="16" x2="21" y2="16" />
        <line x1="11" y1="20" x2="17" y2="20" />
      </g>
    </svg>
  );
}

const Icon = ({ children, size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" {...stroke}>{children}</svg>
);

export const ArrowLeft = () => <Icon><path d="M13 8H3M7 4L3 8l4 4" /></Icon>;
export const Lock = () => <Icon><rect x="3.5" y="7" width="9" height="6.5" rx="1" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></Icon>;
export const Doc = () => <Icon><path d="M4 1.5h5.5L12.5 4.5v10h-8.5z" /><path d="M9.5 1.5v3h3M6 8h4.5M6 10.5h4.5" /></Icon>;
export const Upload = () => <Icon size={20}><path d="M8 11V2.5M4.5 6L8 2.5 11.5 6M2.5 11v2.5h11V11" /></Icon>;
export const Trash = () => <Icon><path d="M2.5 4h11M6 4V2.5h4V4M4 4l.7 9.5h6.6L12 4" /></Icon>;
export const Check = () => <Icon size={14}><path d="M3 8.5l3 3 7-7" /></Icon>;
export const Close = () => <Icon size={14}><path d="M4 4l8 8M12 4l-8 8" /></Icon>;
