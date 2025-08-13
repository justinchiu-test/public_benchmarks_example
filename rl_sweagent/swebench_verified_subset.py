"""Create a subset of SWE-bench Verified benchmark using minimal subset."""

import asyncio
import json
from pathlib import Path

from runloop_api_client import NOT_GIVEN, AsyncRunloop, NotGiven
from runloop_api_client.types import ScenarioView

runloop_api = AsyncRunloop()

# SWE-bench Verified benchmark ID
benchmark_id = "bmd_2zmp3Mu3LhWu7yDVIfq3m"  # princeton-nlp/SWE-bench_Verified
# Set to the name of the benchmark you will clone into
cloned_name = "swebench_verified_eval_subset"


async def list_all_scenarios(search_string: str) -> list[ScenarioView]:
    scenarios: list[ScenarioView] = []
    starting_after: str | NotGiven = NOT_GIVEN
    while True:
        scenarios_response = await runloop_api.scenarios.list_public(
            extra_query={"search": f"{search_string}"},
            limit=100,
            starting_after=starting_after,
        )
        scenarios.extend(scenarios_response.scenarios)
        if not scenarios_response.has_more:
            break

        starting_after = scenarios_response.scenarios[-1].id

    return scenarios


async def main():
    # Load the minimal subset from JSON
    subset_file = Path("minimal_subset.json")
    if not subset_file.exists():
        print(f"Error: {subset_file} not found!")
        return

    with open(subset_file, "r") as f:
        subset_data = json.load(f)

    print(f"Loaded minimal subset with {subset_data['total_instances']} instances")
    print(
        f"This represents {subset_data['percentage_of_original']:.1f}% of the original 500 instances"
    )

    # Retrieve the original benchmark
    benchmark = await runloop_api.benchmarks.retrieve(benchmark_id)
    benchmark_scenario_ids = set(benchmark.scenario_ids)

    print(f"Original benchmark contains {len(benchmark_scenario_ids)} scenarios")

    # Flatten all instance IDs from the subset
    all_subset_instances = []
    for repo, instances in subset_data["instances_by_repo"].items():
        all_subset_instances.extend(instances)

    print(
        f"Subset contains {len(all_subset_instances)} instances across {len(subset_data['instances_by_repo'])} repositories"
    )

    # Search for scenarios matching our subset instances
    scoped_scenarios: list[ScenarioView] = []

    # Process instances in batches to avoid too many API calls
    for instance_id in all_subset_instances:
        # Search for scenarios with this instance ID
        query_scenarios = await list_all_scenarios(instance_id)

        if query_scenarios:
            print(f"Found {len(query_scenarios)} scenario(s) for: {instance_id}")
            scoped_scenarios.extend(query_scenarios)
        else:
            print(f"Warning: No scenarios found for: {instance_id}")

    # Filter scenarios to only include those whose IDs are in benchmark_scenario_ids set
    final_scenarios = [
        scenario
        for scenario in scoped_scenarios
        if scenario.id in benchmark_scenario_ids
    ]

    # Remove duplicates (in case same scenario matched multiple search terms)
    seen_ids = set()
    unique_scenarios = []
    for scenario in final_scenarios:
        if scenario.id not in seen_ids:
            seen_ids.add(scenario.id)
            unique_scenarios.append(scenario)

    final_scenarios = unique_scenarios

    import pdb

    pdb.set_trace()

    print("\nSummary:")
    print(f"- Original benchmark: {len(benchmark_scenario_ids)} scenarios")
    print(f"- Subset instances: {len(all_subset_instances)} instances")
    print(f"- Found scenarios: {len(scoped_scenarios)} total")
    print(f"- Matched scenarios: {len(final_scenarios)} scenarios")

    # Print repo breakdown
    print("\nInstances per repository in subset:")
    for repo, instances in sorted(subset_data["instances_by_repo"].items()):
        print(f"  {repo}: {len(instances)} instances")

    print("\nRanking correlations preserved:")
    if subset_data.get("overall_ranking_correlation"):
        print(
            f"  Spearman: {subset_data['overall_ranking_correlation']['spearman']:.3f}"
        )
        print(
            f"  Kendall Tau: {subset_data['overall_ranking_correlation']['kendall_tau']:.3f}"
        )

    response = input("create new benchmark? (y/n)")
    if response == "y":
        name = f"{cloned_name} - {benchmark.name}"

        existing_benchmarks = await runloop_api.benchmarks.list(
            extra_query={"search": f"{cloned_name}"}
        )
        if existing_benchmarks.benchmarks:
            print(f"existing benchmark found: {existing_benchmarks.benchmarks[0].id}")
            # update
            await runloop_api.benchmarks.update(
                id=existing_benchmarks.benchmarks[0].id,
                name=name,
                scenario_ids=[scenario.id for scenario in final_scenarios],
            )
            print(f"benchmark updated: {existing_benchmarks.benchmarks[0].id}")
            return
        else:
            print(f"creating new benchmark: {name}")

            new_benchmark = await runloop_api.benchmarks.create(
                name=name,
                scenario_ids=[scenario.id for scenario in final_scenarios],
            )
            print(f"new benchmark created: {new_benchmark.id}")


if __name__ == "__main__":
    asyncio.run(main())
