"""Create SWE-Gym benchmarks using the swegym module."""

from runloop_api_client import AsyncRunloop
import os
import asyncio
import sys
import json
from typing import Dict
from datasets import load_dataset
from rl_sweagent.swegym.scenario_builder import create_swegym_scenario


async def test_scenario_with_gold_patch(client: AsyncRunloop, scenario_id: str) -> Dict:
    """Test that a scenario behaves correctly with the gold patch stored in reference_output."""

    try:
        # Retrieve the scenario to get reference_output and metadata
        scenario = await client.scenarios.retrieve(scenario_id)

        # Start a scenario run
        scenario_run = await client.scenarios.start_run_and_await_env_ready(
            scenario_id=scenario_id
        )

        # Write patch to /home/user/ref.patch (like run_gold_patch.py)
        await client.devboxes.write_file_contents(
            id=scenario_run.devbox_id,
            file_path="/home/user/ref.patch",
            contents=scenario.reference_output or "",
        )

        # Determine patch direction (reverse or normal)
        if (
            scenario.metadata
            and scenario.metadata.get("reference_patch_direction")
            and scenario.metadata.get("reference_patch_direction", "").lower()
            == "reverse"
        ):
            patch_apply_flags = "-p1 -R"
        else:
            patch_apply_flags = "-p1"

        # Apply patch (like run_gold_patch.py)
        patch_result = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command=f"cd /testbed && patch {patch_apply_flags} < /home/user/ref.patch",
        )

        patch_applied = patch_result.exit_status == 0

        # Score the scenario with the patch applied
        result = await client.scenarios.runs.score_and_await(id=scenario_run.id)

        # Get the score
        score = 0.0
        if result.scoring_contract_result:
            score = result.scoring_contract_result.score

        # Complete the run to clean up
        await client.scenarios.runs.complete(id=scenario_run.id)

        # Determine status based on score
        if not patch_applied:
            status = "patch_failed"
        elif score >= 1.0:
            status = "valid"  # Gold patch works correctly
        elif score > 0:
            status = "partial"  # Some tests passed
        else:
            status = "failed"  # Gold patch didn't work

        return {
            "status": status,
            "score": score,
            "patch_applied": patch_applied,
            "run_id": scenario_run.id,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


async def create_swegym_benchmark(
    client: AsyncRunloop,
    num_instances: int,
    benchmark_name: str = "SWE-Gym Benchmark",
    reuse_snapshot: bool = False,
    start_from: int = 0,
    test_gold_patch: bool = False,
):
    """Create multiple SWE-Gym scenarios and a benchmark."""

    print(
        f"[INFO] Creating benchmark '{benchmark_name}' with {num_instances} scenarios..."
    )
    print(f"[INFO] Starting from instance index: {start_from}")

    # Load SWE-Gym dataset
    print("[INFO] Loading SWE-Gym dataset...")
    dataset = load_dataset("SWE-Gym/SWE-Gym", split="train", streaming=True)

    scenario_ids = []
    snapshot_id = None
    results = []
    instance_count = 0
    total_seen = 0

    # Iterate through dataset
    for instance in dataset:
        # Skip instances before start_from
        if total_seen < start_from:
            total_seen += 1
            continue

        # Stop when we have enough instances
        if instance_count >= num_instances:
            break

        instance_id = instance.get("instance_id", f"unknown_{instance_count}")
        print(
            f"\n[INFO] Creating scenario {instance_count + 1}/{num_instances}: {instance_id}"
        )

        try:
            # Reuse snapshot if requested and available
            use_snapshot = snapshot_id if reuse_snapshot and snapshot_id else None

            scenario = await create_swegym_scenario(
                client, instance_id, use_snapshot=use_snapshot
            )

            scenario_ids.append(scenario.id)

            # Save the snapshot ID for reuse if this is the first scenario
            if reuse_snapshot and not snapshot_id:
                # Read the saved scenario details to get snapshot ID
                with open(f"scenario_{instance_id}.json", "r") as f:
                    details = json.load(f)
                    snapshot_id = details.get("snapshot_id")
                    print(
                        f"[INFO] Will reuse snapshot {snapshot_id} for remaining scenarios"
                    )

            # Test gold patch if requested
            gold_patch_result = None
            if test_gold_patch and instance.get("patch"):
                print(f"[INFO] Testing gold patch for {instance_id}...")
                gold_patch_result = await test_scenario_with_gold_patch(
                    client, scenario.id
                )
                print(f"[INFO] Gold patch test result: {gold_patch_result['status']}")

            results.append(
                {
                    "instance_id": instance_id,
                    "scenario_id": scenario.id,
                    "repo": instance.get("repo", ""),
                    "version": instance.get("version", ""),
                    "status": "success",
                    "gold_patch_test": gold_patch_result,
                }
            )

        except Exception as e:
            print(f"[ERROR] Failed to create scenario for {instance_id}: {e}")
            results.append(
                {
                    "instance_id": instance_id,
                    "repo": instance.get("repo", ""),
                    "version": instance.get("version", ""),
                    "error": str(e),
                    "status": "failed",
                }
            )

        instance_count += 1
        total_seen += 1

    if not scenario_ids:
        print("[ERROR] No scenarios created successfully. Cannot create benchmark.")
        return None, results

    # Create or update benchmark
    print(
        f"\n[INFO] Creating/updating benchmark '{benchmark_name}' with {len(scenario_ids)} scenarios..."
    )

    # Try to find existing benchmark with this name
    existing_benchmark = None
    try:
        benchmarks_response = await client.benchmarks.list()
        # The response might have a .benchmarks attribute or be a list directly
        benchmarks = (
            benchmarks_response.benchmarks
            if hasattr(benchmarks_response, "benchmarks")
            else benchmarks_response
        )
        for b in benchmarks:
            if b.name == benchmark_name:
                existing_benchmark = b
                print(f"[INFO] Found existing benchmark with ID: {b.id}")
                break
    except Exception as e:
        print(f"[WARNING] Could not list benchmarks: {e}")

    if existing_benchmark:
        # Update existing benchmark by adding new scenarios
        try:
            # Get current scenario IDs
            current_scenarios = (
                existing_benchmark.scenario_ids
                if hasattr(existing_benchmark, "scenario_ids")
                else []
            )
            # Combine with new scenarios (avoiding duplicates)
            all_scenario_ids = list(set(current_scenarios + scenario_ids))

            # Note: The API might not support updating benchmarks directly
            # In that case, we'll just note the existing benchmark
            print(
                f"[INFO] Benchmark '{benchmark_name}' already exists with ID: {existing_benchmark.id}"
            )
            print(f"[INFO] New scenarios created: {', '.join(scenario_ids)}")
            benchmark = existing_benchmark
        except Exception as e:
            print(f"[WARNING] Could not update benchmark: {e}")
            benchmark = existing_benchmark
    else:
        # Create new benchmark
        try:
            benchmark = await client.benchmarks.create(
                name=benchmark_name, scenario_ids=scenario_ids
            )
            print(f"[INFO] Benchmark created with ID: {benchmark.id}")
        except Exception as e:
            print(f"[ERROR] Could not create benchmark '{benchmark_name}': {e}")
            benchmark = None

    return benchmark, results


async def main():
    """Main entry point for creating SWE-Gym benchmarks."""

    # Parse arguments
    if len(sys.argv) < 2:
        print("[ERROR] Please provide the number of instances to create")
        print("Usage:")
        print("  python create_swegym_benchmark.py <num_instances>")
        print("Options:")
        print("  --name <name>: Benchmark name (default: 'SWE-Gym Benchmark')")
        print("  --reuse-snapshot: Reuse first snapshot for all scenarios")
        print(
            "  --start-from <index>: Start from a specific index in the dataset (default: 0)"
        )
        print("  --test-gold-patch: Test that gold patches work correctly")
        return

    # Parse command line arguments
    num_instances = 0
    benchmark_name = "SWE-Gym Benchmark"
    reuse_snapshot = False
    start_from = 0
    test_gold_patch = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--name":
            i += 1
            if i < len(sys.argv):
                benchmark_name = sys.argv[i]
        elif arg == "--reuse-snapshot":
            reuse_snapshot = True
        elif arg == "--test-gold-patch":
            test_gold_patch = True
        elif arg == "--start-from":
            i += 1
            if i < len(sys.argv):
                start_from = int(sys.argv[i])
        elif not arg.startswith("--"):
            try:
                num_instances = int(arg)
            except ValueError:
                print(f"[ERROR] Invalid number of instances: {arg}")
                return
        i += 1

    if num_instances <= 0:
        print("[ERROR] Number of instances must be greater than 0")
        return

    print(
        f"[INFO] Will create scenarios for {num_instances} instances from the SWE-Gym dataset"
    )
    if start_from > 0:
        print(f"[INFO] Starting from index {start_from}")

    # Check for API key
    api_key = os.getenv("RUNLOOP_API_KEY")
    if not api_key:
        print("[ERROR] RUNLOOP_API_KEY environment variable not set")
        return

    # Create client
    client = AsyncRunloop(bearer_token=api_key)

    try:
        # Create benchmark
        benchmark, results = await create_swegym_benchmark(
            client,
            num_instances,
            benchmark_name,
            reuse_snapshot,
            start_from,
            test_gold_patch,
        )

        # Save results
        output = {
            "benchmark_id": benchmark.id if benchmark else None,
            "benchmark_name": benchmark_name,
            "requested_instances": num_instances,
            "start_from": start_from,
            "successful_scenarios": len(
                [r for r in results if r.get("status") == "success"]
            ),
            "failed_scenarios": len(
                [r for r in results if r.get("status") == "failed"]
            ),
            "results": results,
        }

        output_file = f"benchmark_{benchmark.id if benchmark else 'failed'}.json"
        with open(output_file, "w") as f:
            json.dump(output, f, indent=2)

        print("\n[SUCCESS] Benchmark creation completed!")
        print(f"Results saved to: {output_file}")
        if benchmark:
            print(f"Benchmark ID: {benchmark.id}")
            print(
                f"Successfully created {len([r for r in results if r.get('status') == 'success'])}/{num_instances} scenarios"
            )

        # Print summary by repo
        repo_counts = {}
        for r in results:
            if r.get("status") == "success":
                repo = r.get("repo", "unknown")
                repo_counts[repo] = repo_counts.get(repo, 0) + 1

        if repo_counts:
            print("\nScenarios by repository:")
            for repo, count in sorted(repo_counts.items()):
                print(f"  {repo}: {count}")

        # Print gold patch test results if applicable
        if test_gold_patch:
            print("\nGold patch test results:")
            test_statuses = {}
            for r in results:
                if r.get("gold_patch_test"):
                    status = r["gold_patch_test"]["status"]
                    test_statuses[status] = test_statuses.get(status, 0) + 1

            for status, count in sorted(test_statuses.items()):
                print(f"  {status}: {count}")

            # Show scores for valid runs
            valid_runs = [
                r
                for r in results
                if r.get("gold_patch_test", {}).get("status") == "valid"
            ]
            if valid_runs:
                print(f"\n[INFO] {len(valid_runs)} gold patches validated successfully")

            # Warn about failed scenarios
            failed_count = test_statuses.get("failed", 0) + test_statuses.get(
                "error", 0
            )
            if failed_count > 0:
                print(f"\n[WARNING] {failed_count} gold patches failed validation!")

    except Exception as e:
        print(f"\n[ERROR] Failed to create benchmark: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
