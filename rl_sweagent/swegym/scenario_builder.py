"""Build Runloop scenarios from SWE-Gym instances."""

import json
import os

import aiofiles
from runloop_api_client import AsyncRunloop
from runloop_api_client.types import (
    InputContextParam,
    ScenarioEnvironment,
    ScoringContractParam,
)

from rl_sweagent.swegym.constants import USE_X86
from rl_sweagent.swegym.test_spec import TestSpec


async def save_command_logs(
    instance_id: str, command_logs: list, benchmark_name: str = "swegym"
):
    """Save command execution logs to a JSON file in logs/{benchmark}/{instance_id}/"""
    log_dir = os.path.join("logs", benchmark_name, instance_id)
    os.makedirs(log_dir, exist_ok=True)

    filename = os.path.join(log_dir, "scenario_creation_logs.json")
    async with aiofiles.open(filename, mode="w") as f:
        await f.write(json.dumps(command_logs, indent=2))
    print(f"[{instance_id}] Command logs saved to {filename}")


async def create_swegym_scenario(
    client: AsyncRunloop,
    instance: dict,
    test_spec,
    benchmark_name: str = "swegym",
    debug_mode: bool = False,
):
    """Create a Runloop scenario from a SWE-Gym instance

    Args:
        client: AsyncRunloop client
        instance: SWE-Gym instance dictionary
        test_spec: TestSpec object created from the instance
        benchmark_name: Name of the benchmark for organizing logs
        debug_mode: If True, keeps failed devboxes running for debugging
    """

    instance_id = instance["instance_id"]
    print(f"[{instance_id}] Creating scenario")

    # Track all command executions for debugging
    command_logs = []

    # Save test spec details
    log_dir = os.path.join("logs", benchmark_name, instance_id)
    os.makedirs(log_dir, exist_ok=True)

    test_spec_file = os.path.join(log_dir, "test_spec.json")
    test_spec_data = {
        "instance_id": test_spec.instance_id,
        "repo": test_spec.repo,
        "version": test_spec.version,
        "arch": test_spec.arch,
        "FAIL_TO_PASS": test_spec.FAIL_TO_PASS,
        "PASS_TO_PASS": test_spec.PASS_TO_PASS,
        "repo_script_list": test_spec.repo_script_list,
        "eval_script_list": test_spec.eval_script_list,
        "env_script_list": test_spec.env_script_list,
        "setup_env_script": test_spec.setup_env_script,
        "install_repo_script": test_spec.install_repo_script,
        "eval_script": test_spec.eval_script,
    }

    with open(test_spec_file, "w") as f:
        json.dump(test_spec_data, f, indent=2)
    print(f"[{instance_id}] Test spec saved to {test_spec_file}")

    # Generate base setup script (translated from _DOCKERFILE_BASE)
    base_setup_script = """#!/bin/bash
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

# Run the test_spec environment setup (which will create the conda environment)
{test_spec.setup_env_script}

# Now that the environment is created, set up bashrc for future sessions
echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" > /root/.bashrc
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

    # Create new devbox
    print(f"[{instance_id}] Creating new devbox...")

    # Determine architecture based on USE_X86 list
    launch_params = {
        "resource_size_request": "CUSTOM_SIZE",
        "custom_cpu_cores": 4,
        "custom_gb_memory": 32,
    }
    if instance_id in USE_X86:
        launch_params["architecture"] = "x86_64"
        print(f"[{instance_id}] Using x86_64 architecture (instance in USE_X86 list)")
    else:
        # Default to arm64 if not in USE_X86 list
        launch_params["architecture"] = "arm64"
        print(f"[{instance_id}] Using arm64 architecture (default)")

    # Create devbox
    devbox = await client.devboxes.create_and_await_running(
        name=f"SWE-Gym-{instance_id}",
        launch_parameters=launch_params,
        metadata={
            "instance_id": instance_id,
            "repo": test_spec.repo,
            "version": test_spec.version,
        },
    )
    print(f"[{instance_id}] Devbox created with ID: {devbox.id}")

    # Detect architecture
    arch_result = await client.devboxes.execute_sync(id=devbox.id, command="uname -m")
    arch = "aarch64" if "aarch64" in arch_result.stdout else "x86_64"
    print(f"[{instance_id}] Detected architecture: {arch}")

    # Log command execution
    command_logs.append(
        {
            "stage": "architecture_detection",
            "command": "uname -m",
            "exit_status": arch_result.exit_status,
            "stdout": arch_result.stdout,
            "stderr": arch_result.stderr,
        }
    )

    # Update base setup script with correct architecture
    # Map uname -m output to conda architecture names
    conda_arch = "aarch64" if arch == "aarch64" else "x86_64"
    base_setup_script = base_setup_script.format(arch=conda_arch)

    # Stage 1: Base setup (system packages + conda)
    print(f"[{instance_id}] Stage 1: Running base setup...")
    await client.devboxes.write_file_contents(
        id=devbox.id, file_path="/tmp/base_setup.sh", contents=base_setup_script
    )

    result = await client.devboxes.execute_sync(
        id=devbox.id,
        command="chmod +x /tmp/base_setup.sh && bash /tmp/base_setup.sh",
        timeout=1800,  # 30 minutes
    )

    # Log command execution
    command_logs.append(
        {
            "stage": "base_setup",
            "command": "chmod +x /tmp/base_setup.sh && bash /tmp/base_setup.sh",
            "exit_status": result.exit_status,
            "stdout": result.stdout if result.stdout else "",  # Full output
            "stderr": result.stderr if result.stderr else "",
        }
    )

    if result.exit_status != 0:
        print(
            f"[{instance_id}] ERROR: Base setup failed with exit code: {result.exit_status}"
        )
        if result.stderr:
            print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
        # Save logs before raising exception
        await save_command_logs(instance_id, command_logs, benchmark_name)
        error = Exception("Base setup failed")
        error.devbox_id = devbox.id
        raise error

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
        timeout=1800,  # 30 minutes
    )

    # Log command execution
    command_logs.append(
        {
            "stage": "environment_setup",
            "command": 'sudo /bin/bash -c "source ~/.bashrc && /root/setup_env.sh"',
            "exit_status": result.exit_status,
            "stdout": result.stdout if result.stdout else "",
            "stderr": result.stderr if result.stderr else "",
        }
    )

    if result.exit_status != 0:
        print(
            f"[{instance_id}] ERROR: Environment setup failed with exit code: {result.exit_status}"
        )
        if result.stderr:
            print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
        # Save logs before raising exception
        await save_command_logs(instance_id, command_logs, benchmark_name)
        error = Exception("Environment setup failed")
        error.devbox_id = devbox.id
        raise error

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
        timeout=1800,  # 30 minutes
    )

    # Log command execution
    command_logs.append(
        {
            "stage": "repository_setup",
            "command": "sudo /bin/bash /root/setup_repo.sh",
            "exit_status": result.exit_status,
            "stdout": result.stdout if result.stdout else "",
            "stderr": result.stderr if result.stderr else "",
        }
    )

    if result.exit_status != 0:
        print(
            f"[{instance_id}] ERROR: Repository setup failed with exit code: {result.exit_status}"
        )
        if result.stderr:
            print(f"[{instance_id}] ERROR stderr: {result.stderr[-1000:]}")
        # Save logs before raising exception
        await save_command_logs(instance_id, command_logs, benchmark_name)
        error = Exception("Repository setup failed")
        error.devbox_id = devbox.id
        raise error

    print(f"[{instance_id}] SUCCESS: Repository setup completed!")

    # Fix permissions on /testbed to ensure patches can be applied
    print(f"[{instance_id}] Fixing file permissions...")
    perm_result = await client.devboxes.execute_sync(
        id=devbox.id,
        command="sudo chmod -R 755 /testbed && sudo chown -R $(whoami):$(whoami) /testbed && sudo chmod -R u+w /testbed",
        timeout=300,
    )
    if perm_result.exit_status != 0:
        print(
            f"[{instance_id}] WARNING: Failed to fix permissions: {perm_result.stderr}"
        )
    else:
        print(f"[{instance_id}] Permissions fixed successfully")

    # Log permission fix
    command_logs.append(
        {
            "stage": "fix_permissions",
            "command": "sudo chmod -R 755 /testbed && sudo chown -R $(whoami):$(whoami) /testbed && sudo chmod -R u+w /testbed",
            "exit_status": perm_result.exit_status,
            "stdout": perm_result.stdout if perm_result.stdout else "",
            "stderr": perm_result.stderr if perm_result.stderr else "",
        }
    )

    # Comprehensive verification
    print(f"[{instance_id}] Running comprehensive verification...")

    verification_commands = [
        # Check repository
        ("cd /testbed && pwd", "Repository exists"),
        ("git config --global --add safe.directory /testbed", "Git safe directory"),
        ("cd /testbed && git status --short", "Git status clean"),
        ("cd /testbed && git log --oneline -1", "Git history"),
        ("cd /testbed && git remote -v || echo 'No remotes'", "Git remotes"),
        # Check conda environment
        (
            "unset PYTHONPATH && source /opt/miniconda3/bin/activate && conda env list",
            "Conda environments",
        ),
        (
            "source /opt/miniconda3/bin/activate && conda activate testbed && echo 'PYTHONPATH='$PYTHONPATH && echo 'PYTHONHOME='$PYTHONHOME && echo 'LD_LIBRARY_PATH='$LD_LIBRARY_PATH && which python",
            "Python location and env vars",
        ),
        (
            "source /opt/miniconda3/bin/activate && conda activate testbed && unset PYTHONPATH && unset PYTHONHOME && python --version",
            "Python version",
        ),
        # Check package installed (try to import the main package)
        (
            "source /opt/miniconda3/bin/activate && conda activate testbed && unset PYTHONPATH && unset PYTHONHOME && python -c 'import sys; print(sys.path[0])'",
            "Python path",
        ),
        # Check test files exist
        ("find /testbed -name 'test_*.py' -type f | wc -l", "Test files count"),
        # Environment diagnostics
        (
            "env | grep -E '^(PYTHON|LD_LIBRARY|PATH)' | sort",
            "Environment variables",
        ),
        # Check permissions
        ("stat -c '%U:%G %a' /testbed", "Repository permissions"),
        # Show testbed directory structure
        ("ls -la /testbed | head -10", "Testbed directory"),
        # Verify write permissions
        (
            "touch /testbed/test_write_permission && rm -f /testbed/test_write_permission && echo 'Write test passed'",
            "Write permissions",
        ),
    ]

    all_passed = True
    verification_logs = []
    for cmd, description in verification_commands:
        result = await client.devboxes.execute_sync(
            id=devbox.id, command=cmd, timeout=1800
        )

        # Log verification command
        verification_logs.append(
            {
                "description": description,
                "command": cmd,
                "exit_status": result.exit_status,
                "stdout": result.stdout if result.stdout else "",
                "stderr": result.stderr if result.stderr else "",
            }
        )

        if result.exit_status != 0:
            print(
                f"[{instance_id}] ❌ {description}: FAILED (exit code: {result.exit_status})"
            )
            if result.stderr:
                print(f"[{instance_id}]    stderr: {result.stderr.strip()}")
            all_passed = False
        else:
            output = result.stdout.strip() if result.stdout else "OK"
            print(f"[{instance_id}] ✓ {description}: {output}")

    # Add verification logs to command logs
    command_logs.append(
        {
            "stage": "verification",
            "commands": verification_logs,
            "all_passed": all_passed,
        }
    )

    if not all_passed:
        print(f"[{instance_id}] WARNING: Some verification checks failed!")

    # Create snapshot
    print(f"[{instance_id}] Creating snapshot...")
    snapshot = await client.devboxes.snapshot_disk(
        id=devbox.id, name=f"swegym-{instance_id}-snapshot", timeout=1800
    )
    snapshot_id = snapshot.id
    print(f"[{instance_id}] Snapshot created with ID: {snapshot_id}")

    # Shutdown devbox
    await client.devboxes.shutdown(id=devbox.id)
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

    # Save to logs directory
    log_dir = os.path.join("logs", benchmark_name, instance_id)
    os.makedirs(log_dir, exist_ok=True)

    scenario_file = os.path.join(log_dir, "scenario_details.json")
    with open(scenario_file, "w") as f:
        json.dump(details, f, indent=2)
    print(f"[{instance_id}] Scenario details saved to {scenario_file}")

    # Save command logs
    await save_command_logs(instance_id, command_logs, benchmark_name)

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
