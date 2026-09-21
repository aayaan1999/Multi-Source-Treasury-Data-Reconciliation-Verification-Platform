export default function Section({ title, description, action, children, id }) {
  return (
    <section className="mt-8" aria-labelledby={id}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={id} className="text-base font-semibold text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-ink2">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
