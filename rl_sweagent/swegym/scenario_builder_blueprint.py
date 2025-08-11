"""Build Runloop scenarios from SWE-Gym instances from Xingyao's Docker Hub."""

import json
import os

import aiofiles
from runloop_api_client import AsyncRunloop
from runloop_api_client.lib.polling import PollingConfig
from runloop_api_client.types import (
    BlueprintView,
    InputContextParam,
    ScenarioEnvironment,
    ScoringContractParam,
)

from rl_sweagent.swegym.test_spec import TestSpec


async def find_existing_blueprint(
    client: AsyncRunloop,
    blueprint_name: str,
) -> BlueprintView | None:
    """Find an existing blueprint by name.

    Args:
        client: AsyncRunloop client
        blueprint_name: Name of the blueprint to find

    Returns:
        Existing blueprint object if found, None otherwise
    """
    blueprint_results = await client.blueprints.list(name=blueprint_name)

    if blueprint_results.blueprints:
        for blueprint in blueprint_results.blueprints:
            if blueprint.status != "failed":
                # make sure to wait for it to finish building
                print(f"Found existing blueprint {blueprint.name}: {blueprint.status}")
                await client.blueprint.await_build_complete(
                    blueprint.id,
                    polling_config=PollingConfig(interval_seconds=10, max_attempts=120),
                )
                return blueprint
    return None


async def delete_all_blueprints(
    client: AsyncRunloop,
    blueprint_name: str,
) -> int:
    """Delete all blueprints with the given name.

    Args:
        client: AsyncRunloop client
        blueprint_name: Name of the blueprints to delete

    Returns:
        Number of blueprints deleted
    """
    blueprint_results = await client.blueprints.list(name=blueprint_name)
    deleted_count = 0
    for blueprint in blueprint_results.blueprints:
        await client.blueprints.delete(blueprint.id)
        print(f"Deleted blueprint: {blueprint.id}")
        deleted_count += 1
    return deleted_count


async def create_blueprint(
    client: AsyncRunloop,
    blueprint_name: str,
    image_name: str,
    clear_existing: bool = False,
) -> BlueprintView:
    """Create a blueprint for a SWE-Gym instance.

    Args:
        client: AsyncRunloop client
        blueprint_name: Name for the blueprint
        image_name: Docker image name to use
        clear_existing: Whether to clear existing blueprints with same name

    Returns:
        Created blueprint object
    """
    print(f"[{blueprint_name}] Creating new blueprint...")

    # Determine architecture and launch parameters
    launch_params = {
        "resource_size_request": "CUSTOM_SIZE",
        "custom_cpu_cores": 4,
        "custom_gb_memory": 32,
        "architecture": "x86_64",  # All of xingyao's images are x86 now
        "user_parameters": dict(username="root", uid=0),  # For permissions
    }

    print(f"[{blueprint_name}] Using x86_64 architecture (xingyao default)")

    # Clear existing blueprints with same name if requested
    if clear_existing:
        deleted_count = await delete_all_blueprints(client, blueprint_name)
        if deleted_count > 0:
            print(
                f"Cleared {deleted_count} existing blueprint(s) with name: {blueprint_name}"
            )

    # Create new blueprint
    blueprint = await client.blueprints.create_and_await_build_complete(
        name=blueprint_name,
        launch_parameters=launch_params,
        dockerfile=f"""FROM {image_name}""",
        polling_config=PollingConfig(interval_seconds=5, max_attempts=120),
    )
    print(f"[{blueprint_name}] Blueprint created with ID: {blueprint.id}")

    return blueprint


async def create_scenario(
    client: AsyncRunloop,
    instance: dict,
    test_spec: TestSpec,
    blueprint_id: str,
) -> object:
    """Create a scenario for a SWE-Gym instance.

    Args:
        client: AsyncRunloop client
        instance: SWE-Gym instance dictionary
        test_spec: TestSpec object created from the instance
        blueprint_id: ID of the blueprint to use

    Returns:
        Created scenario object
    """
    instance_id = instance["instance_id"]
    print(f"[{instance_id}] Creating scenario...")

    # Generate scoring script (evaluation)
    scoring_script = "echo 1"

    # Create scenario configuration
    scenario_config = {
        "name": f"swegym-{instance_id}",
        "input_context": InputContextParam(
            problem_statement="dummy",
            # problem_statement=instance["problem_statement"],
            # additional_context=format_additional_context(instance, test_spec),
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
            blueprint_id=blueprint_id,
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

    return scenario


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
    test_spec: TestSpec,
    overwrite_blueprint: bool,
    benchmark_name: str = "swegym",
):
    """Create a Runloop scenario from a SWE-Gym instance

    Args:
        client: AsyncRunloop client
        instance: SWE-Gym instance dictionary
        test_spec: TestSpec object created from the instance
        benchmark_name: Name of the benchmark for organizing logs
        overwrite_blueprint: If True, delete existing blueprint and create new one.
            If False, reuse existing blueprint or create if not found.
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
    blueprint_name = f"SWE-Gym-{instance_id}"

    # Handle blueprint based on overwrite_blueprint flag
    if overwrite_blueprint:
        # Clear existing and create new blueprint
        print(f"[{instance_id}] Overwriting blueprint (overwrite_blueprint=True)")
        blueprint = await create_blueprint(
            client, blueprint_name, image_name, clear_existing=True
        )
    else:
        # Try to find existing blueprint first
        print(
            f"[{instance_id}] Checking for existing blueprint (overwrite_blueprint=False)"
        )
        blueprint = await find_existing_blueprint(client, blueprint_name)

        if blueprint:
            print(f"[{instance_id}] Using existing blueprint with ID: {blueprint.id}")
        else:
            print(f"[{instance_id}] No existing blueprint found, creating new one")
            blueprint = await create_blueprint(
                client,
                blueprint_name,
                image_name,
                clear_existing=True,
            )
    if instance_id == "pandas-dev__pandas-54002":
        import pdb

        pdb.set_trace()

    devbox = await client.devboxes.create_and_await_running(
        blueprint_name=blueprint_name
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
    print(f"[{instance_id}] Devbox shut down")

    # Create scenario using helper function
    scenario = await create_scenario(client, instance, test_spec, blueprint.id)

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
