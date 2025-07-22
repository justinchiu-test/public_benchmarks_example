"""Build Runloop scenarios from SWE-Gym instances."""

from runloop_api_client import AsyncRunloop
from runloop_api_client.types import (
    ScoringContractParam,
    ScenarioEnvironment,
    InputContextParam,
    LaunchParameters,
)
from datasets import load_dataset
from rl_sweagent.swegym.test_spec import make_test_spec, TestSpec
import os
import base64


async def create_swegym_scenario(
    client: AsyncRunloop,
    instance_id: str,
    use_snapshot: str = None
):
    """Create a Runloop scenario from a SWE-Gym instance"""
    
    # Load instance from dataset
    print(f"[INFO] Loading SWE-Gym instance: {instance_id}")
    dataset = load_dataset("SWE-Gym/SWE-Gym", split="train", streaming=True)
    instance = None
    for ex in dataset:
        if ex.get('instance_id') == instance_id:
            instance = ex
            break
    
    if not instance:
        raise ValueError(f"Instance {instance_id} not found")
    
    print(f"[INFO] Found instance for repo: {instance['repo']}")
    
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
        print(f"[INFO] Using existing snapshot: {snapshot_id}")
    else:
        print("[INFO] Creating new devbox...")
        
        # Encode the setup script as base64 to avoid shell escaping issues
        setup_script_b64 = base64.b64encode(setup_script.encode()).decode()
        
        # Create devbox with setup
        devbox = await client.devboxes.create_and_await_running(
            name=f"SWE-Gym-{instance_id}",
            launch_parameters=LaunchParameters(
                launch_commands=[
                    "echo 'Setting up SWE-Gym environment'",
                    f"echo '{setup_script_b64}' | base64 -d > /tmp/setup.sh",
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
        print(f"[INFO] Devbox created with ID: {devbox.id}")
        
        # Create snapshot
        print("[INFO] Creating snapshot...")
        snapshot = await client.devboxes.snapshot_disk(
            id=devbox.id,
            name=f"swegym-{instance_id}-snapshot",
            timeout=300
        )
        snapshot_id = snapshot.id
        print(f"[INFO] Snapshot created with ID: {snapshot_id}")
        
        # Shutdown devbox
        await client.devboxes.shutdown(id=devbox.id)
        print("[INFO] Devbox shut down")
    
    # Create scenario
    print("[INFO] Creating scenario...")
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
    print(f"[INFO] Scenario created with ID: {scenario.id}")
    
    # Save scenario details
    import json
    details = {
        "scenario_id": scenario.id,
        "instance_id": instance_id,
        "snapshot_id": snapshot_id,
        "repo": test_spec.repo,
        "version": test_spec.version,
        "base_commit": instance['base_commit'],
        "fail_to_pass": test_spec.FAIL_TO_PASS,
        "pass_to_pass": test_spec.PASS_TO_PASS,
    }
    
    with open(f"scenario_{instance_id}.json", "w") as f:
        json.dump(details, f, indent=2)
    print(f"[INFO] Scenario details saved to scenario_{instance_id}.json")
    
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