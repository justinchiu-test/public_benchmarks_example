from runloop_api_client import Runloop


def main():
    client = Runloop()
    benchmarks = client.benchmarks.list_public()

    for benchmark in benchmarks:
        print(benchmark.name, benchmark.id)
        if "smith" in benchmark.name:
            x = benchmark

    scenario_ids = x.scenario_ids
    scenarios = [client.scenarios.retrieve(id) for id in scenario_ids[:10]]

    # private
    benchmarks = client.benchmarks.list()
    for benchmark in benchmarks:
        print(benchmark.name, benchmark.id)


if __name__ == "__main__":
    main()

