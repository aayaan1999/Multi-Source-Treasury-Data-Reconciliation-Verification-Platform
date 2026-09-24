"""Starts one transaction-review instance with hand-picked variables, for manually verifying the
gateway routes to the correct candidate group (specs/camunda-bpmn-process-design.md section 6's
first three acceptance-criteria checkboxes). Does NOT touch Postgres or camunda_process_tracking
- use camunda/bridge/poll_worker.py for the real Postgres-driven path.

    python camunda/bridge/test_instance.py FRAUD
    python camunda/bridge/test_instance.py COMPLIANCE
    python camunda/bridge/test_instance.py OPERATIONS

Then check Tasklist (http://localhost:8082) for a task in the matching candidate group
(fraud-investigation / compliance / operations).
"""
import asyncio
import sys

from pyzeebe import ZeebeClient, create_insecure_channel

from _env import zeebe_address

SAMPLE_VARS = {
    "FRAUD": {
        "recordType": "fraud", "sourceTable": "transactions", "recordKey": "TEST-TXN-001",
        "flagLabel": "STRUCTURING_PATTERN", "flagType": "SUSPICIOUS", "flagCategory": "FRAUD",
        "description": "Manual test instance - suspicious structuring flag",
    },
    "COMPLIANCE": {
        "recordType": "data_quality", "sourceTable": "capital_positions", "recordKey": "TEST-CAP-001",
        "flagLabel": "MISSING_RISK_RATING", "flagType": "FAULT", "flagCategory": "COMPLIANCE",
        "description": "Manual test instance - capital_positions data-quality flag",
    },
    "OPERATIONS": {
        "recordType": "data_quality", "sourceTable": "customers", "recordKey": "TEST-CUST-001",
        "flagLabel": "ORPHAN_CUSTOMER", "flagType": "FAULT", "flagCategory": "OPERATIONS",
        "description": "Manual test instance - customers data-quality flag",
    },
}


async def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in SAMPLE_VARS:
        sys.exit(f"Usage: python {sys.argv[0]} {{{'|'.join(SAMPLE_VARS)}}}")
    channel = create_insecure_channel(grpc_address=zeebe_address())
    client = ZeebeClient(channel)
    result = await client.run_process(bpmn_process_id="transaction-review", variables=SAMPLE_VARS[sys.argv[1]])
    print(f"Started instance {result.process_instance_key} with flagCategory={sys.argv[1]}")


if __name__ == "__main__":
    asyncio.run(main())
