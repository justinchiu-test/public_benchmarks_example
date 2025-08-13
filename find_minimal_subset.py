#!/usr/bin/env python3
"""Find minimal subset of SWE-bench Verified that preserves model rankings."""

import json
from collections import defaultdict
from pathlib import Path

from datasets import load_dataset


def load_model_results():
    """Load all model results and organize by repo."""
    resolved_dir = Path("resolved_instances")

    if not resolved_dir.exists():
        print(f"Directory {resolved_dir} does not exist.")
        return {}

    # Load dataset to get repo information
    print("Loading SWE-bench Verified dataset...")
    dataset = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")

    # Create instance_id to repo mapping
    instance_to_repo = {}
    repo_to_instances = defaultdict(set)
    for item in dataset:
        instance_id = item["instance_id"]
        repo = item["repo"]
        instance_to_repo[instance_id] = repo
        repo_to_instances[repo].add(instance_id)

    # Load all model results
    model_results = {}

    for file_path in resolved_dir.glob("*.txt"):
        # Parse model run identifier from filename
        model_run = file_path.name.replace("_instances.txt", "").replace("_", "/")

        # Load resolved instances
        with open(file_path, "r") as f:
            resolved_instances = set(line.strip() for line in f if line.strip())

        # Organize by repo
        resolved_by_repo = defaultdict(set)
        for instance_id in resolved_instances:
            if instance_id in instance_to_repo:
                repo = instance_to_repo[instance_id]
                resolved_by_repo[repo].add(instance_id)

        model_results[model_run] = {
            "total_resolved": len(resolved_instances),
            "resolved_by_repo": dict(resolved_by_repo),
            "resolved_instances": resolved_instances,
        }

    return model_results, instance_to_repo, repo_to_instances


def calculate_rankings(model_results, repo_to_instances):
    """Calculate model rankings per repo and overall."""

    # Overall ranking
    overall_ranking = sorted(
        model_results.keys(),
        key=lambda x: model_results[x]["total_resolved"],
        reverse=True,
    )

    # Per-repo rankings
    repo_rankings = {}
    for repo in repo_to_instances:
        # Get models with their success counts for this repo
        model_scores = []
        for model, data in model_results.items():
            resolved_count = len(data["resolved_by_repo"].get(repo, set()))
            model_scores.append((model, resolved_count))

        # Sort by resolved count
        repo_rankings[repo] = [
            m for m, _ in sorted(model_scores, key=lambda x: x[1], reverse=True)
        ]

    return overall_ranking, repo_rankings


def print_current_rankings(
    overall_ranking, repo_rankings, model_results, repo_to_instances
):
    """Print current model rankings."""
    print("\n" + "=" * 100)
    print("CURRENT MODEL RANKINGS")
    print("=" * 100)

    print("\nOVERALL RANKING:")
    print("-" * 50)
    for i, model in enumerate(overall_ranking[:10], 1):
        count = model_results[model]["total_resolved"]
        print(f"{i:2}. {model:<60} {count:>4}/500 ({count/5:.1f}%)")

    print("\n\nPER-REPOSITORY RANKINGS (Top 3 per repo):")
    print("-" * 50)

    for repo in sorted(repo_to_instances.keys()):
        total_instances = len(repo_to_instances[repo])
        print(f"\n{repo} ({total_instances} instances):")

        # Show top 3 models for this repo
        for i, model in enumerate(repo_rankings[repo][:3], 1):
            resolved = len(model_results[model]["resolved_by_repo"].get(repo, set()))
            if resolved > 0:  # Only show models that resolved at least one
                percentage = (
                    (resolved / total_instances * 100) if total_instances > 0 else 0
                )
                print(
                    f"  {i}. {model:<50} {resolved:>3}/{total_instances} ({percentage:.1f}%)"
                )


def find_discriminative_instances(model_results, instance_to_repo, repo_to_instances):
    """Find instances that best discriminate between models."""

    # For each instance, calculate how many models solve it
    instance_difficulty = {}
    for instance_id in instance_to_repo:
        solved_by = sum(
            1
            for model_data in model_results.values()
            if instance_id in model_data["resolved_instances"]
        )
        instance_difficulty[instance_id] = solved_by

    # Find instances that discriminate between adjacent models in rankings
    discriminative_instances = defaultdict(set)

    # For overall ranking
    overall_ranking = sorted(
        model_results.keys(),
        key=lambda x: model_results[x]["total_resolved"],
        reverse=True,
    )

    for i in range(len(overall_ranking) - 1):
        model1 = overall_ranking[i]
        model2 = overall_ranking[i + 1]

        # Find instances solved by model1 but not model2
        diff_instances = (
            model_results[model1]["resolved_instances"]
            - model_results[model2]["resolved_instances"]
        )

        # Add most discriminative instances (solved by fewer models overall)
        for instance in sorted(
            diff_instances, key=lambda x: instance_difficulty.get(x, 0)
        )[:5]:
            repo = instance_to_repo[instance]
            discriminative_instances[repo].add(instance)

    # For per-repo rankings
    for repo, instances in repo_to_instances.items():
        # Get models that solved at least one instance in this repo
        active_models = [
            (model, len(model_results[model]["resolved_by_repo"].get(repo, set())))
            for model in model_results
            if len(model_results[model]["resolved_by_repo"].get(repo, set())) > 0
        ]

        if len(active_models) < 2:
            continue

        # Sort by success count
        active_models.sort(key=lambda x: x[1], reverse=True)

        # Find discriminative instances between adjacent models
        for i in range(len(active_models) - 1):
            model1, count1 = active_models[i]
            model2, count2 = active_models[i + 1]

            if count1 == count2:  # Same performance, no need to discriminate
                continue

            # Find instances solved by model1 but not model2 in this repo
            set1 = model_results[model1]["resolved_by_repo"].get(repo, set())
            set2 = model_results[model2]["resolved_by_repo"].get(repo, set())
            diff_instances = set1 - set2

            # Add most discriminative instances
            for instance in sorted(
                diff_instances, key=lambda x: instance_difficulty.get(x, 0)
            )[:3]:
                discriminative_instances[repo].add(instance)

    return discriminative_instances


def evaluate_subset(
    subset_instances, model_results, instance_to_repo, repo_to_instances
):
    """Evaluate if a subset preserves rankings."""

    # Calculate rankings on subset
    subset_model_results = {}
    for model, data in model_results.items():
        subset_resolved = data["resolved_instances"] & subset_instances
        subset_by_repo = defaultdict(set)
        for instance in subset_resolved:
            if instance in instance_to_repo:
                repo = instance_to_repo[instance]
                subset_by_repo[repo].add(instance)

        subset_model_results[model] = {
            "total_resolved": len(subset_resolved),
            "resolved_by_repo": dict(subset_by_repo),
        }

    # Get subset rankings
    subset_overall = sorted(
        subset_model_results.keys(),
        key=lambda x: subset_model_results[x]["total_resolved"],
        reverse=True,
    )

    subset_repo_rankings = {}
    for repo in repo_to_instances:
        model_scores = []
        for model, data in subset_model_results.items():
            resolved_count = len(data["resolved_by_repo"].get(repo, set()))
            model_scores.append((model, resolved_count))
        subset_repo_rankings[repo] = [
            m for m, _ in sorted(model_scores, key=lambda x: x[1], reverse=True)
        ]

    return subset_overall, subset_repo_rankings, subset_model_results


def main():
    # Load all model results
    print("Loading model results...")
    model_results, instance_to_repo, repo_to_instances = load_model_results()

    if not model_results:
        print("No model results found.")
        return

    print(f"Loaded results for {len(model_results)} model runs")
    print(f"Total instances: {len(instance_to_repo)}")
    print(f"Total repositories: {len(repo_to_instances)}")

    # Calculate current rankings
    overall_ranking, repo_rankings = calculate_rankings(
        model_results, repo_to_instances
    )

    # Print current rankings
    print_current_rankings(
        overall_ranking, repo_rankings, model_results, repo_to_instances
    )

    # Find discriminative instances
    print("\n" + "=" * 100)
    print("FINDING MINIMAL DISCRIMINATIVE SUBSET")
    print("=" * 100)

    discriminative = find_discriminative_instances(
        model_results, instance_to_repo, repo_to_instances
    )

    # Build minimal subset
    minimal_subset = set()
    for repo, instances in discriminative.items():
        minimal_subset.update(instances)

    print(f"\nInitial discriminative subset size: {len(minimal_subset)} instances")

    # Add instances to ensure minimum coverage per repo
    # First try to add from resolved instances, then from all instances if needed
    for repo, instances in repo_to_instances.items():
        repo_subset = minimal_subset & instances
        min_required = min(
            10, len(instances)
        )  # At least 10 instances per repo (or all if < 10)
        if len(repo_subset) < min_required:
            # First, try to add more resolved instances (easiest ones)
            remaining_resolved = instances - minimal_subset
            instance_scores = [
                (
                    inst,
                    sum(
                        1
                        for m in model_results.values()
                        if inst in m["resolved_instances"]
                    ),
                )
                for inst in remaining_resolved
            ]
            instance_scores.sort(key=lambda x: x[1], reverse=True)

            added = 0
            for inst, score in instance_scores:
                if score > 0:  # Only add if at least one model solved it
                    minimal_subset.add(inst)
                    added += 1
                    if len(repo_subset) + added >= min_required:
                        break

            # If still need more, add random unresolved instances from the dataset
            if len(repo_subset) + added < min_required:
                import random

                random.seed(42)  # For reproducibility

                # Get all instances for this repo that aren't in subset
                all_remaining = instances - minimal_subset
                remaining_list = list(all_remaining)
                random.shuffle(remaining_list)

                for inst in remaining_list[: min_required - len(repo_subset) - added]:
                    minimal_subset.add(inst)

    # Iteratively add instances for repos with poor correlation
    print(f"Initial subset size: {len(minimal_subset)} instances")

    # Target repos that need better correlation
    target_repos = ["sympy/sympy", "scikit-learn/scikit-learn"]
    target_correlation = 0.90

    for target_repo in target_repos:
        print(f"\nImproving correlation for {target_repo}...")

        # Get current correlation
        repo_instances = repo_to_instances[target_repo]
        subset_repo = minimal_subset & repo_instances

        # Calculate initial correlation
        from scipy.stats import spearmanr

        def calc_repo_correlation(repo, subset_instances):
            # Get model scores for original
            orig_scores = {}
            for model, data in model_results.items():
                score = len(data["resolved_by_repo"].get(repo, set()))
                if score > 0:
                    orig_scores[model] = score

            # Get model scores for subset
            subset_scores = {}
            for model, data in model_results.items():
                score = len(data["resolved_instances"] & subset_instances)
                if score > 0:
                    subset_scores[model] = score

            # Calculate correlation
            common_models = set(orig_scores.keys()) & set(subset_scores.keys())
            if len(common_models) <= 2:
                return 0.0

            orig_sorted = sorted(orig_scores.items(), key=lambda x: x[1], reverse=True)
            subset_sorted = sorted(
                subset_scores.items(), key=lambda x: x[1], reverse=True
            )

            orig_ranking = {m: i for i, (m, _) in enumerate(orig_sorted)}
            subset_ranking = {m: i for i, (m, _) in enumerate(subset_sorted)}

            orig_ranks = [orig_ranking[m] for m in common_models]
            subset_ranks = [subset_ranking[m] for m in common_models]

            if len(set(orig_ranks)) > 1 and len(set(subset_ranks)) > 1:
                corr, _ = spearmanr(orig_ranks, subset_ranks)
                return corr
            return 0.0

        current_corr = calc_repo_correlation(target_repo, subset_repo)
        print(f"  Current correlation: {current_corr:.3f}")
        print(f"  Current instances: {len(subset_repo)}/{len(repo_instances)}")

        if current_corr < target_correlation:
            # Try adding instances one by one until correlation improves
            remaining = repo_instances - minimal_subset

            # Score remaining instances by how many models solve them
            instance_scores = []
            for inst in remaining:
                score = sum(
                    1 for m in model_results.values() if inst in m["resolved_instances"]
                )
                instance_scores.append((inst, score))

            # Sort by score (prefer instances solved by more models)
            instance_scores.sort(key=lambda x: x[1], reverse=True)

            # Also try instances solved by fewer models for diversity
            if len(instance_scores) > 10:
                # Take some from high scores and some from medium scores
                candidates = [x[0] for x in instance_scores[:10]] + [
                    x[0] for x in instance_scores[10:20] if len(instance_scores) > 10
                ]
            else:
                candidates = [x[0] for x in instance_scores]

            # Try adding instances and check correlation
            best_additions = []
            test_subset = subset_repo.copy()

            for candidate in candidates:
                test_subset.add(candidate)
                new_corr = calc_repo_correlation(target_repo, test_subset)

                if new_corr >= target_correlation:
                    best_additions.append(candidate)
                    print(f"  Added 1 instance, new correlation: {new_corr:.3f}")
                    break
                elif new_corr > current_corr:
                    best_additions.append(candidate)
                    current_corr = new_corr
                    if len(best_additions) % 5 == 0:
                        print(
                            f"  Added {len(best_additions)} instances, correlation: {new_corr:.3f}"
                        )
                else:
                    test_subset.discard(candidate)

            # Add the best instances to the main subset
            for inst in best_additions:
                minimal_subset.add(inst)

            final_corr = calc_repo_correlation(
                target_repo, minimal_subset & repo_instances
            )
            print(f"  Final correlation: {final_corr:.3f}")
            print(
                f"  Final instances: {len(minimal_subset & repo_instances)}/{len(repo_instances)}"
            )

    print(
        f"\nFinal subset size: {len(minimal_subset)} instances ({len(minimal_subset)/500*100:.1f}% of original)"
    )

    # Check how many are resolved vs unresolved
    all_resolved = set()
    for model_data in model_results.values():
        all_resolved.update(model_data["resolved_instances"])

    resolved_in_subset = minimal_subset & all_resolved
    unresolved_in_subset = minimal_subset - all_resolved

    print(
        f"  - Resolved instances: {len(resolved_in_subset)} (solved by at least one model)"
    )
    print(
        f"  - Unresolved instances: {len(unresolved_in_subset)} (never solved by any model)"
    )

    # Evaluate subset
    subset_overall, subset_repo_rankings, subset_model_results = evaluate_subset(
        minimal_subset, model_results, instance_to_repo, repo_to_instances
    )

    # Check ranking preservation
    print("\n" + "=" * 100)
    print("RANKING PRESERVATION ANALYSIS")
    print("=" * 100)

    # Check overall ranking preservation
    print("\nOVERALL RANKING COMPARISON:")
    print(
        f"{'Original Rank':<15} {'Subset Rank':<15} {'Model':<50} {'Original':<12} {'Subset':<12}"
    )
    print("-" * 100)

    for i, model in enumerate(overall_ranking[:10], 1):
        subset_rank = (
            subset_overall.index(model) + 1 if model in subset_overall else "N/A"
        )
        orig_count = model_results[model]["total_resolved"]
        subset_count = subset_model_results[model]["total_resolved"]
        print(
            f"{i:<15} {subset_rank:<15} {model:<50} {orig_count:>4}/500 {subset_count:>4}/{len(minimal_subset)}"
        )

    # Calculate ranking correlation
    try:
        from scipy.stats import kendalltau, spearmanr

        # Get common models
        common_models = [m for m in overall_ranking if m in subset_overall]
        orig_ranks = [overall_ranking.index(m) for m in common_models]
        subset_ranks = [subset_overall.index(m) for m in common_models]

        if len(common_models) > 1:
            spearman_corr, _ = spearmanr(orig_ranks, subset_ranks)
            kendall_corr, _ = kendalltau(orig_ranks, subset_ranks)
            print("\nOverall Ranking Correlation:")
            print(f"  Spearman: {spearman_corr:.3f}")
            print(f"  Kendall Tau: {kendall_corr:.3f}")
        else:
            spearman_corr = None
            kendall_corr = None
    except ImportError:
        print("\n(scipy not available for correlation calculation)")
        spearman_corr = None
        kendall_corr = None

    # Check per-repository ranking preservation
    print("\n" + "=" * 100)
    print("PER-REPOSITORY RANKING PRESERVATION")
    print("=" * 100)

    repo_correlations = {}
    ranking_changes = []

    for repo in sorted(repo_to_instances.keys()):
        # Get models that have non-zero performance in this repo (original)
        orig_models_with_scores = []
        for model in model_results:
            score = len(model_results[model]["resolved_by_repo"].get(repo, set()))
            if score > 0:
                orig_models_with_scores.append((model, score))

        # Get models that have non-zero performance in this repo (subset)
        subset_models_with_scores = []
        for model in subset_model_results:
            score = len(
                subset_model_results[model]["resolved_by_repo"].get(repo, set())
            )
            if score > 0:
                subset_models_with_scores.append((model, score))

        if len(orig_models_with_scores) < 2:
            continue

        # Sort by score
        orig_models_with_scores.sort(key=lambda x: x[1], reverse=True)
        subset_models_with_scores.sort(key=lambda x: x[1], reverse=True)

        # Get rankings
        orig_ranking = [m for m, _ in orig_models_with_scores]
        subset_ranking = [m for m, _ in subset_models_with_scores]

        # Compare top 3
        print(f"\n{repo}:")
        print(f"  Original instances: {len(repo_to_instances[repo])}")
        print(f"  Subset instances: {len(minimal_subset & repo_to_instances[repo])}")

        print("  Original top 3:")
        for i, (model, score) in enumerate(orig_models_with_scores[:3], 1):
            print(
                f"    {i}. {model.split('/')[-1][:40]:40} {score}/{len(repo_to_instances[repo])}"
            )

        print("  Subset top 3:")
        subset_in_repo = len(minimal_subset & repo_to_instances[repo])
        for i, (model, score) in enumerate(subset_models_with_scores[:3], 1):
            print(f"    {i}. {model.split('/')[-1][:40]:40} {score}/{subset_in_repo}")

        # Check if top model changed
        if orig_models_with_scores and subset_models_with_scores:
            orig_top = orig_models_with_scores[0][0]
            subset_top = (
                subset_models_with_scores[0][0] if subset_models_with_scores else None
            )

            if orig_top != subset_top:
                ranking_changes.append(repo)
                print("  ⚠️ TOP MODEL CHANGED!")

        # Calculate correlation if enough models
        common = [m for m in orig_ranking if m in subset_ranking]
        if len(common) > 2:
            try:
                orig_ranks = [orig_ranking.index(m) for m in common]
                subset_ranks = [subset_ranking.index(m) for m in common]
                corr, _ = spearmanr(orig_ranks, subset_ranks)
                repo_correlations[repo] = corr
                print(f"  Correlation: {corr:.3f}")
            except Exception:
                pass

    if ranking_changes:
        print(f"\n⚠️ Repositories with changed top model: {', '.join(ranking_changes)}")
    else:
        print("\n✓ All repositories maintain their top model!")

    if repo_correlations:
        avg_corr = sum(repo_correlations.values()) / len(repo_correlations)
        print(f"\nAverage per-repo correlation: {avg_corr:.3f}")
        print(
            f"Repos with correlation > 0.8: {sum(1 for c in repo_correlations.values() if c > 0.8)}/{len(repo_correlations)}"
        )

    # Save subset to file
    output_file = "minimal_subset.json"
    subset_by_repo = defaultdict(list)
    for instance in minimal_subset:
        repo = instance_to_repo[instance]
        subset_by_repo[repo].append(instance)

    output_data = {
        "total_instances": len(minimal_subset),
        "percentage_of_original": len(minimal_subset) / 500 * 100,
        "instances_by_repo": {
            repo: sorted(instances) for repo, instances in subset_by_repo.items()
        },
        "overall_ranking_correlation": {
            "spearman": spearman_corr if "spearman_corr" in locals() else None,
            "kendall_tau": kendall_corr if "kendall_corr" in locals() else None,
        },
    }

    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nMinimal subset saved to {output_file}")

    # Print subset statistics by repo
    print("\n" + "=" * 100)
    print("SUBSET STATISTICS BY REPOSITORY")
    print("=" * 100)
    print(f"{'Repository':<40} {'Original':<12} {'Subset':<12} {'Percentage':<12}")
    print("-" * 100)

    for repo in sorted(repo_to_instances.keys()):
        orig_count = len(repo_to_instances[repo])
        subset_count = len(subset_by_repo[repo])
        percentage = (subset_count / orig_count * 100) if orig_count > 0 else 0
        print(f"{repo:<40} {orig_count:<12} {subset_count:<12} {percentage:.1f}%")


if __name__ == "__main__":
    main()
