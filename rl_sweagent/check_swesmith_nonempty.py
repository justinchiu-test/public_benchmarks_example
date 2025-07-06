import asyncio
import csv
import glob
from tqdm.asyncio import tqdm
from runloop_api_client import NOT_GIVEN, AsyncRunloop, NotGiven
from runloop_api_client.types import ScenarioView

runloop_api = AsyncRunloop()

benchmark_id = "bmd_30OwC7ZxCbVkpMu0hyNPx"
# Set to the name of the benchmark you will clone into
cloned_name = "swesmith-nonempty"


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

    semaphore = asyncio.Semaphore(256)
    scenarios = await tqdm.gather(*[retrieve_scenario(scenario_id, instance_ids, semaphore) for scenario_id in benchmark_scenario_ids], desc="Retrieving scenarios")
    final_scenario_ids = [x for x in scenarios if x is not None]
    print(f"Found {len(final_scenario_ids)} scenarios")

    import pdb; pdb.set_trace()

if __name__ == "__main__":
    asyncio.run(main())
