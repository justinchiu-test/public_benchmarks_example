#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def analyze_instance(instance_dir):
    """Analyze a single instance directory and return its status."""
    instance_id = instance_dir.name
    result = {
        "instance_id": instance_id,
        "scenario_created": False,
        "gold_patch_status": "not_attempted",
        "failure_stage": None,
        "error_summary": None,
    }

    # Check scenarios.jsonl for overall status
    scenarios_file = instance_dir.parent / "scenarios.jsonl"
    if scenarios_file.exists():
        with open(scenarios_file, "r") as f:
            for line in f:
                data = json.loads(line)
                if data.get("instance_id") == instance_id:
                    result["scenario_created"] = data.get("scenario_id") is not None
                    result["gold_patch_status"] = data.get(
                        "gold_patch_test_status", "not_attempted"
                    )
                    if "error" in data:
                        result["error_summary"] = data["error"]
                    break

    # Check scenario creation logs
    scenario_logs = instance_dir / "scenario_creation_logs.json"
    if scenario_logs.exists():
        with open(scenario_logs, "r") as f:
            logs = json.load(f)

        # Find where it failed
        for log in logs:
            if log.get("exit_status", 0) != 0:
                result["failure_stage"] = log.get("stage", "unknown")

                # Extract error message
                stderr = log.get("stderr", "")
                stdout = log.get("stdout", "")

                # Look for specific error patterns
                if "ERROR: Could not find a version that satisfies" in stdout:
                    lines = stdout.split("\n")
                    for line in lines:
                        if "ERROR: Could not find a version" in line:
                            result["error_summary"] = line.strip()
                            break
                elif "ERROR: No matching distribution" in stdout:
                    lines = stdout.split("\n")
                    for line in lines:
                        if "ERROR: No matching distribution" in line:
                            result["error_summary"] = line.strip()
                            break
                elif "error: subprocess-exited-with-error" in stderr:
                    result["error_summary"] = "subprocess-exited-with-error"
                elif "error: metadata-generation-failed" in stderr:
                    result["error_summary"] = "metadata-generation-failed"
                elif "[PdmUsageError]" in stderr:
                    lines = stderr.split("\n")
                    for line in lines:
                        if "[PdmUsageError]" in line:
                            result["error_summary"] = line.strip()
                            break
                elif "ModuleNotFoundError" in stderr:
                    lines = stderr.split("\n")
                    for line in lines:
                        if "ModuleNotFoundError" in line:
                            result["error_summary"] = line.strip()
                            break
                elif stderr.strip():
                    # Get last non-empty line of stderr
                    lines = [line for line in stderr.split("\n") if line.strip()]
                    if lines:
                        # Check if this is a killed process (OOM)
                        last_line = lines[-1].strip()
                        if "Killed" in last_line and "conda.sh" in last_line:
                            result["error_summary"] = (
                                "OOM: " + last_line[:100] + "..."
                                if len(last_line) > 100
                                else "OOM: " + last_line
                            )
                        else:
                            result["error_summary"] = (
                                last_line[:100] + "..."
                                if len(last_line) > 100
                                else last_line
                            )
                break

    # Check gold patch test logs
    gold_patch_logs = instance_dir / "gold_patch_test_logs.json"
    if gold_patch_logs.exists():
        with open(gold_patch_logs, "r") as f:
            data = json.load(f)
            result["gold_patch_status"] = data.get("status", "unknown")
            result["patch_applied"] = data.get("patch_applied", False)
            result["test_score"] = data.get("score", None)

    return result


def main():
    if len(sys.argv) > 1:
        logs_dir = Path(sys.argv[1])
    else:
        logs_dir = Path.cwd()

    # Find all instance directories
    instances = []
    for item in sorted(logs_dir.iterdir()):
        if item.is_dir() and "__" in item.name:
            instances.append(item)

    # Open output file
    output_file = logs_dir / "analysis.txt"
    with open(output_file, "w") as f:
        f.write(f"Analyzing {len(instances)} instances in {logs_dir}\n\n")
        print(f"Writing analysis to {output_file}")

        # Group by repository
        by_repo = {}
        for instance_dir in instances:
            result = analyze_instance(instance_dir)
            repo = result["instance_id"].rsplit("-", 1)[0].replace("__", "/")
            if repo not in by_repo:
                by_repo[repo] = []
            by_repo[repo].append(result)

        # Print results by repository
        total_success = 0
        total_instances = 0

        # Track error types for summary
        error_types = {}

        for repo in sorted(by_repo.keys()):
            results = by_repo[repo]
            f.write(f"\n{'='*80}\n")
            f.write(f"Repository: {repo}\n")
            f.write(f"{'='*80}\n")

            success_count = 0
            for r in sorted(results, key=lambda x: x["instance_id"]):
                total_instances += 1

                # Determine overall status
                if r["gold_patch_status"] == "valid" and r.get("test_score", 0) > 0:
                    status = "✅ PASSED"
                    success_count += 1
                    total_success += 1
                elif r["gold_patch_status"] == "valid" and r.get("test_score", 0) == 0:
                    status = "❌ FAILED (tests fail)"
                elif r["gold_patch_status"] == "patch_failed":
                    status = "❌ FAILED (patch failed)"
                elif r["gold_patch_status"] == "error":
                    status = "❌ ERROR"
                elif not r["scenario_created"]:
                    status = "❌ FAILED (scenario not created)"
                else:
                    status = "❓ UNKNOWN"

                f.write(f"\n{r['instance_id']}: {status}\n")

                if r["failure_stage"]:
                    f.write(f"  Failed at: {r['failure_stage']}\n")

                if r["error_summary"]:
                    f.write(f"  Error: {r['error_summary']}\n")
                    # Track error types
                    error_key = f"{r['failure_stage']}:{r['error_summary'][:50]}"
                    if error_key not in error_types:
                        error_types[error_key] = []
                    error_types[error_key].append(r["instance_id"])

                if r["gold_patch_status"] == "valid":
                    f.write(f"  Patch applied: {r.get('patch_applied', 'unknown')}\n")
                    f.write(f"  Test score: {r.get('test_score', 'unknown')}\n")

            f.write(f"\nRepository summary: {success_count}/{len(results)} passed\n")

        # Overall summary
        f.write(f"\n{'='*80}\n")
        f.write(
            f"OVERALL SUMMARY: {total_success}/{total_instances} passed ({total_success/total_instances*100:.1f}%)\n"
        )
        f.write(f"{'='*80}\n")

        # Error summary
        f.write(f"\n{'='*80}\n")
        f.write("ERROR SUMMARY BY TYPE\n")
        f.write(f"{'='*80}\n\n")

        # Group similar errors
        grouped_errors = {}
        oom_instances = []

        for error_key, instances in error_types.items():
            stage, error_msg = error_key.split(":", 1)

            # Categorize errors
            if "504 Gateway Time-out" in error_msg:
                category = "API Timeout (504)"
            elif "Killed" in error_msg and "conda.sh" in error_msg:
                category = "OOM (Out of Memory) - Conda Environment Setup"
                oom_instances.extend(instances)
            elif "No matching distribution found for cucim" in error_msg:
                category = "Missing CUDA/GPU Package (cucim)"
            elif "make: ***" in error_msg and "Makefile" in error_msg:
                category = "Makefile/PDM Build Error"
            elif "IncompleteRead" in error_msg:
                category = "Network Download Error"
            else:
                category = error_msg[:50] + "..." if len(error_msg) > 50 else error_msg

            if category not in grouped_errors:
                grouped_errors[category] = {"stage": stage, "instances": []}
            grouped_errors[category]["instances"].extend(instances)

        # Print grouped errors
        for category, info in sorted(
            grouped_errors.items(), key=lambda x: len(x[1]["instances"]), reverse=True
        ):
            f.write(f"{category} ({len(info['instances'])} instances)\n")
            f.write(f"  Stage: {info['stage']}\n")
            f.write("  Affected instances:\n")
            for inst in sorted(info["instances"]):
                f.write(f"    - {inst}\n")
            f.write("\n")

        # Highlight OOM issues specifically
        if oom_instances:
            f.write(f"\n{'='*80}\n")
            f.write("CRITICAL: OOM (Out of Memory) Issues Detected\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"Total OOM failures: {len(oom_instances)}\n")
            f.write(
                "These instances failed due to memory constraints during conda environment setup.\n"
            )
            f.write(
                "Exit code 137 (SIGKILL) indicates the process was killed by the system.\n"
            )
            f.write("\nAffected instances:\n")
            for inst in sorted(set(oom_instances)):
                f.write(f"  - {inst}\n")
            f.write("\nThese failures require either:\n")
            f.write("  1. More memory allocation for the environment\n")
            f.write("  2. Simplified conda dependency specifications\n")
            f.write("  3. Pre-built environments or Docker images\n")

    print(f"\nAnalysis complete. Results written to {output_file}")


if __name__ == "__main__":
    main()
