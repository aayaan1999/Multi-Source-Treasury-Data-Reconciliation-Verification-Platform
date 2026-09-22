import { useEffect } from "react";

/**
 * A centred overlay dialog: backdrop click, Escape, and a close button all dismiss it. Content
 * scrolls internally so a long review panel never grows past the viewport.
 */
export default function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-10 sm:pt-16" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="card w-full max-w-3xl rounded-xl border border-hair bg-surface shadow-lg"
      >
        <div className="flex items-start justify-between gap-3 border-b border-hair px-5 py-3.5">
          <h2 className="text-base font-semibold tracking-tight text-ink">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md border border-hair px-2.5 py-1 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink"
          >
            ✕
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}
