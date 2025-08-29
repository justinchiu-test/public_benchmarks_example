"""Create SWE-Gym benchmarks using the swegym module."""

import argparse
import asyncio
import json
import os
from typing import Dict, Optional

import aiofiles
from datasets import load_dataset
from runloop_api_client import AsyncRunloop
from runloop_api_client.lib.polling import PollingConfig
from runloop_api_client.types import BenchmarkView

from rl_sweagent.swe_rebench.grading import get_report_from_devbox
from rl_sweagent.swe_rebench.test_spec import TestSpec, make_test_spec


async def test_scenario_with_gold_patch(
    client: AsyncRunloop,
    scenario_id: str,
    test_spec: TestSpec,
    benchmark_name: str = "swegym",
    debug: bool = False,
) -> Dict:
    """Test that a scenario behaves correctly with the gold patch stored in reference_output."""

    instance_id = test_spec.instance_id

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

        # Fix permissions on /testbed before applying patch
        print(f"[{instance_id}] Fixing file permissions before patch application...")
        perm_fix_result = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command="sudo chmod -R 755 /testbed && sudo chown -R $(whoami):$(whoami) /testbed && sudo chmod -R u+w /testbed",
            timeout=300,
        )

        # Log permission fix
        command_logs.append(
            {
                "stage": "fix_permissions_before_patch",
                "command": "sudo chmod -R 755 /testbed && sudo chown -R $(whoami):$(whoami) /testbed && sudo chmod -R u+w /testbed",
                "exit_status": perm_fix_result.exit_status,
                "stdout": perm_fix_result.stdout if perm_fix_result.stdout else "",
                "stderr": perm_fix_result.stderr if perm_fix_result.stderr else "",
            }
        )

        if perm_fix_result.exit_status != 0:
            print(
                f"[{instance_id}] WARNING: Failed to fix permissions: {perm_fix_result.stderr}"
            )
        else:
            print(f"[{instance_id}] Permissions fixed successfully")

        # Apply patch (like run_gold_patch.py)
        # Also ensure /tmp is writable for patch temporary files
        patch_result = await client.devboxes.execute_sync(
            id=scenario_run.devbox_id,
            command=f"sudo chmod 1777 /tmp && cd /testbed && patch {patch_apply_flags} < /home/user/ref.patch",
        )

        # Log command execution
        command_logs.append(
            {
                "stage": "apply_patch",
                "command": f"sudo chmod 1777 /tmp && cd /testbed && patch {patch_apply_flags} < /home/user/ref.patch",
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
        # the scenario is a dummy, just always passes to set up the environment.
        await client.scenarios.runs.score_and_await(
            id=scenario_run.id,
            polling_config=PollingConfig(
                interval_seconds=10,
                timeout_seconds=1200,
            ),
        )

        log_dir = os.path.join("logs", benchmark_name, instance_id)
        os.makedirs(log_dir, exist_ok=True)
        report = await get_report_from_devbox(
            client, scenario_run.devbox_id, test_spec, log_dir
        )

        is_resolved = report[instance_id]["resolved"]

        # Save report to JSON file
        report_file = os.path.join(log_dir, "report.json")
        async with aiofiles.open(report_file, mode="w") as f:
            await f.write(json.dumps(report, indent=2))
        print(f"[{instance_id}] Evaluation report saved to {report_file}")

        # print(f"[{instance_id}] Evaluation report: {report}")
        print(f"[{instance_id}] Evaluation report resolved: {is_resolved}")

        # Get the score and output
        score = 1.0 if is_resolved else 0.0

        # END EVAL CODE

        # Complete the run to clean up
        if not debug:
            await client.scenarios.runs.complete(id=scenario_run.id)

        # Determine status based on score
        if not patch_applied:
            status = "patch_failed"
        elif score >= 1.0:
            status = "resolved"  # Gold patch works correctly
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
        }

    except Exception as e:
        print(e)
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


async def create_or_update_benchmark(
    client: AsyncRunloop,
    benchmark_name: str,
    scenario_ids: list[str],
) -> Optional[BenchmarkView]:
    """Create or update a benchmark with the given scenario IDs.

    Args:
        client: AsyncRunloop client
        benchmark_name: Name for the benchmark
        scenario_ids: List of scenario IDs to include in the benchmark

    Returns:
        The created or updated benchmark object, or None if failed
    """
    if not scenario_ids:
        print("[ERROR] No scenarios provided. Cannot create benchmark.")
        return None

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
            print(
                f"[INFO] Benchmark '{benchmark_name}' already exists with ID: {existing_benchmark.id}"
            )
            print(f"[INFO] New scenarios created: {', '.join(scenario_ids)}")
            benchmark = await client.benchmarks.update(
                id=existing_benchmark.id, name=benchmark_name, scenario_ids=scenario_ids
            )

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

    return benchmark


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
    debug: bool = False,
    overwrite_blueprint: bool = False,
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
                client=client,
                instance=instance,
                test_spec=test_spec,
                overwrite_blueprint=overwrite_blueprint,
                benchmark_name=benchmark_name,
            )

            # Test gold patch if requested
            gold_patch_result = None
            if test_gold_patch and instance.get("patch"):
                print(f"[{instance_id}] Testing gold patch...")
                gold_patch_result = await test_scenario_with_gold_patch(
                    client,
                    scenario.id,
                    test_spec,
                    benchmark_name,
                    debug=debug,
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
                "devbox_id": getattr(e, "devbox_id", None) if debug else None,
            }
            await append_to_jsonl(failed_record, benchmark_name, lock=file_lock)

            return {
                "instance_id": instance_id,
                "repo": instance.get("repo", ""),
                "version": instance.get("version", ""),
                "error": str(e),
                "status": "failed",
                "devbox_id": getattr(e, "devbox_id", None) if debug else None,
            }


async def create_benchmark(
    client: AsyncRunloop,
    max_instances_per_repo: int,
    benchmark_name: str = "swe-rebench",
    start_from: int = 0,
    test_gold_patch: bool = False,
    max_concurrent: int = 5,
    max_repos: int = None,
    repo_filter: str = None,
    debug: bool = False,
    instance_ids: list = None,
    overwrite_blueprint: bool = False,
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
        repo_filter: If specified, only process instances from this repository
        debug: If True, keeps failed devboxes running for debugging
        overwrite_blueprint: If True, force recreation of blueprints
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
    if repo_filter:
        print(f"[INFO] Filtering to repository: {repo_filter}")
    elif max_repos:
        print(f"[INFO] Maximum repositories: {max_repos}")
    if debug:
        print("[INFO] DEBUG MODE ENABLED - Failed devboxes will be kept running")

    # Load SWE-Gym dataset
    print("[INFO] Loading swe-rebench dataset...")
    dataset = load_dataset("nebius/SWE-rebench", split="train", streaming=True)

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
        instance_id = instance.get("instance_id", "")

        # Skip if --repo filter is specified and this isn't the target repo
        if repo_filter and repo != repo_filter:
            total_seen += 1
            continue

        # Skip if --instance-ids filter is specified and this isn't one of the target instances
        if instance_ids and instance_id not in instance_ids:
            total_seen += 1
            continue

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
            debug,
            overwrite_blueprint,
        )
        tasks.append(task)

    # Process all tasks concurrently
    results = []

    if tasks:
        task_results = await asyncio.gather(*tasks)
        results.extend(task_results)

    # Extract scenario IDs from successful results
    scenario_ids = [r["scenario_id"] for r in results if r.get("status") == "success"]

    benchmark = await create_or_update_benchmark(client, benchmark_name, scenario_ids)

    return benchmark, results


def get_scenario_status(output_dir: str = ".") -> dict:
    """Get status of all created scenarios from saved JSON files.

    Returns a dict keyed by instance_id with scenario details and gold patch results.
    """
    import glob

    scenarios = {}

    # First try to read from scenarios.jsonl files in log directories
    for jsonl_file in glob.glob(os.path.join(output_dir, "logs/*/scenarios.jsonl")):
        with open(jsonl_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    instance_id = data.get("instance_id")
                    if instance_id:
                        scenarios[instance_id] = {
                            "scenario_id": data.get("scenario_id"),
                            "repo": data.get("repo"),
                            "version": data.get("version"),
                            "gold_patch_test": {
                                "status": data.get("gold_patch_test_status"),
                                "score": data.get("gold_patch_test_score"),
                            }
                            if data.get("gold_patch_test_status")
                            else None,
                            "error": data.get("error"),
                        }

    # Fall back to individual scenario files if no JSONL found
    if not scenarios:
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
            error = info.get("error")

            if error:
                status_str = (
                    f"ERROR: {error[:50]}..."
                    if len(str(error)) > 50
                    else f"ERROR: {error}"
                )
            elif gold_test:
                status = gold_test.get("status", "unknown")
                score = gold_test.get("score", 0)
                if status == "valid":
                    status_str = f"✅ {status} (score: {score})"
                else:
                    status_str = f"❌ {status} (score: {score})"
            else:
                status_str = "not tested"

            print(f"  {instance_id}: {scenario_id} - Gold patch: {status_str}")

    # Summary statistics
    print("\n" + "-" * 80)
    total = len(scenarios)
    errors = len([s for s in scenarios.values() if s.get("error")])
    created = len(
        [s for s in scenarios.values() if s.get("scenario_id") and not s.get("error")]
    )
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
            and s.get("gold_patch_test", {}).get("status")
            in ["failed", "patch_failed", "error"]
        ]
    )

    print(f"Total instances: {total}")
    if errors > 0:
        print(f"Failed to create scenario: {errors} ({errors/total*100:.1f}%)")
    print(f"Scenarios created: {created} ({created/total*100:.1f}%)")
    print(f"Gold patch tested: {tested}")
    if tested > 0:
        print(f"  Valid: {valid} ({valid/tested*100:.1f}%)")
        print(f"  Failed: {failed} ({failed/tested*100:.1f}%)")

    # Show success rate
    if total > 0:
        overall_success = valid / total * 100
        print(f"\nOverall success rate: {valid}/{total} ({overall_success:.1f}%)")


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
    create_parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Only process instances from this specific repository (e.g., 'django/django')",
    )
    create_parser.add_argument(
        "--debug",
        action="store_true",
        help="Keep devboxes running on failure for debugging (does not clean up failed devboxes)",
    )
    create_parser.add_argument(
        "--instance-ids",
        type=str,
        default=None,
        help="Comma-separated list of specific instance IDs to run (e.g., 'iterative__dvc-3472,iterative__dvc-3493')",
    )
    create_parser.add_argument(
        "--overwrite-blueprint",
        action="store_true",
        help="Force recreation of blueprints even if they already exist (default: reuse existing blueprints)",
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
        if args.repo:
            # If filtering by specific repo, use repo name in benchmark name
            repo_clean = args.repo.replace("/", "__")
            repos_str = repo_clean
        else:
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
    if args.repo:
        print(f"[INFO] Filtering to repository: {args.repo}")
    elif args.max_repos:
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
        # Process instance IDs if provided
        instance_ids_list = None
        if args.instance_ids:
            instance_ids_list = [id.strip() for id in args.instance_ids.split(",")]
            print(f"[INFO] Filtering to specific instances: {instance_ids_list}")

        # Create benchmark
        benchmark, results = await create_benchmark(
            client,
            args.max_instances_per_repo,
            args.name,
            args.start_from,
            args.test_gold_patch,
            args.max_concurrent,
            args.max_repos,
            args.repo,
            args.debug,
            instance_ids_list,
            args.overwrite_blueprint,
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

        """
        # Show detailed scenario summary
        print("\n" + "=" * 80)
        print("DETAILED SCENARIO STATUS")
        print("=" * 80)
        scenarios = get_scenario_status(".")
        print_scenario_summary(scenarios)
        """

    except Exception as e:
        print(f"\n[ERROR] Failed to create benchmark: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
