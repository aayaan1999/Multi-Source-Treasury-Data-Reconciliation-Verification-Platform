import { Link, useLocation } from "react-router-dom";
import TopBar from "../components/TopBar";

// Target for tile and alert clicks until the real screens exist; shows what the click asked for.
export default function Placeholder({ screen }) {
  const { search } = useLocation();
  return (
    <>
      <TopBar />
      <main className="card mx-auto mt-16 max-w-md rounded-xl border border-hair bg-surface p-6 text-center">
        <span
          aria-hidden
          className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full text-lg"
          style={{ background: "color-mix(in srgb, var(--series-1) 14%, transparent)", color: "var(--series-1)" }}
        >
          ⚑
        </span>
        <h1 className="text-lg font-semibold tracking-tight text-ink">{screen}</h1>
        <p className="mt-2 text-sm text-ink2">This screen isn't built yet.</p>
        {search && <p className="mt-2 text-sm text-muted">Requested view: {search}</p>}
        <Link to="/" className="mt-4 inline-block rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:brightness-110">
          Back to the executive summary
        </Link>
      </main>
    </>
  );
}
