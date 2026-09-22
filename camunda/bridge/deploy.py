"""Deploys the transaction-review BPMN process and its form to the local Zeebe gateway.

    python camunda/bridge/deploy.py

Run this once after `docker compose up -d` in camunda/ (give Zeebe a minute to become healthy
first - `docker compose ps` in that folder shows readiness), and again any time
camunda/process/*.bpmn or *.form changes.
"""
import asyncio

from pyzeebe import ZeebeClient, create_insecure_channel

from _env import zeebe_address

PROCESS_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "process"


async def main() -> None:
    channel = create_insecure_channel(grpc_address=zeebe_address())
    client = ZeebeClient(channel)
    result = await client.deploy_resource(
        str(PROCESS_DIR / "review-outcome-form.form"),  # deploy the form first so the BPMN's formId resolves
        str(PROCESS_DIR / "transaction-review.bpmn"),
    )
    print(f"Deployed key {result.key}:")
    for resource in result.deployments:
        if hasattr(resource, "bpmn_process_id"):
            print(f"  process {resource.bpmn_process_id} v{resource.version} (key {resource.process_definition_key})")
        elif hasattr(resource, "form_id"):
            print(f"  form {resource.form_id} v{resource.version} (key {resource.form_key})")


if __name__ == "__main__":
    asyncio.run(main())
