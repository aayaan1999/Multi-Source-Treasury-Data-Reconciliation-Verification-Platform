export default function Section({ title, eyebrow, description, action, children, id }) {
  return (
    <section className="mt-10" aria-labelledby={id}>
      <div className="mb-3.5 flex flex-wrap items-end justify-between gap-3 border-l-2 border-accent pl-3">
        <div>
          {eyebrow && <span className="kicker mb-1.5">{eyebrow}</span>}
          <h2 id={id} className="text-base font-semibold tracking-tight text-ink">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-ink2">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
