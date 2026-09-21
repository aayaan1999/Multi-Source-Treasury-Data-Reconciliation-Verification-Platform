// Small inline icons. They inherit colour from `currentColor` unless a colour is passed.
const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", "aria-hidden": true, focusable: false };

export function CheckIcon({ color = "currentColor" }) {
  return (
    <svg {...base} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6.25" />
      <path d="M5.2 8.2l1.9 1.9 3.7-4" />
    </svg>
  );
}

export function WarningIcon({ color = "currentColor" }) {
  return (
    <svg {...base} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 2.2L14.2 13H1.8L8 2.2z" />
      <path d="M8 6.6v3M8 11.6v.1" />
    </svg>
  );
}

export function CrossIcon({ color = "currentColor" }) {
  return (
    <svg {...base} stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6.25" />
      <path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8" />
    </svg>
  );
}

export function DashIcon({ color = "currentColor" }) {
  return (
    <svg {...base} stroke={color} strokeWidth="2" strokeLinecap="round">
      <circle cx="8" cy="8" r="6.25" />
      <path d="M5.5 8h5" />
    </svg>
  );
}

export function ArrowIcon({ direction, color = "currentColor" }) {
  const d = direction === "up" ? "M8 13V3M4 7l4-4 4 4" : direction === "down" ? "M8 3v10M4 9l4 4 4-4" : "M3 8h10";
  return (
    <svg {...base} width="14" height="14" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

export function InfoIcon() {
  return (
    <svg {...base} width="14" height="14" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 7.4v3.6M8 5v.1" />
    </svg>
  );
}
