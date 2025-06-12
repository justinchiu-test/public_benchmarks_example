from runloop_api_client import Runloop

client = Runloop()
benchmarks = client.benchmarks.list_public()

for benchmark in benchmarks:
    print(benchmark.name, benchmark.id)
