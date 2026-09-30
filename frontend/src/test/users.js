// Signed-in people for tests, with the `access` the server sends at login (a copy of backend/app/roles.py's
// table - specs/user-roles.md; backend/tests/test_roles.py checks the server side).
const ACCESS = {
  approver: {
    title: "Chief Financial Officer (CFO)", home: "/",
    screens: { summary: "full", portfolio: "full", performance: "full", scenario: "full", reports: "full", reconciliation: "read", tasks: "full", audit: "full", ingestion: "full", ask: "full" },
    tasks: { groups: ["cfo"] },
  },
  risk: {
    title: "Chief Risk Officer (CRO)", home: "/portfolio",
    screens: { summary: "full", portfolio: "full", performance: "full", scenario: "full", reports: "full", tasks: "full", ask: "full" },
    tasks: { types: ["breach"] },
  },
  analyst: {
    title: "Reconciliation Analyst", home: "/tasks",
    screens: { summary: "read", reconciliation: "full", tasks: "full", ingestion: "read", ask: "full" },
    tasks: { groups: ["operations"], types: ["data_quality", "entity_match"] },
  },
  compliance: { title: "Compliance Officer", home: "/tasks", screens: { summary: "read", tasks: "full", ask: "full" }, tasks: { types: ["fraud", "fraud_case"] } },
  auditor: {
    title: "Internal Auditor", home: "/audit-oversight", read_only: true, tasks: {},
    screens: { summary: "read", portfolio: "read", performance: "read", reports: "read", reconciliation: "read", audit: "full", ingestion: "read", ask: "full" },
  },
  admin: {
    title: "Platform Administrator", home: "/ingestion",
    screens: { summary: "read", reconciliation: "read", tasks: "full", audit: "full", ingestion: "full", ask: "full" },
    tasks: { all: true },
  },
};

const PEOPLE = {
  approver: [3, "CFO", "cfo@bankx.demo"], risk: [2, "CRO", "cro@bankx.demo"],
  analyst: [1, "Reconciliation Analyst", "recon.analyst@bankx.demo"], compliance: [5, "Compliance Officer", "compliance@bankx.demo"],
  auditor: [6, "Internal Auditor", "auditor@bankx.demo"], admin: [4, "Platform Admin", "admin@bankx.demo"],
};

export function userFor(role, extra = {}) {
  const [user_id, name, email] = PEOPLE[role];
  return { user_id, name, email, role, access: { read_only: false, ...ACCESS[role] }, ...extra };
}
