"""Create a subset of swesmith with non-empty prompts."""

import asyncio
import csv
import glob
from tqdm.asyncio import tqdm
from runloop_api_client import NOT_GIVEN, AsyncRunloop, NotGiven
from runloop_api_client.types import ScenarioView

runloop_api = AsyncRunloop()

benchmark_id = "bmd_3056xc0UoFk0xSyRKtfqC"
# Set to the name of the benchmark you will clone into
cloned_name = "swesmith-nonempty"


async def list_all_scenarios(benchmark_id: str, instance_ids: set[str]) -> list[ScenarioView]:
    scenario_ids: list[str] = []
    starting_after: str | NotGiven = NOT_GIVEN
    while True:
        scenarios_response = await runloop_api.scenarios.list(
            benchmark_id=benchmark_id,
            limit=100,
            starting_after=starting_after,
        )
        import pdb; pdb.set_trace()
        scenarios.extend(scenarios_response.scenarios)
        if not scenarios_response.has_more:
            break

        starting_after = scenarios_response.scenarios[-1].id

    return scenarios


async def main():
    benchmark = await runloop_api.benchmarks.retrieve(benchmark_id)

    # Load instance_id from CSV file in data directory
    # these are the NAMES in scenario.name = isntance_id
    instance_ids = set()
    with open("data/swesmith_nonempty.csv", 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "instance_id" in row:
                instance_ids.add(row["instance_id"])

    print(f"Loaded {len(instance_ids)} instance ids to intersect with benchmark scenario ids")

    benchmark_scenario_ids = set([id for id in benchmark.scenario_ids])

    async def retrieve_scenario(scenario_id: str, instance_ids: set[str], semaphore) -> str | None:
        async with semaphore:
            scenario_view = await runloop_api.scenarios.retrieve(scenario_id)
            return scenario_id if scenario_view.name in instance_ids else None

    semaphore = asyncio.Semaphore(128)
    scenarios = await tqdm.gather(*[retrieve_scenario(scenario_id, instance_ids, semaphore) for scenario_id in benchmark_scenario_ids], desc="Retrieving scenarios")
    final_scenario_ids = [x for x in scenarios if x is not None]
    print(f"Found {len(final_scenario_ids)} scenarios")

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
                scenario_ids=final_scenario_ids,
            )
            print(f"benchmark updated: {existing_benchmarks.benchmarks[0].id}")
            return
        else:
            print(f"creating new benchmark: {name}")

            new_benchmark = await runloop_api.benchmarks.create(
                name=name,
                scenario_ids=final_scenario_ids,
            )
            print(f"new benchmark created: {new_benchmark.id}")


if __name__ == "__main__":
    asyncio.run(main())
