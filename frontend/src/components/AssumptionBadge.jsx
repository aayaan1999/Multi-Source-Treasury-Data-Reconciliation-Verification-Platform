import { useId, useState } from "react";
import { InfoIcon } from "./icons";

/**
 * A labelled "Assumption" button that opens a small popover listing the assumption(s) behind a number. Used wherever a
 * figure rests on a placeholder rather than measured data, so it is never presented as verified fact.
 * Hover, focus and click all open it; Escape closes it.
 */
export default function AssumptionBadge({
  items,
  label = "Assumption",
  heading = "Based on a demo assumption",
  footer = "A placeholder pending confirmation — not verified accounting.",
  align = "right",
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative z-10 inline-block shrink-0">
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="inline-flex items-center gap-1 rounded-full border border-hair px-2 py-0.5 text-xs text-ink2 hover:bg-page"
      >
        <InfoIcon />
        {label}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={`absolute ${align === "left" ? "left-0" : "right-0"} top-full z-20 mt-1 w-72 rounded-lg border border-hair bg-surface p-3 text-left text-xs leading-relaxed text-ink shadow-lg`}
        >
          <strong className="block text-ink">{heading}</strong>
          <ul className="mt-1 list-disc pl-4 text-ink2">
            {items.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          {footer && <span className="mt-1 block text-ink2">{footer}</span>}
        </span>
      )}
    </span>
  );
}
