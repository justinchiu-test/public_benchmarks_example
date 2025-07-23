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
    print(f"[{instance_id}] Creating scenario")

    # We'll detect architecture after creating the devbox
    arch = "aarch64"  # Default, will be updated later

    # Generate base setup script (translated from _DOCKERFILE_BASE)
    base_setup_script = f"""#!/bin/bash
set -euxo pipefail

# Clean Python environment variables that might conflict
unset PYTHONPATH
unset PYTHONHOME

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
wget 'https://repo.anaconda.com/miniconda/Miniconda3-py312_24.7.1-0-Linux-{arch}.sh' -O miniconda.sh
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
# Don't use -e flag to match eval script behavior
set -xo pipefail

# Clean environment before running eval script
unset PYTHONPATH
unset PYTHONHOME

# Run evaluation (eval script will handle conda activation)
{test_spec.eval_script}

# Capture the exit code
EVAL_EXIT_CODE=$?

# Return score based on exit code
if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo "1.0"
else
    echo "0.0"
fi

# Exit with success so Runloop knows the scoring script ran
exit 0
"""

    # Create or reuse snapshot
    if use_snapshot:
        snapshot_id = use_snapshot
        print(f"[{instance_id}] Using existing snapshot: {snapshot_id}")
    else:
        print(f"[{instance_id}] Creating new devbox...")

        # Create devbox
        devbox = await client.devboxes.create_and_await_running(
            name=f"SWE-Gym-{instance_id}",
            metadata={
                "instance_id": instance_id,
                "repo": test_spec.repo,
                "version": test_spec.version,
            },
        )
        print(f"[{instance_id}] Devbox created with ID: {devbox.id}")

        # Detect architecture
        arch_result = await client.devboxes.execute_sync(
            id=devbox.id, command="uname -m"
        )
        arch = "aarch64" if "aarch64" in arch_result.stdout else "x86_64"
        print(f"[{instance_id}] Detected architecture: {arch}")

        # Update base setup script with correct architecture
        base_setup_script = base_setup_script.replace("{arch}", arch)

        # Stage 1: Base setup (system packages + conda)
        print(f"[{instance_id}] Stage 1: Running base setup...")
        await client.devboxes.write_file_contents(
            id=devbox.id, file_path="/tmp/base_setup.sh", contents=base_setup_script
        )

        result = await client.devboxes.execute_sync(
            id=devbox.id,
            command="chmod +x /tmp/base_setup.sh && bash /tmp/base_setup.sh",
            timeout=600000,  # 10 minutes
        )

        if result.exit_status != 0:
            print(
                f"[{instance_id}] ERROR: Base setup failed with exit code: {result.exit_status}"
            )
            if result.stderr:
                print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
            raise Exception("Base setup failed")

        print(f"[{instance_id}] SUCCESS: Base setup completed!")

        # Stage 2: Environment setup (conda environment)
        print(f"[{instance_id}] Stage 2: Running environment setup...")

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
                f"[{instance_id}] ERROR: Environment setup failed with exit code: {result.exit_status}"
            )
            if result.stderr:
                print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
            raise Exception("Environment setup failed")

        print(f"[{instance_id}] SUCCESS: Environment setup completed!")

        # Stage 3: Repository setup
        print(f"[{instance_id}] Stage 3: Running repository setup...")

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
                f"[{instance_id}] ERROR: Repository setup failed with exit code: {result.exit_status}"
            )
            if result.stderr:
                print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
            raise Exception("Repository setup failed")

        print(f"[{instance_id}] SUCCESS: Repository setup completed!")

        # Comprehensive verification
        print(f"[{instance_id}] Running comprehensive verification...")

        verification_commands = [
            # Check repository
            ("cd /testbed && pwd", "Repository exists"),
            ("cd /testbed && git status --short", "Git status clean"),
            ("cd /testbed && git log --oneline -1", "Git history"),
            ("cd /testbed && git remote -v || echo 'No remotes'", "Git remotes"),
            # Check conda environment
            (
                "source /opt/miniconda3/bin/activate && conda env list",
                "Conda environments",
            ),
            (
                "source /opt/miniconda3/bin/activate && conda activate testbed && which python",
                "Python location",
            ),
            (
                "source /opt/miniconda3/bin/activate && conda activate testbed && python --version",
                "Python version",
            ),
            # Check package installed (try to import the main package)
            (
                "source /opt/miniconda3/bin/activate && conda activate testbed && python -c 'import sys; print(sys.path[0])'",
                "Python path",
            ),
            # Check test files exist
            ("find /testbed -name 'test_*.py' -type f | wc -l", "Test files count"),
            # Check permissions
            ("stat -c '%U:%G %a' /testbed", "Repository permissions"),
            # Show testbed directory structure
            ("ls -la /testbed | head -10", "Testbed directory"),
        ]

        all_passed = True
        for cmd, description in verification_commands:
            result = await client.devboxes.execute_sync(
                id=devbox.id, command=cmd, timeout=30000
            )
            if result.exit_status != 0:
                print(
                    f"[{instance_id}] ❌ {description}: FAILED (exit code: {result.exit_status})"
                )
                if result.stderr:
                    print(f"[{instance_id}]    stderr: {result.stderr.strip()}")
                all_passed = False
            else:
                # Get first line of output
                output = result.stdout.strip().split("\n")[0] if result.stdout else "OK"
                print(f"[{instance_id}] ✓ {description}: {output}")

        if not all_passed:
            print(f"[{instance_id}] WARNING: Some verification checks failed!")

        # Create snapshot
        print(f"[{instance_id}] Creating snapshot...")
        snapshot = await client.devboxes.snapshot_disk(
            id=devbox.id, name=f"swegym-{instance_id}-snapshot", timeout=300
        )
        snapshot_id = snapshot.id
        print(f"[{instance_id}] Snapshot created with ID: {snapshot_id}")

        # Shutdown devbox
        # await client.devboxes.shutdown(id=devbox.id)
        # print(f"[{instance_id}] Devbox shut down")

    # Create scenario
    print(f"[{instance_id}] Creating scenario...")
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
    print(f"[{instance_id}] Scenario created with ID: {scenario.id}")

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
    print(f"[{instance_id}] Scenario details saved to scenario_{instance_id}.json")

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
