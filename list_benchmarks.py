from runloop_api_client import Runloop

client = Runloop()
benchmarks = client.benchmarks.list_public()

for benchmark in benchmarks:
    print(benchmark.name, benchmark.id)
    if "smith" in benchmark.name:
        x = benchmark

scenario_ids = x.scenario_ids
scenarios = [client.scenarios.retrieve(id) for id in scenario_ids[:10]]

