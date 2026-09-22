"""Write-back service task worker for the `write-review-outcome` job type
(specs/camunda-bpmn-process-design.md section 3's "Service Task: Write outcome back to Postgres").

Runs as a long-lived Zeebe job worker: subscribes to `write-review-outcome` jobs, which Zeebe
creates when a reviewer completes one of the three user tasks (Fraud Investigation / Compliance
Review / Operations Review) via Tasklist with the review-outcome-form's `outcome`,
`correctedValue` and `reviewedByUserId` fields.

    python camunda/bridge/outcome_worker.py

Writes one row to review_outcomes (specs/bidirectional-sync.md's Direction 2 - Databricks reads
this back over JDBC on Notebook 3's next run). For fraud records, also updates
flagged_transactions.status so the record stops showing as PENDING_REVIEW immediately in the
application layer, without waiting for the next Databricks sync - CLAUDE.md's Databricks/Postgres
split has flagged_transactions.status as the one notebook output the app layer, not Databricks,
owns.
"""
import asyncio
import json

import _env  # sets the Windows event-loop policy - must be imported before pyzeebe/grpc.aio, see _env.py
import psycopg2
from pyzeebe import ZeebeWorker, Job, create_insecure_channel

from _env import database_url, zeebe_address


async def write_review_outcome(job: Job) -> dict:
    v = job.variables
    corrected_value = v.get("correctedValue") or None
    if corrected_value:
        try:
            corrected_value = json.dumps(json.loads(corrected_value))
        except (TypeError, ValueError):
            # Reviewer typed a non-JSON string; store it as a JSON string rather than fail the
            # job - specs/camunda-bpmn-process-design.md Open Item 3 flags corrected-value
            # validation as unresolved for the POC.
            corrected_value = json.dumps(corrected_value)

    conn = psycopg2.connect(database_url(), connect_timeout=45)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO review_outcomes
                   (record_type, source_table, record_key, outcome, corrected_value, reviewed_by)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (v["recordType"], v["sourceTable"], v["recordKey"], v["outcome"],
                 corrected_value, v["reviewedByUserId"]),
            )
            if v["recordType"] == "fraud":
                cur.execute(
                    """UPDATE flagged_transactions SET status = %s
                       WHERE transaction_id = %s AND flag_label = %s""",
                    (v["outcome"], v["recordKey"], v["flagLabel"]),
                )
        conn.commit()
    finally:
        conn.close()

    return {}


async def main() -> None:
    # Built inside main(), not at module scope: a grpc.aio channel created before asyncio.run()
    # starts its loop binds to a throwaway loop instance, distinct from the one main() actually
    # runs in - causes "Task ... got Future ... attached to a different loop" the moment a
    # streaming call (ActivateJobs, used by worker.work()) runs (confirmed live 2026-09-22).
    channel = create_insecure_channel(grpc_address=zeebe_address())
    worker = ZeebeWorker(channel)
    worker.task(task_type="write-review-outcome")(write_review_outcome)
    print(f"write-review-outcome worker listening on {zeebe_address()}...")
    await worker.work()


if __name__ == "__main__":
    asyncio.run(main())
