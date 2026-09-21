import { Link, useLocation } from "react-router-dom";
import TopBar from "../components/TopBar";

// Target for tile and alert clicks until the real screens exist; shows what the click asked for.
export default function Placeholder({ screen }) {
  const { search } = useLocation();
  return (
    <>
      <TopBar />
      <main className="mx-auto mt-16 max-w-md rounded-xl border border-hair bg-surface p-6 text-center">
        <h1 className="text-lg font-semibold text-ink">{screen}</h1>
        <p className="mt-2 text-sm text-ink2">This screen isn't built yet.</p>
        {search && <p className="mt-2 text-sm text-muted">Requested view: {search}</p>}
        <Link to="/" className="mt-4 inline-block rounded-md border border-hair px-3 py-1.5 text-sm text-ink hover:bg-page">
          Back to the executive summary
        </Link>
      </main>
    </>
  );
}
