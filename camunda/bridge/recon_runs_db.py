"""Reconciliation runs and their sign-off (specs/reconciliation-approvals.md). A run is one delivery of a
pipeline source (its tasks: the gaps in that ingest batch) or one day's comparison with core banking or
the CRM (its tasks: the break groups of that source). Once every task in a run is decided, or from the
08:00 cut-off the next morning (recon.signoff), the bridge starts a reconciliation-run-signoff process; the
CFO signs off the decided tasks - the open ones are carried into a carry-over run with a high priority, and a
task carried 3 times is escalated - or sends named tasks back.

    sync_runs        creates each source's current run and files every task under one
    fetch_ready      runs whose tasks are all decided, or past their cut-off, with no sign-off yet
    close_run        the CFO's sign-off: never by anyone who decided a task in it; carries the open tasks
    send_back_run    reopens the named tasks; the bridge starts a new task for each

Plain psycopg2, no Zeebe, so the backend tests exercise it against a real Postgres.
"""
from datetime import date, datetime, timedelta, timezone

import psycopg2.extras

import recon_groups_db
import recon_tasks_db
import reconciliation_db

PROCESS_ID = "reconciliation-run-signoff"
RECORD_TYPE = "recon_run"
SOURCE_TABLE = "reconciliation_runs"
FLAG_LABEL = "RECON_RUN"
# What a run is called in a sentence, per source.
RUN_NAME = {"CORE_CSV": "core banking files", "neon": "core banking comparison", "salesforce": "CRM comparison"}
PIPELINE_DONE = ("DECIDED", "APPROVED")
RESOLVED = ("ACCEPTED", "CORRECTED", "DISMISSED")


DEFAULT_SIGNOFF = {"cutoff_time": "08:00", "utc_offset_hours": 3, "carry_limit": 3}


def signoff_settings(cur) -> dict:
    """recon.signoff: the cut-off (bank time, as UTC + offset) and the carry limit."""
    cur.execute("SELECT value FROM app_settings WHERE key = 'recon.signoff'")
    row = cur.fetchone()
    value = (row["value"] if isinstance(row, dict) else row[0]) if row else {}
    return {**DEFAULT_SIGNOFF, **(value or {})}


def bank_today(settings: dict, now: datetime = None) -> date:
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=settings["utc_offset_hours"])).date()


def cutoff(run_date: date, settings: dict) -> datetime:
    """When a run may be signed off with tasks still open: the cut-off time on the day after it, bank time."""
    hh, mm = (int(x) for x in settings["cutoff_time"].split(":"))
    local = datetime(run_date.year, run_date.month, run_date.day, hh, mm, tzinfo=timezone.utc) + timedelta(days=1)
    return local - timedelta(hours=settings["utc_offset_hours"])


def base_key(run_key: str) -> str:
    """'2026-09-25#c2' -> '2026-09-25': the data run a follow-on or carry-over run belongs to."""
    return run_key.split("#")[0]


def _run(cur, source_system: str, run_key: str, run_date) -> dict:
    cur.execute(
        """INSERT INTO reconciliation_runs (source_system, run_key, run_date) VALUES (%s, %s, %s)
           ON CONFLICT (source_system, run_key) DO NOTHING""",
        (source_system, run_key, run_date),
    )
    cur.execute("SELECT * FROM reconciliation_runs WHERE source_system = %s AND run_key = %s", (source_system, run_key))
    return cur.fetchone()


def sync_runs(conn) -> None:
    """Every source's current run exists, and every task is filed under one. Undecided tasks from an
    older run still open move to the current one; runs left behind that way are SUPERSEDED."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Pipeline sources: the run is the newest delivery (an older delivery's undecided items are
        # superseded by reconciliation_db, so they never move).
        cur.execute(
            """SELECT DISTINCT ON (source_system) source_system, ingest_batch_id, detected_at::date AS run_date
               FROM pipeline_reconciliation ORDER BY source_system, detected_at DESC"""
        )
        for src in cur.fetchall():
            batch = src["ingest_batch_id"]
            run = _run(cur, src["source_system"], batch, src["run_date"])
            cur.execute(
                """UPDATE pipeline_reconciliation SET run_id = %s
                   WHERE source_system = %s AND ingest_batch_id = %s AND has_gap AND status <> 'SUPERSEDED' AND run_id IS NULL""",
                (run["run_id"], src["source_system"], batch),
            )
            # Runs of an older delivery still open are replaced (their undecided items are superseded by
            # reconciliation_db); this delivery's carry-over runs stay.
            cur.execute(
                """UPDATE reconciliation_runs SET status = 'SUPERSEDED'
                   WHERE source_system = %s AND status = 'OPEN' AND run_key <> %s AND run_key NOT LIKE %s""",
                (src["source_system"], batch, batch + "#%"),
            )

        # Break sources: the run is the newest comparison date. A run already in sign-off takes no new
        # tasks: new groups that turn up then (a later comparison the same day) start a follow-on run.
        cur.execute("SELECT source_system, max(last_seen)::date AS run_date FROM reconciliation_exceptions GROUP BY source_system")
        for src in cur.fetchall():
            base = src["run_date"].isoformat()
            cur.execute(
                """SELECT * FROM reconciliation_runs WHERE source_system = %s AND (run_key = %s OR run_key LIKE %s)
                   ORDER BY run_id DESC LIMIT 1""",
                (src["source_system"], base, base + "#%"),
            )
            run = cur.fetchone()
            if run is None:
                run = _run(cur, src["source_system"], base, src["run_date"])
            elif run["status"] in ("IN_SIGNOFF", "SIGNED_OFF"):
                cur.execute("SELECT 1 FROM reconciliation_groups WHERE source_system = %s AND run_id IS NULL LIMIT 1", (src["source_system"],))
                if cur.fetchone():
                    cur.execute("SELECT count(*) AS n FROM reconciliation_runs WHERE source_system = %s AND (run_key = %s OR run_key LIKE %s)",
                                (src["source_system"], base, base + "#%"))
                    run = _run(cur, src["source_system"], f"{base}#{cur.fetchone()['n'] + 1}", src["run_date"])
            if run["status"] == "OPEN":
                cur.execute(
                    """UPDATE reconciliation_groups g SET run_id = %s
                       WHERE g.source_system = %s AND (g.run_id IS NULL OR (g.status <> 'CLOSED' AND g.run_id IN (
                           SELECT run_id FROM reconciliation_runs WHERE source_system = %s AND status = 'OPEN' AND run_id <> %s)))""",
                    (run["run_id"], src["source_system"], src["source_system"], run["run_id"]),
                )
                cur.execute("UPDATE reconciliation_runs SET status = 'SUPERSEDED' WHERE source_system = %s AND run_id <> %s AND status = 'OPEN'",
                            (src["source_system"], run["run_id"]))
    conn.commit()


UNDECIDED = """(
    (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.status NOT IN ('DECIDED', 'APPROVED', 'SUPERSEDED'))
  + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.status <> 'CLOSED')
  + (SELECT count(*) FROM reconciliation_exceptions e WHERE e.source_system = r.source_system AND e.status = 'OPEN' AND e.group_id IS NULL))"""


def undecided(cur, run_id: int) -> int:
    """Tasks in the run not decided yet (an important one waiting for the CFO counts), plus breaks of
    the source not in a group yet (they become tasks at the next poll)."""
    cur.execute(f"SELECT {UNDECIDED} AS n FROM reconciliation_runs r WHERE r.run_id = %s", (run_id,))
    return cur.fetchone()["n"]


def fetch_ready(conn, now: datetime = None) -> list:
    """OPEN runs not yet in sign-off whose every task is decided, or that are past their cut-off (08:00 the
    next morning): then the CFO signs off what's decided and the rest is carried."""
    now = now or datetime.now(timezone.utc)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        settings = signoff_settings(cur)
        cur.execute(f"SELECT r.*, {UNDECIDED} AS undecided FROM reconciliation_runs r WHERE r.status = 'OPEN' AND r.process_instance_key IS NULL ORDER BY r.run_id")
        return [r for r in cur.fetchall() if r["undecided"] == 0 or now >= cutoff(r["run_date"], settings)]


def title(run: dict) -> str:
    """E.g. "Sign off the core banking comparison of 25 Sep 2026"."""
    d = run["run_date"]
    name = RUN_NAME.get(run["source_system"], f"{run['source_system']} run")
    part = run["run_key"].split("#")[1] if "#" in run["run_key"] else ""
    suffix = " (carried over)" if part.startswith("c") else f" (part {part})" if part else ""
    return f"Sign off the {name} of {d.day} {d:%b %Y}{suffix}"


def process_variables(run: dict, today: date = None) -> dict:
    today = today or date.today()
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(run["run_id"]),
        "flagLabel": FLAG_LABEL,
        "title": title(run),
        "severity": "MEDIUM",
        "dueDate": (today + timedelta(days=1)).isoformat(),
    }


def record_started(conn, run_id: int, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE reconciliation_runs SET status = 'IN_SIGNOFF', process_instance_key = %s WHERE run_id = %s AND status = 'OPEN'",
                    (process_instance_key, run_id))
    conn.commit()


def _deciders(cur, run_id: int) -> list:
    cur.execute(
        """SELECT decided_by FROM pipeline_reconciliation WHERE run_id = %s AND decided_by IS NOT NULL
           UNION ALL SELECT decided_by FROM reconciliation_groups WHERE run_id = %s AND decided_by IS NOT NULL""",
        (run_id, run_id),
    )
    return [r["decided_by"] for r in cur.fetchall()]


def _counts(cur, run_id: int) -> dict:
    cur.execute(
        """SELECT (SELECT count(*) FROM pipeline_reconciliation WHERE run_id = %s AND status IN ('DECIDED', 'APPROVED'))
                + (SELECT count(*) FROM reconciliation_groups WHERE run_id = %s AND status = 'CLOSED') AS decided,
                  (SELECT count(*) FROM pipeline_reconciliation WHERE run_id = %s AND status = 'AWAITING_CFO')
                + (SELECT count(*) FROM reconciliation_groups WHERE run_id = %s AND status = 'AWAITING_CFO') AS awaiting_cfo""",
        (run_id,) * 4,
    )
    return cur.fetchone()


def _carry(cur, run: dict, settings: dict, who: dict, now: datetime) -> int:
    """Moves the run's open tasks into a carry-over run for today: carried once more, from the day they were
    first open; escalated (with an audit row) once carried carry_limit times. Returns the carry run's id."""
    base = base_key(run["run_key"])
    cur.execute("SELECT count(*) AS n FROM reconciliation_runs WHERE source_system = %s AND run_key LIKE %s",
                (run["source_system"], base + "#c%"))
    carry = _run(cur, run["source_system"], f"{base}#c{cur.fetchone()['n'] + 1}", bank_today(settings, now))
    for table, id_col, open_statuses, object_type in (
        ("pipeline_reconciliation", "recon_id", ("OPEN", "WITH_TEAM"), "reconciliation_item"),
        ("reconciliation_groups", "group_id", ("PENDING", "OPEN"), "reconciliation_group"),
    ):
        cur.execute(
            f"""UPDATE {table} SET run_id = %s, carried_count = carried_count + 1,
                       carried_since = COALESCE(carried_since, %s),
                       escalated_at = CASE WHEN carried_count + 1 >= %s THEN COALESCE(escalated_at, now()) END
                WHERE run_id = %s AND status IN %s
                RETURNING {id_col} AS id, carried_count, escalated_at IS NOT NULL AS escalated""",
            (carry["run_id"], run["run_date"], settings["carry_limit"], run["run_id"], open_statuses),
        )
        for row in cur.fetchall():
            recon_tasks_db._audit(cur, who["user_id"], "CARRIED_OVER", object_type, row["id"], None, f"carried {row['carried_count']}x")
            if row["escalated"] and row["carried_count"] == settings["carry_limit"]:
                recon_tasks_db._audit(cur, who["user_id"], "ESCALATED", object_type, row["id"], None,
                                      f"carried {row['carried_count']} times without a decision")
    return carry["run_id"]


def close_run(conn, run_id, signed_by, note=None, now: datetime = None) -> dict:
    """The CFO signs off the run's decided tasks. Before the cut-off every task must be decided; from the
    cut-off the open ones are carried to the next day (a note saying why is required). Refused
    (signoffOk false, signoffError) for anyone who decided a task in it, anyone but the CFO or an admin,
    or while a task waits for the CFO's own approval."""
    now = now or datetime.now(timezone.utc)
    note = (note or "").strip() or None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        settings = signoff_settings(cur)
        cur.execute("SELECT * FROM reconciliation_runs WHERE run_id = %s FOR UPDATE", (int(run_id),))
        run = cur.fetchone()
        who = recon_tasks_db.user(cur, signed_by)
        counts = _counts(cur, run["run_id"]) if run else {}
        open_n = undecided(cur, run["run_id"]) if run else 0
        mine = _deciders(cur, run["run_id"]).count(who["user_id"]) if run and who else 0
        if run is None:
            result = dict(signoffOk=False, signoffError="This run no longer exists.")
        elif run["status"] == "SIGNED_OFF" and who and run["signed_by"] == who["user_id"]:
            result = dict(signoffOk=True, signoffError="")                   # a retried job
        elif run["status"] != "IN_SIGNOFF":
            result = dict(signoffOk=False, signoffError=f"This run isn't waiting for sign-off (it is {run['status'].lower().replace('_', ' ')}).")
        elif who is None:
            result = dict(signoffOk=False, signoffError="The sign-off didn't say who signed. Sign off again.")
        elif who["role"] not in recon_tasks_db.CFO_ROLES:
            result = dict(signoffOk=False, signoffError=f"Only the CFO or the Platform Administrator can sign off a run; {who['name']} can't.")
        elif counts["awaiting_cfo"]:
            result = dict(signoffOk=False, signoffError=f"Approve or send back the {counts['awaiting_cfo']} task(s) waiting for you first.")
        elif open_n and now < cutoff(run["run_date"], settings):
            result = dict(signoffOk=False, signoffError=(
                f"{open_n} task(s) aren't decided yet. Before the {settings['cutoff_time']} cut-off a run is signed off only once every task is decided."))
        elif open_n and not note:
            result = dict(signoffOk=False, signoffError=f"Say why the {open_n} open task(s) are carried over to the next day.")
        elif mine:
            result = dict(signoffOk=False, signoffError=(
                f"{who['name']} decided {mine} task(s) in this run, so a different person has to sign it off."))
        else:
            carry_run = _carry(cur, run, settings, who, now) if open_n else None
            cur.execute(
                """UPDATE reconciliation_runs SET status = 'SIGNED_OFF', signed_by = %s, signed_at = now(), sign_note = %s,
                          signed_tasks = %s, carried_tasks = %s, carried_to_run_id = %s WHERE run_id = %s""",
                (who["user_id"], note, counts["decided"], open_n, carry_run, run["run_id"]),
            )
            recon_tasks_db._audit(cur, who["user_id"], "RUN_SIGNED_OFF", "reconciliation_run",
                                  f"{run['source_system']}:{run['run_key']}", "IN_SIGNOFF",
                                  f"{counts['decided']} signed off, {open_n} carried over" + (f": {note}" if note else ""))
            result = dict(signoffOk=True, signoffError="")
    if result["signoffOk"]:
        conn.commit()
    else:
        conn.rollback()
    return result


def send_back_run(conn, run_id, sent_back_by, tasks, note) -> dict:
    """The CFO sends named tasks back: each is reopened (its decision undone, breaks open again, fixes not
    yet applied withdrawn) and the run is open again; the bridge starts a new task for each, and a new
    sign-off once they're decided."""
    tasks = tasks or []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM reconciliation_runs WHERE run_id = %s FOR UPDATE", (int(run_id),))
        run = cur.fetchone()
        who = recon_tasks_db.user(cur, sent_back_by)
        refuse = None
        if run is None:
            refuse = "This run no longer exists."
        elif run["status"] == "OPEN" and run["process_instance_key"] is None:
            conn.rollback()
            return dict(signoffOk=True, signoffError="")                     # a retried job: already reopened
        elif run["status"] != "IN_SIGNOFF":
            refuse = "This run isn't waiting for sign-off."
        elif who is None or who["role"] not in recon_tasks_db.CFO_ROLES:
            refuse = "Only the CFO or the Platform Administrator can send tasks back."
        elif not (note or "").strip():
            refuse = "Say why the tasks are being sent back."
        elif not tasks:
            refuse = "Pick at least one task to send back."
        if refuse is None:
            for t in tasks:
                kind, key = t.get("kind"), int(t.get("id"))
                if kind == reconciliation_db.RECORD_TYPE:
                    cur.execute(
                        """UPDATE pipeline_reconciliation SET status = 'OPEN', decision = NULL, decided_by = NULL, decided_at = NULL,
                                  approved_by = NULL, approved_at = NULL
                           WHERE recon_id = %s AND run_id = %s AND status IN %s RETURNING recon_id""",
                        (key, run["run_id"], PIPELINE_DONE),
                    )
                    if cur.fetchone() is None:
                        refuse = f"Item #{key} isn't a decided task of this run."
                        break
                    cur.execute("DELETE FROM camunda_process_tracking WHERE record_type = %s AND source_table = %s AND record_key = %s",
                                (reconciliation_db.RECORD_TYPE, reconciliation_db.SOURCE_TABLE, str(key)))
                    cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE recon_id = %s AND status IN ('PROPOSED', 'APPROVED') AND synced_at IS NULL", (key,))
                    recon_tasks_db._audit(cur, who["user_id"], "SENT_BACK_AT_SIGNOFF", "reconciliation_item", key, None, note.strip())
                    recon_tasks_db.mark_sent_back(cur, kind, key, who["user_id"], note, "RUN_SIGNOFF")
                elif kind == recon_groups_db.RECORD_TYPE:
                    cur.execute(
                        """UPDATE reconciliation_groups SET status = 'PENDING', process_instance_key = NULL, decision = NULL,
                                  decided_by = NULL, decided_at = NULL, approved_by = NULL, approved_at = NULL, closed_at = NULL
                           WHERE group_id = %s AND run_id = %s AND status = 'CLOSED' RETURNING group_id""",
                        (key, run["run_id"]),
                    )
                    if cur.fetchone() is None:
                        refuse = f"Group #{key} isn't a decided task of this run."
                        break
                    cur.execute(
                        """UPDATE reconciliation_exceptions SET status = 'OPEN', resolved_by = NULL, resolved_at = NULL, resolution_note = NULL
                           WHERE group_id = %s AND status IN %s""",
                        (key, RESOLVED),
                    )
                    cur.execute("DELETE FROM camunda_process_tracking WHERE record_type = %s AND source_table = %s AND record_key = %s",
                                (recon_groups_db.RECORD_TYPE, recon_groups_db.SOURCE_TABLE, str(key)))
                    cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE group_id = %s AND status IN ('PROPOSED', 'APPROVED') AND synced_at IS NULL", (key,))
                    recon_tasks_db._audit(cur, who["user_id"], "SENT_BACK_AT_SIGNOFF", "reconciliation_group", key, None, note.strip())
                    recon_tasks_db.mark_sent_back(cur, kind, key, who["user_id"], note, "RUN_SIGNOFF")
                else:
                    refuse = "Unknown task type."
                    break
        if refuse is not None:
            conn.rollback()
            return dict(signoffOk=False, signoffError=refuse)
        cur.execute("UPDATE reconciliation_runs SET status = 'OPEN', process_instance_key = NULL WHERE run_id = %s", (run["run_id"],))
        recon_tasks_db._audit(cur, who["user_id"], "RUN_SENT_BACK", "reconciliation_run", f"{run['source_system']}:{run['run_key']}",
                              "IN_SIGNOFF", f"{len(tasks)} task(s): {note.strip()}")
    conn.commit()
    return dict(signoffOk=True, signoffError="")
