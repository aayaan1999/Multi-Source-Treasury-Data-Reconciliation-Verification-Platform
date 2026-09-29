// Client-side checks for a source's Connect form. The backend (app/connectors.py validate) checks the
// same rules again; these only decide whether "Connect & Save" is enabled and what to say.

const URL_RE = /^https:\/\/[^\s/$.?#][^\s]*$/;

/** Problems per field key for the current values; empty when the form can be sent. */
export function formProblems(fields, values) {
  const problems = {};
  for (const f of fields) {
    const v = (values[f.key] ?? "").trim();
    if (!v) {
      if (f.required) problems[f.key] = `${f.label} is required`;
    } else if (f.kind === "url" && !URL_RE.test(v)) {
      problems[f.key] = `${f.label} must start with https://`;
    } else if (f.kind === "port" && !(/^\d+$/.test(v) && +v > 0 && +v < 65536)) {
      problems[f.key] = `${f.label} must be a number from 1 to 65535`;
    }
  }
  return problems;
}

/** Only the filled-in fields, trimmed - what is sent to the server. */
export function filledValues(fields, values) {
  const out = {};
  for (const f of fields) {
    const v = (values[f.key] ?? "").trim();
    if (v) out[f.key] = v;
  }
  return out;
}

/** The form's starting values: a connected source's saved settings; secrets always start empty. */
export function initialValues(source) {
  const out = {};
  for (const f of source.fields) out[f.key] = f.kind === "secret" ? "" : (source.config?.[f.key] ?? "");
  return out;
}
