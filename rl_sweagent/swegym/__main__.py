"""Main entry point for SWE-Gym to Runloop conversion."""

import argparse
import asyncio
import os

from runloop_api_client import AsyncRunloop

from rl_sweagent.swegym.scenario_builder import create_swegym_scenario


async def main():
    parser = argparse.ArgumentParser(
        description="Create Runloop scenarios from SWE-Gym instances"
    )
    parser.add_argument(
        "--instance-id",
        required=True,
        help="SWE-Gym instance ID (e.g., getmoto__moto-7365)",
    )
    parser.add_argument(
        "--snapshot-id", help="Use existing snapshot instead of creating new devbox"
    )

    args = parser.parse_args()

    # Check for API key
    api_key = os.getenv("RUNLOOP_API_KEY")
    if not api_key:
        print("[ERROR] RUNLOOP_API_KEY environment variable not set")
        return

    client = AsyncRunloop(bearer_token=api_key)

    try:
        scenario = await create_swegym_scenario(
            client, args.instance_id, args.snapshot_id
        )

        print(f"\n[SUCCESS] Created scenario: {scenario.id}")
        print("You can now run agents on this scenario using the scenario ID")

    except Exception as e:
        print(f"\n[ERROR] Failed to create scenario: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
