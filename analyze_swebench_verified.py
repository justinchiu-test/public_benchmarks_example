#!/usr/bin/env python3
"""Analyze SWE-bench Verified trajectories and success rates."""

import json
from collections import defaultdict
from pathlib import Path

trajectories_dir = Path("trajectories/princeton-nlp")
output_dir = Path("resolved_instances")
output_dir.mkdir(exist_ok=True)

# Track each date/model combination separately
model_runs = defaultdict(
    lambda: {"trajectories_exist": 0, "successful": 0, "resolved_instances": []}
)

# Process all trajectory directories
for dataset_dir in trajectories_dir.iterdir():
    if not dataset_dir.is_dir() or not dataset_dir.name.startswith(
        "SWE-bench_Verified"
    ):
        continue

    date = dataset_dir.name.replace("SWE-bench_Verified-", "")

    for potential_model_or_org in dataset_dir.iterdir():
        if not potential_model_or_org.is_dir():
            continue

        # Check if this is a model directory (contains instance directories with .traj files)
        # or an org directory (contains model directories)

        # First, check if it looks like a direct model directory (like claude-sonnet-4-20250514)
        has_traj_files = any(
            (d / f"{d.name}.traj").exists()
            for d in potential_model_or_org.iterdir()
            if d.is_dir()
        )

        if has_traj_files:
            # This is a direct model directory (no org level)
            model = potential_model_or_org.name
            model_run_id = f"{date}/{model}"

            # Count trajectories and successes
            for instance_dir in potential_model_or_org.iterdir():
                if not instance_dir.is_dir():
                    continue

                instance_name = instance_dir.name

                # Check if trajectory file exists
                traj_file = instance_dir / f"{instance_name}.traj"
                if traj_file.exists():
                    model_runs[model_run_id]["trajectories_exist"] += 1

                    # Check if score.json exists and has score=1.0
                    score_file = instance_dir / "score.json"
                    if score_file.exists():
                        try:
                            with open(score_file, "r") as f:
                                score_data = json.load(f)
                            if score_data.get("score", 0) == 1.0:
                                model_runs[model_run_id]["successful"] += 1
                                model_runs[model_run_id]["resolved_instances"].append(
                                    instance_name
                                )
                        except Exception:
                            pass  # Skip if can't read score
        else:
            # This is an org directory containing model directories
            org = potential_model_or_org.name

            for model_dir in potential_model_or_org.iterdir():
                if not model_dir.is_dir():
                    continue
                model = model_dir.name

                # Create unique identifier for this model run
                model_run_id = f"{date}/{org}/{model}"

                # Count trajectories and successes
                for instance_dir in model_dir.iterdir():
                    if not instance_dir.is_dir():
                        continue

                    instance_name = instance_dir.name

                    # Check if trajectory file exists
                    traj_file = instance_dir / f"{instance_name}.traj"
                    if traj_file.exists():
                        model_runs[model_run_id]["trajectories_exist"] += 1

                        # Check if score.json exists and has score=1.0
                        score_file = instance_dir / "score.json"
                        if score_file.exists():
                            try:
                                with open(score_file, "r") as f:
                                    score_data = json.load(f)
                                if score_data.get("score", 0) == 1.0:
                                    model_runs[model_run_id]["successful"] += 1
                                    model_runs[model_run_id][
                                        "resolved_instances"
                                    ].append(instance_name)
                            except Exception:
                                pass  # Skip if can't read score

# Print summary table
print("=" * 120)
print("SWE-BENCH VERIFIED TRAJECTORY ANALYSIS")
print("=" * 120)
print(f"{'Date':<25} {'Model':<55} {'Exist/500':>12} {'Success/500':>12} {'Rate':>8}")
print("-" * 120)

# Sort by date then model
sorted_runs = sorted(model_runs.items())

for model_run_id, stats in sorted_runs:
    parts = model_run_id.split("/")
    date = parts[0]
    if len(parts) == 3:
        # Has org/model structure
        org = parts[1]
        model = parts[2]
        model_name = f"{org}/{model}"
    else:
        # Direct model (no org)
        model = parts[1]
        model_name = model

    exist = stats["trajectories_exist"]
    success = stats["successful"]
    rate = (success / 500 * 100) if exist > 0 else 0

    print(f"{date:<25} {model_name:<55} {exist:>4}/500 {success:>4}/500 {rate:>6.1f}%")

    # Save resolved instances to file
    if stats["resolved_instances"]:
        # Create safe filename based on model_run_id
        safe_filename = model_run_id.replace("/", "_") + "_instances.txt"
        output_file = output_dir / safe_filename

        with open(output_file, "w") as f:
            for instance in sorted(stats["resolved_instances"]):
                f.write(f"{instance}\n")

# Print summary statistics
print("\n" + "=" * 120)
print("SUMMARY STATISTICS")
print("=" * 120)

# Group by model (across dates) for aggregate stats
model_aggregate = defaultdict(
    lambda: {
        "dates": [],
        "total_exist": 0,
        "total_success": 0,
        "max_trajectories": 0,
        "max_success": 0,
    }
)

for model_run_id, stats in model_runs.items():
    parts = model_run_id.split("/")
    date = parts[0]
    if len(parts) == 3:
        model_name = f"{parts[1]}/{parts[2]}"
    else:
        model_name = parts[1]

    model_aggregate[model_name]["dates"].append(date)
    model_aggregate[model_name]["total_exist"] += stats["trajectories_exist"]
    model_aggregate[model_name]["total_success"] += stats["successful"]
    model_aggregate[model_name]["max_trajectories"] = max(
        model_aggregate[model_name]["max_trajectories"], stats["trajectories_exist"]
    )
    model_aggregate[model_name]["max_success"] = max(
        model_aggregate[model_name]["max_success"], stats["successful"]
    )

print(
    f"\n{'Model':<50} {'Runs':>6} {'Max Traj':>10} {'Max Success':>12} {'Total Traj':>12} {'Total Success':>14}"
)
print("-" * 120)

sorted_models = sorted(
    model_aggregate.items(), key=lambda x: x[1]["max_success"], reverse=True
)

for model_name, agg_stats in sorted_models[:15]:  # Top 15 models
    num_runs = len(agg_stats["dates"])
    total_exist = agg_stats["total_exist"]
    total_success = agg_stats["total_success"]
    max_traj = agg_stats["max_trajectories"]
    max_success = agg_stats["max_success"]

    print(
        f"{model_name:<50} {num_runs:>6} {max_traj:>10} {max_success:>12} {total_exist:>12} {total_success:>14}"
    )

# Models with near-complete runs
print("\n" + "=" * 120)
print("NEAR-COMPLETE RUNS (>= 495 trajectories)")
print("=" * 120)

complete_runs = [
    (run_id, stats)
    for run_id, stats in model_runs.items()
    if stats["trajectories_exist"] >= 495
]
complete_runs.sort(key=lambda x: x[1]["successful"], reverse=True)

if complete_runs:
    print(f"{'Date':<25} {'Model':<55} {'Success/Exist':>15} {'Rate':>8}")
    print("-" * 120)

    for model_run_id, stats in complete_runs:
        parts = model_run_id.split("/")
        date = parts[0]
        if len(parts) == 3:
            model_name = f"{parts[1]}/{parts[2]}"
        else:
            model_name = parts[1]

        exist = stats["trajectories_exist"]
        success = stats["successful"]
        rate = (success / exist * 100) if exist > 0 else 0

        print(f"{date:<25} {model_name:<55} {success:>4}/{exist:<4} {rate:>6.1f}%")
else:
    print("No runs with >= 495 trajectories found")

# Save summary to JSON
summary_data = {
    "model_runs": {
        run_id: {
            "trajectories_exist": stats["trajectories_exist"],
            "successful": stats["successful"],
            "success_rate": (stats["successful"] / 500 * 100)
            if stats["trajectories_exist"] > 0
            else 0,
            "resolved_count": len(stats["resolved_instances"]),
        }
        for run_id, stats in model_runs.items()
    },
    "model_aggregates": {
        model: {
            "runs": len(stats["dates"]),
            "total_trajectories": stats["total_exist"],
            "total_successes": stats["total_success"],
            "max_trajectories": stats["max_trajectories"],
            "max_success": stats["max_success"],
            "dates": stats["dates"],
        }
        for model, stats in model_aggregate.items()
    },
}

with open("swebench_verified_summary.json", "w") as f:
    json.dump(summary_data, f, indent=2)

print(f"\nResolved instance lists saved to: {output_dir}/")
print("Summary saved to: swebench_verified_summary.json")
print(f"\nTotal model runs analyzed: {len(model_runs)}")
print(f"Total unique models: {len(model_aggregate)}")
