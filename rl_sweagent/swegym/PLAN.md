# SWE-Gym to Runloop Integration Plan (Simplified)

## Overview
This module uses the existing SWE-bench test_spec.py to generate scripts for Runloop scenarios.

## Directory Structure

```
rl_sweagent/swegym/
├── __init__.py
├── constants.py          # Copied from swe-bench-fork
├── test_spec.py          # Copied from swe-bench-fork
├── utils.py              # Copied from swe-bench-fork
├── dockerfiles.py        # Copied from swe-bench-fork
├── scenario_builder.py   # Build Runloop scenarios
└── __main__.py          # Main entry point
```

## Implementation

### 1. Copy Required Files

All files are copied from the SWE-Bench-Fork repository:

```bash
# Copy core files from swe-bench-fork
cp swe-bench-fork/swebench/harness/constants.py rl_sweagent/swegym/constants.py
cp swe-bench-fork/swebench/harness/test_spec.py rl_sweagent/swegym/test_spec.py
cp swe-bench-fork/swebench/harness/utils.py rl_sweagent/swegym/utils.py
cp swe-bench-fork/swebench/harness/dockerfiles.py rl_sweagent/swegym/dockerfiles.py
```

Each file includes a comment at the top with its source URL:
- constants.py: https://github.com/SWE-Gym/SWE-Bench-Fork/blob/main/swebench/harness/constants.py
- test_spec.py: https://github.com/SWE-Gym/SWE-Bench-Fork/blob/main/swebench/harness/test_spec.py
- utils.py: https://github.com/SWE-Gym/SWE-Bench-Fork/blob/main/swebench/harness/utils.py
- dockerfiles.py: https://github.com/SWE-Gym/SWE-Bench-Fork/blob/main/swebench/harness/dockerfiles.py

After copying, the imports in these files need to be updated from `swebench.harness.*` to `rl_sweagent.swegym.*`.

### 2. Create Scenario Builder (`scenario_builder.py`)

```python
from runloop_api_client import AsyncRunloop
from runloop_api_client.types import (
    ScoringContractParam,
    ScenarioEnvironment,
    InputContextParam,
    LaunchParameters,
)
from datasets import load_dataset
from test_spec import make_test_spec, TestSpec
import os

async def create_swegym_scenario(
    client: AsyncRunloop,
    instance_id: str,
    use_snapshot: str = None
):
    """Create a Runloop scenario from a SWE-Gym instance"""

    # Load instance from dataset
    dataset = load_dataset("SWE-Gym/SWE-Gym", split="train", streaming=True)
    instance = None
    for ex in dataset:
        if ex.get('instance_id') == instance_id:
            instance = ex
            break

    if not instance:
        raise ValueError(f"Instance {instance_id} not found")

    # Create test spec using swe-bench logic
    test_spec = make_test_spec(instance)

    # Generate setup script (combines env + repo setup)
    setup_script = f"""#!/bin/bash
set -euxo pipefail

# Install system dependencies
sudo apt-get update
sudo apt-get install -y wget git build-essential libffi-dev libtiff-dev python3 python3-pip

# Install Miniconda
if [ ! -d /opt/miniconda3 ]; then
    wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh
    bash miniconda.sh -b -p /opt/miniconda3
    rm miniconda.sh
fi

export PATH=/opt/miniconda3/bin:$PATH
conda init bash

# Environment setup
{test_spec.setup_env_script}

# Repository setup
{test_spec.install_repo_script}
"""

    # Generate scoring script (evaluation)
    scoring_script = f"""#!/bin/bash
set -eo pipefail

# Run evaluation
{test_spec.eval_script}

# Return score based on exit code
if [ $? -eq 0 ]; then
    echo "1.0"
else
    echo "0.0"
fi
"""

    # Create or reuse snapshot
    if use_snapshot:
        snapshot_id = use_snapshot
    else:
        # Create devbox with setup
        devbox = await client.devboxes.create_and_await_running(
            name=f"SWE-Gym-{instance_id}",
            launch_parameters=LaunchParameters(
                launch_commands=[
                    "echo 'Setting up SWE-Gym environment'",
                    f"echo '{setup_script}' > /tmp/setup.sh",
                    "chmod +x /tmp/setup.sh",
                    "bash /tmp/setup.sh"
                ]
            ),
            metadata={
                "instance_id": instance_id,
                "repo": test_spec.repo,
                "version": test_spec.version,
            }
        )

        # Create snapshot
        snapshot = await client.devboxes.snapshot_disk(
            id=devbox.id,
            name=f"swegym-{instance_id}-snapshot",
            timeout=300
        )
        snapshot_id = snapshot.id

        # Shutdown devbox
        await client.devboxes.shutdown(id=devbox.id)

    # Create scenario
    scenario_config = {
        "name": f"swegym-{instance_id}",
        "input_context": InputContextParam(
            problem_statement=instance['problem_statement'],
            additional_context=format_additional_context(instance, test_spec)
        ),
        "scoring_contract": ScoringContractParam(
            scoring_function_parameters=[{
                "name": "test_evaluation",
                "scorer": {
                    "type": "bash_script_scorer",
                    "bash_script": scoring_script,
                },
                "weight": 1.0,
            }]
        ),
        "environment_parameters": ScenarioEnvironment(
            snapshot_id=snapshot_id,
        ),
        "metadata": {
            "instance_id": instance_id,
            "repo": test_spec.repo,
            "version": test_spec.version,
            "base_commit": instance['base_commit'],
        }
    }

    scenario = await client.scenarios.create(**scenario_config)
    return scenario

def format_additional_context(instance: dict, test_spec: TestSpec) -> str:
    """Format additional context for the scenario"""
    parts = [
        f"Repository: {test_spec.repo}",
        f"Version: {test_spec.version}",
        f"Base Commit: {instance['base_commit']}",
    ]

    if test_spec.FAIL_TO_PASS:
        parts.append(f"\nTests to fix (FAIL_TO_PASS):\n" +
                    "\n".join(f"- {t}" for t in test_spec.FAIL_TO_PASS))

    if test_spec.PASS_TO_PASS:
        parts.append(f"\nTests to keep passing (PASS_TO_PASS):\n" +
                    "\n".join(f"- {t}" for t in test_spec.PASS_TO_PASS))

    if instance.get('hints_text'):
        parts.append(f"\nHints: {instance['hints_text']}")

    return "\n".join(parts)
```

### 3. Main Entry Point (`__main__.py`)

```python
import asyncio
import argparse
import os
from runloop_api_client import AsyncRunloop
from scenario_builder import create_swegym_scenario

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True, help="SWE-Gym instance ID")
    parser.add_argument("--snapshot-id", help="Use existing snapshot")

    args = parser.parse_args()

    client = AsyncRunloop(bearer_token=os.getenv("RUNLOOP_API_KEY"))

    scenario = await create_swegym_scenario(
        client,
        args.instance_id,
        args.snapshot_id
    )

    print(f"Created scenario: {scenario.id}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Usage

```bash
# Create a scenario
python -m rl_sweagent.swegym --instance-id getmoto__moto-7365

# Use existing snapshot
python -m rl_sweagent.swegym --instance-id getmoto__moto-7365 --snapshot-id snp_xxx
```

## Benefits

1. **Reuses proven code**: Uses SWE-bench's test_spec.py directly
2. **Simple**: Minimal new code to maintain
3. **Compatible**: Generates the same scripts as SWE-bench
4. **Efficient**: Can reuse snapshots across similar instances
