"""Build Runloop scenarios from SWE-Gym instances."""

from runloop_api_client import AsyncRunloop
from runloop_api_client.types import (
    InputContextParam,
    ScenarioEnvironment,
    ScoringContractParam,
)

from rl_sweagent.swegym.test_spec import TestSpec


async def create_swegym_scenario(
    client: AsyncRunloop, instance: dict, test_spec, use_snapshot: str = None
):
    """Create a Runloop scenario from a SWE-Gym instance

    Args:
        client: AsyncRunloop client
        instance: SWE-Gym instance dictionary
        test_spec: TestSpec object created from the instance
        use_snapshot: If provided, use this specific snapshot instead of creating new one
    """

    instance_id = instance["instance_id"]
    print(f"[INFO] Creating scenario for: {instance_id}")

    # We'll detect architecture after creating the devbox
    arch = "aarch64"  # Default, will be updated later

    # Generate base setup script (translated from _DOCKERFILE_BASE)
    base_setup_script = f"""#!/bin/bash
set -euxo pipefail

# Set environment variables
export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

# Install system dependencies (from Dockerfile)
sudo apt update && sudo apt install -y \\
    wget \\
    git \\
    build-essential \\
    libffi-dev \\
    libtiff-dev \\
    python3 \\
    python3-pip \\
    python-is-python3 \\
    jq \\
    curl \\
    locales \\
    locales-all \\
    tzdata

# Clean apt cache
sudo rm -rf /var/lib/apt/lists/*

# Download and install conda at /opt/miniconda3 (MUST use this path from Dockerfile)
wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_24.7.1-0-Linux-{arch}.sh' -O miniconda.sh
sudo bash miniconda.sh -b -p /opt/miniconda3
rm miniconda.sh

# Add conda to PATH
export PATH=/opt/miniconda3/bin:$PATH

# Initialize conda for all users
sudo /opt/miniconda3/bin/conda init --all

# Configure conda
/opt/miniconda3/bin/conda config --append channels conda-forge

# Add nonroot user (from Dockerfile)
sudo adduser --disabled-password --gecos 'dog' nonroot || true

# Create /testbed directory
sudo mkdir -p /testbed
sudo chmod 777 /testbed
"""

    # Generate environment setup script (will be written to /root/setup_env.sh)
    env_setup_script = f"""#!/bin/bash
set -euxo pipefail

# Source bashrc to get conda
source ~/.bashrc

# Run the test_spec environment setup
{test_spec.setup_env_script}
"""

    # Generate repository setup script (will be written to /root/setup_repo.sh)
    repo_setup_script = f"""#!/bin/bash
set -euxo pipefail

# Run the test_spec repository setup
{test_spec.install_repo_script}
"""

    # Generate scoring script (evaluation)
    scoring_script = f"""#!/bin/bash
set -eo pipefail

# Source conda from /opt/miniconda3 (as per Dockerfile)
source /opt/miniconda3/etc/profile.d/conda.sh

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

        # Create devbox
        devbox = await client.devboxes.create_and_await_running(
            name=f"SWE-Gym-{instance_id}",
            metadata={
                "instance_id": instance_id,
                "repo": test_spec.repo,
                "version": test_spec.version,
            },
        )
        print(f"[INFO] Devbox created with ID: {devbox.id}")

        # Detect architecture
        arch_result = await client.devboxes.execute_sync(
            id=devbox.id, command="uname -m"
        )
        arch = "aarch64" if "aarch64" in arch_result.stdout else "x86_64"
        print(f"[INFO] Detected architecture: {arch}")

        # Update base setup script with correct architecture
        base_setup_script = base_setup_script.replace("{arch}", arch)

        # Stage 1: Base setup (system packages + conda)
        print("[INFO] Stage 1: Running base setup...")
        await client.devboxes.write_file_contents(
            id=devbox.id, file_path="/tmp/base_setup.sh", contents=base_setup_script
        )

        result = await client.devboxes.execute_sync(
            id=devbox.id,
            command="chmod +x /tmp/base_setup.sh && bash /tmp/base_setup.sh",
            timeout=600000,  # 10 minutes
        )

        if result.exit_status != 0:
            print(f"[ERROR] Base setup failed with exit code: {result.exit_status}")
            if result.stderr:
                print(f"[ERROR] stderr: {result.stderr[-1000:]}")
            raise Exception("Base setup failed")

        print("[SUCCESS] Base setup completed!")

        # Stage 2: Environment setup (conda environment)
        print("[INFO] Stage 2: Running environment setup...")

        # Write setup_env.sh to /root/ (as per Dockerfile)
        await client.devboxes.execute_sync(id=devbox.id, command="sudo mkdir -p /root")

        await client.devboxes.write_file_contents(
            id=devbox.id, file_path="/tmp/setup_env.sh", contents=env_setup_script
        )

        await client.devboxes.execute_sync(
            id=devbox.id,
            command="sudo cp /tmp/setup_env.sh /root/setup_env.sh && sudo chmod +x /root/setup_env.sh",
        )

        # Run environment setup as per Dockerfile
        result = await client.devboxes.execute_sync(
            id=devbox.id,
            command='sudo /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"',
            timeout=600000,  # 10 minutes
        )

        if result.exit_status != 0:
            print(
                f"[ERROR] Environment setup failed with exit code: {result.exit_status}"
            )
            if result.stderr:
                print(f"[ERROR] stderr: {result.stderr[-1000:]}")
            raise Exception("Environment setup failed")

        print("[SUCCESS] Environment setup completed!")

        # Stage 3: Repository setup
        print("[INFO] Stage 3: Running repository setup...")

        # Write setup_repo.sh to /root/ (as per Dockerfile)
        await client.devboxes.write_file_contents(
            id=devbox.id, file_path="/tmp/setup_repo.sh", contents=repo_setup_script
        )

        await client.devboxes.execute_sync(
            id=devbox.id,
            command="sudo cp /tmp/setup_repo.sh /root/setup_repo.sh && sudo chmod +x /root/setup_repo.sh",
        )

        # Run repository setup as per Dockerfile
        result = await client.devboxes.execute_sync(
            id=devbox.id,
            command="sudo /bin/bash /root/setup_repo.sh",
            timeout=600000,  # 10 minutes
        )

        if result.exit_status != 0:
            print(
                f"[ERROR] Repository setup failed with exit code: {result.exit_status}"
            )
            if result.stderr:
                print(f"[ERROR] stderr: {result.stderr[-1000:]}")
            raise Exception("Repository setup failed")

        print("[SUCCESS] Repository setup completed!")

        # Final verification
        verify_result = await client.devboxes.execute_sync(
            id=devbox.id,
            command="ls -la /testbed/.git 2>&1 | head -3 && echo '---' && conda env list",
        )
        print("[INFO] Verification:")
        print(verify_result.stdout)

        # Create snapshot
        print("[INFO] Creating snapshot...")
        snapshot = await client.devboxes.snapshot_disk(
            id=devbox.id, name=f"swegym-{instance_id}-snapshot", timeout=300
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
            problem_statement=instance["problem_statement"],
            additional_context=format_additional_context(instance, test_spec),
        ),
        "scoring_contract": ScoringContractParam(
            scoring_function_parameters=[
                {
                    "name": "test_evaluation",
                    "scorer": {
                        "type": "bash_script_scorer",
                        "bash_script": scoring_script,
                    },
                    "weight": 1.0,
                }
            ]
        ),
        "environment_parameters": ScenarioEnvironment(
            snapshot_id=snapshot_id,
        ),
        "metadata": {
            "instance_id": instance_id,
            "repo": test_spec.repo,
            "version": test_spec.version,
            "base_commit": instance["base_commit"],
        },
        "reference_output": instance.get("patch", ""),  # Store the gold patch
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
        "base_commit": instance["base_commit"],
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
        fail_tests = "\n".join(f"- {t}" for t in test_spec.FAIL_TO_PASS)
        parts.append(f"\nTests to fix (FAIL_TO_PASS):\n{fail_tests}")

    if test_spec.PASS_TO_PASS:
        pass_tests = "\n".join(f"- {t}" for t in test_spec.PASS_TO_PASS)
        parts.append(f"\nTests to keep passing (PASS_TO_PASS):\n{pass_tests}")

    if instance.get("hints_text"):
        parts.append(f"\nHints: {instance['hints_text']}")

    return "\n".join(parts)
