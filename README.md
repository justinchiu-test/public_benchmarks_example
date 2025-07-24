# Public Benchmarks Example

This repository contains a script to run public benchmarks using the Runloop API.

## Setup
Export your Runloop API Key.
You can get an API key from the Runloop dashboard at https://platform.runloop.ai/manage/keys
```bash
export RUNLOOP_API_KEY=<YOUR_API_KEY>
```

### Python setup
1. Install `uv` (if not already installed):
See: https://docs.astral.sh/uv/getting-started/installation/
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Sync Dependencies:
```bash
uv sync
```
### Node setup
1. Install `Node.js` from [https://nodejs.org/en/download](https://nodejs.org/en/download) (if not already installed)

2. Install packages via package manager
```bash
npm install # or pnpm install
```

## Usage

The script can be run in several ways:
- If using python, use the command `uv run run_public_benchmark.py`
- If using typescript, use the command `npx tsx runPublicBenchmark.ts`
- The README will continue with python command

1. Run a specific benchmark:
```bash
uv run run_public_benchmark.py --benchmark-id <BENCHMARK_ID>
```

2. Run a specific scenario by ID:
```bash
uv run run_public_benchmark.py --scenario-id <SCENARIO_ID>
```

3. Run a specific scenario by name:
```bash
uv run run_public_benchmark.py --scenario-name <SCENARIO_NAME>
```

# SWE Bench Examples
1. Run full SWE Bench Verified benchmark:
```bash
uv run run_public_benchmark.py --benchmark-id bmd_2zmp3Mu3LhWu7yDVIfq3m
```

2. Run a specific SWE bench verified scenario by instance ID:
See full list of scenarios at: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
```bash
uv run run_public_benchmark.py --scenario-name astropy__astropy-12907
```

### Additional Options
- `--keep-devbox`: Keep the devbox running after scoring for manual inspection and debugging
- `--force-clear-running-devboxes`: Force shutdown all running devboxes before running the benchmark/scenario


## Creating SWE-Gym Benchmarks

The repository includes tools to create benchmarks from the SWE-Gym dataset.

### SWE-Gym Dataset
SWE-Gym is available at: https://huggingface.co/datasets/SWE-Gym/SWE-Gym

### Creating Benchmarks

1. Create scenarios from SWE-Gym instances:
```bash
uv run rl_sweagent/swegym/create_swegym_benchmark.py create 10 --name my-benchmark
```

This will create 10 scenarios from the SWE-Gym dataset.

2. Create scenarios with gold patch testing:
```bash
uv run rl_sweagent/swegym/create_swegym_benchmark.py create 10 --name my-benchmark --test-gold-patch
```

This validates that the gold patches actually fix the failing tests.

3. Create scenarios starting from a specific index:
```bash
uv run rl_sweagent/swegym/create_swegym_benchmark.py create 10 --name my-benchmark --start-from 100
```

4. Control concurrency:
```bash
uv run rl_sweagent/swegym/create_swegym_benchmark.py create 50 --name my-benchmark --max-concurrent 10
```

### Checking Status

View the status of created scenarios:
```bash
uv run rl_sweagent/swegym/create_swegym_benchmark.py status
```

### Logging Structure

All logs are saved in an organized directory structure:

```
logs/
├── {benchmark_name}/
│   ├── scenarios.jsonl                        # Main JSONL file tracking all scenarios
│   ├── benchmark_{id}.json                    # Benchmark creation results
│   └── {instance_id}/
│       ├── scenario_details.json              # Scenario configuration (repo, tests, etc.)
│       ├── scenario_creation_logs.json        # Full stdout/stderr from scenario creation
│       └── gold_patch_test_logs.json          # Full stdout/stderr from gold patch testing
```

#### Log Files

- **scenarios.jsonl**: Contains one line per scenario with instance_id, scenario_id, and gold patch test results
- **scenario_details.json**: Contains scenario metadata including fail_to_pass and pass_to_pass tests
- **scenario_creation_logs.json**: Full command logs from:
  - Base setup (system packages + conda installation)
  - Environment setup (conda environment creation)
  - Repository setup (cloning and installing dependencies)
  - Verification commands
- **gold_patch_test_logs.json**: Full command logs from:
  - Patch file verification
  - Pre-patch git status
  - Patch application
  - Post-patch diff
  - Test execution and scoring output

### Example Workflow

```bash
# Create 20 scenarios with gold patch validation
uv run rl_sweagent/swegym/create_swegym_benchmark.py create 20 --name swegym-test --test-gold-patch

# Check status
uv run rl_sweagent/swegym/create_swegym_benchmark.py status

# Examine logs for a specific instance
cat logs/swegym-test/getmoto__moto-7365/scenario_creation_logs.json
cat logs/swegym-test/getmoto__moto-7365/gold_patch_test_logs.json

# Run the created benchmark
uv run run_public_benchmark.py --benchmark-name swegym-test
```

## Notes
- The script limits concurrent scenario runs to 50
- SWE-Gym scenarios test repository-specific bug fixes across different versions
- Gold patch testing ensures the provided patches actually fix the failing tests
- Use `--max-concurrent` to control resource usage during benchmark creation
