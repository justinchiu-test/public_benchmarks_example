"""Build Runloop scenarios from SWE-Gym instances from Xingyao's Docker Hub."""

import json
import os

import aiofiles
from runloop_api_client import AsyncRunloop
from runloop_api_client.types import (
    InputContextParam,
    ScenarioEnvironment,
    ScoringContractParam,
)

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

    instance_id_with_typo = test_spec.instance_id.replace("__", "_s_")
    image_name = f"xingyaoww/sweb.eval.x86_64.{instance_id_with_typo}"

    # Create new blueprint
    print(f"[{instance_id}] Creating new blueprint...")

    # Determine architecture based on USE_X86 list
    launch_params = {
        "resource_size_request": "CUSTOM_SIZE",
        "custom_cpu_cores": 4,
        "custom_gb_memory": 32,
    }

    # i think all of xingyao's images are x86 now?
    launch_params["architecture"] = "x86_64"
    print(f"[{instance_id}] Using x86_64 architecture (xingyao default)")
    """
    if instance_id in USE_X86:
        launch_params["architecture"] = "x86_64"
        print(f"[{instance_id}] Using x86_64 architecture (instance in USE_X86 list)")
    else:
        # Default to arm64 if not in USE_X86 list
        launch_params["architecture"] = "arm64"
        print(f"[{instance_id}] Using arm64 architecture (default)")
    """

    # for permissions...
    # launch_params["user_parameters"] = dict(username="root", uid=0)

    # Create blueprint
    blueprint = await client.blueprints.create_and_await_build_complete(
        name=f"SWE-Gym-{instance_id}",
        launch_parameters=launch_params,
        dockerfile=f"""FROM {image_name}""",
        # Add nonroot user (from Dockerfile)
        # sudo adduser --disabled-password --gecos 'dog' nonroot || true""",
    )
    print(f"[{instance_id}] Blueprint created with ID: {blueprint.id}")

    blueprint_results = await client.blueprints.list(name="my_blueprint_name")
    for blueprint in blueprint_results.blueprints:
        print(blueprint)

    # do we need to wait until blueprint gets provisioned?
    devbox = await client.devboxes.create_and_await_running(
        blueprint_name=f"SWE-Gym-{instance_id}"
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

    # Shutdown devbox
    await client.devboxes.shutdown(id=devbox.id)
    # print(f"[{instance_id}] Devbox shut down")
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
            blueprint_id=blueprint.id,
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
        "blueprint_id": blueprint.id,
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
