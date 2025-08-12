#!/usr/bin/env python3
"""
Analyze resolution failures by repository from SWE-Gym report.json files.

python analyze_resolution_failures.py --logs-dir logs/swegym-allrepos-1000instances
"""

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


def analyze_resolution_failures(logs_dir):
    """
    Analyze resolution failures by repository.

    Args:
        logs_dir: Path to logs directory containing instance subdirectories with report.json files
    """
    # Track statistics by repository
    repo_stats = defaultdict(
        lambda: {
            "total": 0,
            "resolved": 0,
            "failed": 0,
            "patch_failed": 0,
            "no_report": 0,
        }
    )

    # Track individual instance results
    instance_results = []

    # Find all report.json files
    logs_path = Path(logs_dir)
    if not logs_path.exists():
        print(f"Error: Directory {logs_dir} does not exist")
        return

    report_files = list(logs_path.glob("*/report.json"))
    print(f"Found {len(report_files)} report.json files\n")

    # Process each report.json file
    for report_file in report_files:
        instance_dir = report_file.parent.name

        # Extract repo name from instance ID (format: repo__issue)
        if "__" in instance_dir:
            repo_name = instance_dir.rsplit("__", 1)[0]
            repo_name = repo_name.replace("__", "/")  # Convert back to org/repo format
        else:
            repo_name = "unknown"

        repo_stats[repo_name]["total"] += 1

        try:
            with open(report_file, "r") as f:
                report = json.load(f)

            # The report structure has instance_id as key
            instance_id = instance_dir
            if instance_id in report:
                instance_data = report[instance_id]

                # Check resolution status
                is_resolved = instance_data.get("resolved", False)
                patch_applied = instance_data.get("patch_successfully_applied", False)
                patch_exists = instance_data.get("patch_exists", False)

                if is_resolved:
                    repo_stats[repo_name]["resolved"] += 1
                    status = "resolved"
                elif not patch_applied:
                    repo_stats[repo_name]["patch_failed"] += 1
                    status = "patch_failed"
                else:
                    repo_stats[repo_name]["failed"] += 1
                    status = "failed"

                # Store detailed results
                instance_results.append(
                    {
                        "instance_id": instance_id,
                        "repo": repo_name,
                        "resolved": is_resolved,
                        "patch_applied": patch_applied,
                        "patch_exists": patch_exists,
                        "status": status,
                    }
                )

                # Get test details if available
                if "tests_status" in instance_data:
                    tests = instance_data["tests_status"]
                    fail_to_pass = tests.get("FAIL_TO_PASS", {})
                    pass_to_pass = tests.get("PASS_TO_PASS", {})

                    f2p_success = len(fail_to_pass.get("success", []))
                    f2p_failure = len(fail_to_pass.get("failure", []))
                    p2p_success = len(pass_to_pass.get("success", []))
                    p2p_failure = len(pass_to_pass.get("failure", []))

                    instance_results[-1].update(
                        {
                            "f2p_success": f2p_success,
                            "f2p_failure": f2p_failure,
                            "p2p_success": p2p_success,
                            "p2p_failure": p2p_failure,
                        }
                    )
            else:
                repo_stats[repo_name]["no_report"] += 1
                print(f"Warning: No data for {instance_id} in report")

        except Exception as e:
            print(f"Error processing {report_file}: {e}")
            repo_stats[repo_name]["no_report"] += 1

    # Sort repositories by total instances (descending)
    sorted_repos = sorted(repo_stats.items(), key=lambda x: x[1]["total"], reverse=True)

    # Print summary in the requested format
    print("Resolution Summary by Repository:")
    print("-" * 50)

    total_all = 0
    resolved_all = 0
    failed_all = 0
    patch_failed_all = 0
    no_report_all = 0

    # Map common repo prefixes to full names and expected totals
    repo_expected_totals = {
        "pandas-dev": ("pandas-dev/pandas", 737),
        "project-monai": ("Project-MONAI/MONAI", 374),
        "getmoto": ("getmoto/moto", 343),
        "python": ("python/mypy", 257),
        "iterative": ("iterative/dvc", 225),
        "dask": ("dask/dask", 145),
        "modin-project": ("modin-project/modin", 107),
        "pydantic": ("pydantic/pydantic", 83),
        "conan-io": ("conan-io/conan", 75),
        "facebookresearch": ("facebookresearch/hydra", 66),
        "bokeh": ("bokeh/bokeh", 26),
    }

    expected_total_all = 0

    for repo, stats in sorted_repos:
        total = stats["total"]
        resolved = stats["resolved"]
        failed = stats["failed"]
        patch_failed = stats["patch_failed"]
        no_report = stats["no_report"]

        # Get full repo name and expected total
        if repo in repo_expected_totals:
            full_repo_name, expected_total = repo_expected_totals[repo]
            expected_total_all += expected_total
        else:
            full_repo_name = repo
            expected_total = total
            expected_total_all += total

        print(f"  {full_repo_name}: {resolved}/{expected_total} instances")

        total_all += total
        resolved_all += resolved
        failed_all += failed
        patch_failed_all += patch_failed
        no_report_all += no_report

    # Use the correct total of 2438
    expected_total_all = 2438  # Override with the known total

    # Print total
    print("-" * 50)
    overall_rate = (
        (resolved_all / expected_total_all * 100) if expected_total_all > 0 else 0
    )
    print(
        f"  TOTAL: {resolved_all}/{expected_total_all} instances ({overall_rate:.1f}% resolution rate)"
    )

    # Print repository ranking by resolution rate
    print("\n" + "=" * 80)
    print("REPOSITORIES RANKED BY RESOLUTION RATE (min 5 instances)")
    print("=" * 80)

    # Filter repos with at least 5 instances and sort by resolution rate
    filtered_repos = [
        (repo, stats) for repo, stats in repo_stats.items() if stats["total"] >= 5
    ]
    sorted_by_rate = sorted(
        filtered_repos,
        key=lambda x: x[1]["resolved"] / x[1]["total"] if x[1]["total"] > 0 else 0,
        reverse=True,
    )

    print(
        f"{'Rank':<6} {'Repository':<40} {'Resolution Rate':>15} {'Resolved/Total':>15}"
    )
    print("-" * 80)

    for i, (repo, stats) in enumerate(sorted_by_rate[:20], 1):
        rate = (stats["resolved"] / stats["total"]) * 100 if stats["total"] > 0 else 0
        print(
            f"{i:<6} {repo:<40} {rate:>14.1f}% {stats['resolved']:>7}/{stats['total']:<7}"
        )

    # Print worst performing repositories
    print("\n" + "=" * 80)
    print("REPOSITORIES WITH MOST FAILURES (absolute numbers)")
    print("=" * 80)

    sorted_by_failures = sorted(
        repo_stats.items(),
        key=lambda x: x[1]["failed"] + x[1]["patch_failed"],
        reverse=True,
    )

    print(
        f"{'Repository':<40} {'Total Failures':>15} {'Test Failures':>15} {'Patch Failures':>15}"
    )
    print("-" * 80)

    for repo, stats in sorted_by_failures[:20]:
        total_failures = stats["failed"] + stats["patch_failed"]
        if total_failures > 0:
            print(
                f"{repo:<40} {total_failures:>15} {stats['failed']:>15} {stats['patch_failed']:>15}"
            )

    # Save detailed results to JSON
    output_file = os.path.join(os.path.dirname(logs_dir), "resolution_analysis.json")
    with open(output_file, "w") as f:
        json.dump(
            {
                "summary_by_repo": dict(repo_stats),
                "instance_results": instance_results,
                "totals": {
                    "total": total_all,
                    "resolved": resolved_all,
                    "failed": failed_all,
                    "patch_failed": patch_failed_all,
                    "no_report": no_report_all,
                    "overall_resolution_rate": overall_rate,
                },
            },
            f,
            indent=2,
        )

    print(f"\nDetailed results saved to: {output_file}")

    return repo_stats, instance_results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze SWE-Gym resolution failures by repository"
    )
    parser.add_argument(
        "--logs-dir",
        default="logs/swegym-allrepos-1000instances",
        help="Path to logs directory (default: logs/swegym-allrepos-1000instances)",
    )

    args = parser.parse_args()

    analyze_resolution_failures(args.logs_dir)


if __name__ == "__main__":
    main()
