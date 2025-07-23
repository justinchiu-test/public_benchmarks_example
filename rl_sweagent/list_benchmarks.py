from runloop_api_client import Runloop


def main():
    client = Runloop()
    benchmarks = client.benchmarks.list_public()

    for benchmark in benchmarks:
        print(benchmark.name, benchmark.id)

    # private
    benchmarks = client.benchmarks.list()
    for benchmark in benchmarks:
        print(benchmark.name, benchmark.id)


if __name__ == "__main__":
    main()
