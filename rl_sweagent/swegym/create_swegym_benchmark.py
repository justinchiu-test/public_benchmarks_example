"""Create SWE-Gym benchmarks using the swegym module."""

import argparse
import asyncio
import json
import os
from typing import Dict

import aiofiles
from datasets import load_dataset
from runloop_api_client import AsyncRunloop

from rl_sweagent.swegym.scenario_builder import create_swegym_scenario
from rl_sweagent.swegym.test_spec import make_test_spec


async def test_scenario_with_gold_patch(
    client: AsyncRunloop,
    scenario_id: str,
    instance_id: str = None,
    benchmark_name: str = "swegym",
) -> Dict:
    """Test that a scenario behaves correctly with the gold patch stored in reference_output."""

    # Track all command executions for debugging
    command_logs = []

    try:
        # Retrieve the scenario to get reference_output and metadata
        scenario = await client.scenarios.retrieve(scenario_id)

        # Start a scenario run
        scenario_run = await client.scenarios.start_run_and_await_env_ready(
            scenario_id=scenario_id
        )

        print(f"[{instance_id}] Testing gold patch on devbox: {scenario_run.devbox_id}")

        # Write patch to /home/user/ref.patch (like run_gold_patch.py)
        await client.devboxes.write_file_contents(
            id=scenario_run.devbox_id,
            file_path="/home/user/ref.patch",
            contents=scenario.reference_output or "",
        )

        # Verify patch file was written
        verify_result = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command="ls -la /home/user/ref.patch && wc -l /home/user/ref.patch",
        )

        # Log command execution
        command_logs.append(
            {
                "stage": "verify_patch_file",
                "command": "ls -la /home/user/ref.patch && wc -l /home/user/ref.patch",
                "exit_status": verify_result.exit_status,
                "stdout": verify_result.stdout if verify_result.stdout else "",
                "stderr": verify_result.stderr if verify_result.stderr else "",
            }
        )

        if verify_result.exit_status != 0:
            print(
                f"[{instance_id}] ERROR: Failed to verify patch file: {verify_result.exit_status}"
            )
            print(f"[{instance_id}] ERROR Stdout: {verify_result.stdout}")
            print(f"[{instance_id}] ERROR Stderr: {verify_result.stderr}")

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

        # Check current state before patching (add safe.directory for git operations)
        pre_patch_check = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command="git config --global --add safe.directory /testbed && cd /testbed && pwd && git status --short",
        )

        # Log command execution
        command_logs.append(
            {
                "stage": "pre_patch_check",
                "command": "git config --global --add safe.directory /testbed && cd /testbed && pwd && git status --short",
                "exit_status": pre_patch_check.exit_status,
                "stdout": pre_patch_check.stdout if pre_patch_check.stdout else "",
                "stderr": pre_patch_check.stderr if pre_patch_check.stderr else "",
            }
        )

        if pre_patch_check.exit_status != 0:
            print(
                f"[{instance_id}] ERROR: Pre-patch check failed: {pre_patch_check.exit_status}"
            )
            print(f"[{instance_id}] ERROR Stdout: {pre_patch_check.stdout}")
            print(f"[{instance_id}] ERROR Stderr: {pre_patch_check.stderr}")

        # Apply patch (like run_gold_patch.py)
        patch_result = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command=f"cd /testbed && patch {patch_apply_flags} < /home/user/ref.patch",
        )

        # Log command execution
        command_logs.append(
            {
                "stage": "apply_patch",
                "command": f"cd /testbed && patch {patch_apply_flags} < /home/user/ref.patch",
                "exit_status": patch_result.exit_status,
                "stdout": patch_result.stdout if patch_result.stdout else "",
                "stderr": patch_result.stderr if patch_result.stderr else "",
            }
        )

        patch_applied = patch_result.exit_status == 0

        # Print error details if patch application failed
        if not patch_applied:
            print(
                f"[{instance_id}] ERROR: Patch application failed with exit code: {patch_result.exit_status}"
            )
            print(f"[{instance_id}] ERROR Stdout: {patch_result.stdout}")
            print(f"[{instance_id}] ERROR Stderr: {patch_result.stderr}")
        else:
            # Check what changed after patch
            post_patch_check = await client.devboxes.execute_sync(
                id=scenario_run.devbox_id,
                command="cd /testbed && git diff --name-only",
            )

            # Log command execution
            command_logs.append(
                {
                    "stage": "post_patch_check",
                    "command": "cd /testbed && git diff --name-only",
                    "exit_status": post_patch_check.exit_status,
                    "stdout": post_patch_check.stdout
                    if post_patch_check.stdout
                    else "",
                    "stderr": post_patch_check.stderr
                    if post_patch_check.stderr
                    else "",
                }
            )

            if post_patch_check.exit_status != 0:
                print(
                    f"[{instance_id}] ERROR: Post-patch check failed: {post_patch_check.exit_status}"
                )
                print(f"[{instance_id}] ERROR Stdout: {post_patch_check.stdout}")
                print(f"[{instance_id}] ERROR Stderr: {post_patch_check.stderr}")

        # Score the scenario with the patch applied
        result = await client.scenarios.runs.score_and_await(id=scenario_run.id)

        # Get the score and output
        score = 0.0
        scoring_output = None
        if result.scoring_contract_result:
            score = result.scoring_contract_result.score
            # Get the scoring output directly from the result
            if result.scoring_contract_result.scoring_function_results:
                scoring_output = (
                    result.scoring_contract_result.scoring_function_results[0].output
                )
                print(f"[{instance_id}] Scoring output:")
                print("-" * 80)
                print(f"[{instance_id}] {scoring_output[:2000]}")  # First 2000 chars
                if len(scoring_output) > 2000:
                    print(
                        f"[{instance_id}] ... (truncated, total length: {len(scoring_output)} chars)"
                    )
                print("-" * 80)

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

        # Save command logs
        log_dir = os.path.join("logs", benchmark_name, instance_id)
        os.makedirs(log_dir, exist_ok=True)

        filename = os.path.join(log_dir, "gold_patch_test_logs.json")
        async with aiofiles.open(filename, mode="w") as f:
            await f.write(
                json.dumps(
                    {
                        "instance_id": instance_id,
                        "scenario_id": scenario_id,
                        "devbox_id": scenario_run.devbox_id,
                        "status": status,
                        "score": score,
                        "patch_applied": patch_applied,
                        "command_logs": command_logs,
                        "scoring_output": scoring_output if scoring_output else None,
                    },
                    indent=2,
                )
            )
        print(f"[{instance_id}] Gold patch test logs saved to {filename}")

        return {
            "status": status,
            "score": score,
            "patch_applied": patch_applied,
            "run_id": scenario_run.id,
            "devbox_id": scenario_run.devbox_id,
            "scoring_output": scoring_output[:1000]
            if scoring_output
            else None,  # Truncate for storage
        }

    except Exception as e:
        # Save command logs even on error
        if command_logs:
            log_dir = os.path.join("logs", benchmark_name, instance_id)
            os.makedirs(log_dir, exist_ok=True)

            filename = os.path.join(log_dir, "gold_patch_test_logs.json")
            async with aiofiles.open(filename, mode="w") as f:
                await f.write(
                    json.dumps(
                        {
                            "instance_id": instance_id,
                            "scenario_id": scenario_id,
                            "status": "error",
                            "error": str(e),
                            "command_logs": command_logs,
                        },
                        indent=2,
                    )
                )
            print(f"[{instance_id}] Gold patch test error logs saved to {filename}")

        return {"status": "error", "error": str(e)}


async def append_to_jsonl(
    record: dict, benchmark_name: str = "swegym", lock: asyncio.Lock = None
):
    """Append a single record to the JSONL file in a thread-safe manner."""
    # Create logs directory for the benchmark
    log_dir = os.path.join("logs", benchmark_name)
    os.makedirs(log_dir, exist_ok=True)

    output_file = os.path.join(log_dir, "scenarios.jsonl")

    async with lock if lock else asyncio.Lock():
        async with aiofiles.open(output_file, mode="a") as f:
            await f.write(json.dumps(record) + "\n")


async def process_instance(
    client: AsyncRunloop,
    instance: dict,
    instance_index: int,
    total_instances: int,
    test_gold_patch: bool,
    semaphore: asyncio.Semaphore,
    file_lock: asyncio.Lock,
    benchmark_name: str = "swegym",
):
    """Process a single instance to create a scenario."""
    async with semaphore:
        instance_id = instance.get("instance_id", f"unknown_{instance_index}")
        print(
            f"\n[{instance_id}] Creating scenario {instance_index + 1}/{total_instances}"
        )

        try:
            # Create test spec for this instance
            test_spec = make_test_spec(instance)

            # Create scenario with its own snapshot
            scenario = await create_swegym_scenario(
                client, instance, test_spec, benchmark_name
            )

            # Test gold patch if requested
            gold_patch_result = None
            if test_gold_patch and instance.get("patch"):
                print(f"[{instance_id}] Testing gold patch...")
                gold_patch_result = await test_scenario_with_gold_patch(
                    client, scenario.id, instance_id, benchmark_name
                )
                print(
                    f"[{instance_id}] Gold patch test result: {gold_patch_result['status']}"
                )

            # Write to JSONL file immediately after completion
            record = {
                "instance_id": instance_id,
                "scenario_id": scenario.id,
                "gold_patch_test_success": gold_patch_result.get("status") == "valid"
                if gold_patch_result
                else None,
                "gold_patch_test_status": gold_patch_result.get("status")
                if gold_patch_result
                else None,
                "gold_patch_test_score": gold_patch_result.get("score")
                if gold_patch_result
                else None,
                "repo": instance.get("repo", ""),
                "version": instance.get("version", ""),
            }
            await append_to_jsonl(record, benchmark_name, lock=file_lock)
            print(f"[{instance_id}] Saved to logs/{benchmark_name}/scenarios.jsonl")

            return {
                "instance_id": instance_id,
                "scenario_id": scenario.id,
                "repo": instance.get("repo", ""),
                "version": instance.get("version", ""),
                "status": "success",
                "gold_patch_test": gold_patch_result,
            }

        except Exception as e:
            print(f"[{instance_id}] ERROR: Failed to create scenario: {e}")

            # Also log failed scenarios
            failed_record = {
                "instance_id": instance_id,
                "scenario_id": None,
                "gold_patch_test_success": None,
                "gold_patch_test_status": "error",
                "gold_patch_test_score": None,
                "repo": instance.get("repo", ""),
                "version": instance.get("version", ""),
                "error": str(e),
            }
            await append_to_jsonl(failed_record, benchmark_name, lock=file_lock)

            return {
                "instance_id": instance_id,
                "repo": instance.get("repo", ""),
                "version": instance.get("version", ""),
                "error": str(e),
                "status": "failed",
            }


async def create_swegym_benchmark(
    client: AsyncRunloop,
    max_instances_per_repo: int,
    benchmark_name: str = "SWE-Gym Benchmark",
    start_from: int = 0,
    test_gold_patch: bool = False,
    max_concurrent: int = 5,
    max_repos: int = None,
):
    """Create SWE-Gym scenarios by sampling up to K instances from each repository.

    Args:
        client: AsyncRunloop client
        max_instances_per_repo: Maximum number of instances to sample from each repository
        benchmark_name: Name for the benchmark
        start_from: Starting index in the dataset
        test_gold_patch: Whether to test gold patches
        max_concurrent: Maximum concurrent operations
        max_repos: Maximum number of repositories to include (None for all)
    """

    if max_instances_per_repo == 0:
        print(
            f"[INFO] Creating benchmark '{benchmark_name}' with ALL instances from each repository..."
        )
    else:
        print(
            f"[INFO] Creating benchmark '{benchmark_name}' with up to {max_instances_per_repo} instances per repository..."
        )
    print(f"[INFO] Starting from instance index: {start_from}")
    print(f"[INFO] Max concurrent operations: {max_concurrent}")
    if max_repos:
        print(f"[INFO] Maximum repositories: {max_repos}")

    # Load SWE-Gym dataset
    print("[INFO] Loading SWE-Gym dataset...")
    dataset = load_dataset("SWE-Gym/SWE-Gym", split="train", streaming=True)

    # Sample K instances from each repository
    instances_by_repo = {}
    total_seen = 0
    instances_to_process = []
    repos_completed = 0

    for instance in dataset:
        # Skip instances before start_from
        if total_seen < start_from:
            total_seen += 1
            continue

        repo = instance.get("repo", "unknown")

        # Initialize repo counter if needed
        if repo not in instances_by_repo:
            instances_by_repo[repo] = []

        # Check if we've reached the max number of repos
        if max_repos and len(instances_by_repo) > max_repos:
            # Only continue processing if this is a repo we've already started
            if repo not in instances_by_repo or (
                max_instances_per_repo > 0
                and len(instances_by_repo[repo]) >= max_instances_per_repo
            ):
                total_seen += 1
                continue

        # Add instance if we haven't reached the limit for this repo (0 means no limit)
        if (
            max_instances_per_repo == 0
            or len(instances_by_repo[repo]) < max_instances_per_repo
        ):
            instances_by_repo[repo].append((instance, len(instances_to_process)))
            instances_to_process.append((instance, len(instances_to_process)))

            # Check if this repo is now complete (only if we have a limit)
            if (
                max_instances_per_repo > 0
                and len(instances_by_repo[repo]) == max_instances_per_repo
            ):
                repos_completed += 1

                # Stop if we've completed max_repos
                if max_repos and repos_completed >= max_repos:
                    break

        total_seen += 1

    # Print repository distribution
    print("\n[INFO] Repository distribution:")
    repo_counts = {}
    for repo, instances in instances_by_repo.items():
        repo_counts[repo] = len(instances)

    # Sort by count (descending) then by repo name
    sorted_repos = sorted(repo_counts.items(), key=lambda x: (-x[1], x[0]))

    for repo, count in sorted_repos[:20]:
        print(f"  {repo}: {count} instances")
    if len(repo_counts) > 20:
        print(f"  ... and {len(repo_counts) - 20} more repositories")

    print(f"\n[INFO] Total repositories: {len(repo_counts)}")
    print(f"[INFO] Total instances selected: {len(instances_to_process)}")

    # Show repos with fewer instances than requested (only if we had a limit)
    if max_instances_per_repo > 0:
        incomplete_repos = [
            (repo, count)
            for repo, count in repo_counts.items()
            if count < max_instances_per_repo
        ]
        if incomplete_repos:
            print(
                f"\n[WARNING] {len(incomplete_repos)} repositories had fewer than {max_instances_per_repo} instances:"
            )
            for repo, count in sorted(incomplete_repos[:10], key=lambda x: x[1]):
                print(f"  {repo}: {count} instances")
            if len(incomplete_repos) > 10:
                print(f"  ... and {len(incomplete_repos) - 10} more repositories")

    # Create semaphore for concurrency control
    semaphore = asyncio.Semaphore(max_concurrent)

    # Create file lock for thread-safe JSONL writing
    file_lock = asyncio.Lock()

    # Create tasks for all instances
    tasks = []
    total_instances = len(instances_to_process)
    for instance, index in instances_to_process:
        task = process_instance(
            client,
            instance,
            index,
            total_instances,
            test_gold_patch,
            semaphore,
            file_lock,
            benchmark_name,
        )
        tasks.append(task)

    # Process all tasks concurrently
    results = []

    if tasks:
        task_results = await asyncio.gather(*tasks)
        results.extend(task_results)

    # Extract scenario IDs from successful results
    scenario_ids = [r["scenario_id"] for r in results if r.get("status") == "success"]

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
            # current_scenarios = (
            #     existing_benchmark.scenario_ids
            #     if hasattr(existing_benchmark, "scenario_ids")
            #     else []
            # )
            # Combine with new scenarios (avoiding duplicates)
            # all_scenario_ids = list(set(current_scenarios + scenario_ids))

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


def get_scenario_status(output_dir: str = ".") -> dict:
    """Get status of all created scenarios from saved JSON files.

    Returns a dict keyed by instance_id with scenario details and gold patch results.
    """
    import glob

    scenarios = {}

    # Read individual scenario files
    for scenario_file in glob.glob(os.path.join(output_dir, "scenario_*.json")):
        with open(scenario_file, "r") as f:
            data = json.load(f)
            instance_id = data.get("instance_id")
            if instance_id:
                scenarios[instance_id] = {
                    "scenario_id": data.get("scenario_id"),
                    "snapshot_id": data.get("snapshot_id"),
                    "repo": data.get("repo"),
                    "version": data.get("version"),
                    "base_commit": data.get("base_commit"),
                    "file": scenario_file,
                    "gold_patch_test": None,  # Will be filled from benchmark results
                }

    # Read benchmark result files to get gold patch test results
    for benchmark_file in glob.glob(os.path.join(output_dir, "benchmark_*.json")):
        with open(benchmark_file, "r") as f:
            data = json.load(f)
            for result in data.get("results", []):
                instance_id = result.get("instance_id")
                if instance_id and instance_id in scenarios:
                    scenarios[instance_id]["gold_patch_test"] = result.get(
                        "gold_patch_test"
                    )
                elif instance_id:
                    # Scenario might exist in benchmark but not have individual file
                    scenarios[instance_id] = {
                        "scenario_id": result.get("scenario_id"),
                        "repo": result.get("repo"),
                        "version": result.get("version"),
                        "status": result.get("status"),
                        "gold_patch_test": result.get("gold_patch_test"),
                        "from_benchmark": benchmark_file,
                    }

    return scenarios


def save_scenario_summary(scenarios: dict, output_file: str = "swegym_scenarios.jsonl"):
    """Save scenario summary to a JSONL file."""
    with open(output_file, "w") as f:
        for instance_id, info in sorted(scenarios.items()):
            gold_test = info.get("gold_patch_test", {})
            record = {
                "instance_id": instance_id,
                "scenario_id": info.get("scenario_id"),
                "gold_patch_test_success": gold_test.get("status") == "valid"
                if gold_test
                else None,
                "gold_patch_test_status": gold_test.get("status")
                if gold_test
                else None,
                "gold_patch_test_score": gold_test.get("score") if gold_test else None,
                "repo": info.get("repo"),
                "version": info.get("version"),
            }
            f.write(json.dumps(record) + "\n")

    print(f"[INFO] Scenario summary saved to: {output_file}")


def print_scenario_summary(scenarios: dict):
    """Print a summary of scenarios and their gold patch test results."""
    if not scenarios:
        print("[INFO] No scenarios found.")
        return

    print(f"\n[SUMMARY] Found {len(scenarios)} scenarios:")
    print("-" * 80)

    # Group by repo
    by_repo = {}
    for instance_id, info in scenarios.items():
        repo = info.get("repo", "unknown")
        if repo not in by_repo:
            by_repo[repo] = []
        by_repo[repo].append((instance_id, info))

    # Print by repo
    for repo in sorted(by_repo.keys()):
        instances = by_repo[repo]
        print(f"\n{repo} ({len(instances)} instances):")

        for instance_id, info in sorted(instances):
            scenario_id = info.get("scenario_id", "N/A")
            gold_test = info.get("gold_patch_test")

            if gold_test:
                status = gold_test.get("status", "unknown")
                score = gold_test.get("score", 0)
                status_str = f"{status} (score: {score})"
            else:
                status_str = "not tested"

            print(f"  {instance_id}: {scenario_id} - Gold patch: {status_str}")

    # Summary statistics
    print("\n" + "-" * 80)
    total = len(scenarios)
    tested = len([s for s in scenarios.values() if s.get("gold_patch_test")])
    valid = len(
        [
            s
            for s in scenarios.values()
            if s.get("gold_patch_test")
            and s.get("gold_patch_test", {}).get("status") == "valid"
        ]
    )
    failed = len(
        [
            s
            for s in scenarios.values()
            if s.get("gold_patch_test")
            and s.get("gold_patch_test", {}).get("status") in ["failed", "patch_failed"]
        ]
    )

    print(f"Total scenarios: {total}")
    print(f"Gold patch tested: {tested}")
    if tested > 0:
        print(f"  Valid: {valid} ({valid/tested*100:.1f}%)")
        print(f"  Failed: {failed} ({failed/tested*100:.1f}%)")


async def main():
    """Main entry point for creating SWE-Gym benchmarks."""

    # Create argument parser
    parser = argparse.ArgumentParser(
        description="Create SWE-Gym benchmarks with multiple scenarios",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(
        dest="command", help="Command to run", required=True
    )

    # Create command
    create_parser = subparsers.add_parser(
        "create", help="Create new scenarios and benchmark"
    )
    create_parser.add_argument(
        "max_instances_per_repo",
        type=int,
        help="Maximum number of instances to sample from each repository (0 for all)",
    )
    create_parser.add_argument(
        "--name",
        type=str,
        default="swegym",
        help="Base name for the benchmark (will append -{repos}-{instances})",
    )
    create_parser.add_argument(
        "--start-from",
        type=int,
        default=0,
        help="Start from a specific index in the dataset",
    )
    create_parser.add_argument(
        "--test-gold-patch",
        action="store_true",
        help="Test that gold patches work correctly by applying and scoring them",
    )
    create_parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum number of concurrent operations",
    )
    create_parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Maximum number of repositories to include (default: all repositories)",
    )

    # Status command
    status_parser = subparsers.add_parser(
        "status", help="Show status of created scenarios"
    )
    status_parser.add_argument(
        "--dir",
        type=str,
        default=".",
        help="Directory to search for scenario and benchmark files",
    )

    # Parse arguments
    args = parser.parse_args()

    # Handle status command
    if args.command == "status":
        scenarios = get_scenario_status(args.dir)
        print_scenario_summary(scenarios)
        return

    # Handle create command
    if args.command == "create":
        # Validate arguments
        if args.max_instances_per_repo < 0:
            parser.error(
                "Max instances per repository must be non-negative (0 for all)"
            )

        if args.max_concurrent <= 0:
            parser.error("Max concurrent must be greater than 0")

        if args.start_from < 0:
            parser.error("Start from index must be non-negative")

        if args.max_repos is not None and args.max_repos <= 0:
            parser.error("Max repos must be greater than 0")

        # Append repo and instance info to the name
        repos_str = f"{args.max_repos}repos" if args.max_repos else "allrepos"
        instances_str = (
            "allinstances"
            if args.max_instances_per_repo == 0
            else f"{args.max_instances_per_repo}instances"
        )
        full_name = f"{args.name}-{repos_str}-{instances_str}"
        args.name = full_name
        print(f"[INFO] Full benchmark name: {args.name}")

    if args.max_instances_per_repo == 0:
        print("[INFO] Will create scenarios with ALL instances from each repository")
    else:
        print(
            f"[INFO] Will create scenarios with up to {args.max_instances_per_repo} instances per repository"
        )
    if args.max_repos:
        print(f"[INFO] Limiting to {args.max_repos} repositories")
    if args.start_from > 0:
        print(f"[INFO] Starting from index {args.start_from}")

    # Check for API key
    api_key = os.getenv("RUNLOOP_API_KEY")
    if not api_key:
        parser.error("RUNLOOP_API_KEY environment variable not set")

    # Create client
    client = AsyncRunloop(bearer_token=api_key)

    try:
        # Create benchmark
        benchmark, results = await create_swegym_benchmark(
            client,
            args.max_instances_per_repo,
            args.name,
            args.start_from,
            args.test_gold_patch,
            args.max_concurrent,
            args.max_repos,
        )

        # Save results
        output = {
            "benchmark_id": benchmark.id if benchmark else None,
            "benchmark_name": args.name,
            "max_instances_per_repo": args.max_instances_per_repo,
            "max_repos": args.max_repos,
            "start_from": args.start_from,
            "successful_scenarios": len(
                [r for r in results if r.get("status") == "success"]
            ),
            "failed_scenarios": len(
                [r for r in results if r.get("status") == "failed"]
            ),
            "total_instances": len(results),
            "results": results,
        }

        # Save to logs directory
        log_dir = os.path.join("logs", args.name)
        os.makedirs(log_dir, exist_ok=True)

        output_file = os.path.join(
            log_dir, f"benchmark_{benchmark.id if benchmark else 'failed'}.json"
        )
        with open(output_file, "w") as f:
            json.dump(output, f, indent=2)

        print("\n[SUCCESS] Benchmark creation completed!")
        print(f"Results saved to: {output_file}")
        if benchmark:
            print(f"Benchmark ID: {benchmark.id}")
            print(
                f"Successfully created {len([r for r in results if r.get('status') == 'success'])}/{len(results)} scenarios"
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
        if args.test_gold_patch:
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

        # Show detailed scenario summary
        print("\n" + "=" * 80)
        print("DETAILED SCENARIO STATUS")
        print("=" * 80)
        scenarios = get_scenario_status(".")
        print_scenario_summary(scenarios)

    except Exception as e:
        print(f"\n[ERROR] Failed to create benchmark: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
