import json
import os
import re
from pathlib import Path
from anthropic import Anthropic
from tqdm import tqdm

from rl_sweagent.tools import SWEAGENT_TOOLS_RAW

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


TOOLS = []
for x in SWEAGENT_TOOLS_RAW:
    tool = x["function"].copy()
    tool["input_schema"] = tool.pop("parameters")
    TOOLS.append(tool)


def analyze_mistakes_with_claude(messages):
    """Send trajectory to Claude for mistake analysis."""
    if messages[0]["role"] == "system":
        messages.pop(0)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            tools=TOOLS,
            messages=[
                dict(
                    role="user" if x["role"] == "tool" else x["role"],
                    content=x["content"] if x["content"] != "" else "No content, only tool call",
                )
                for x in messages
            ]
            + [
                {
                    "role": "user",
                    "content": """Analyze this trajectory and return a JSON object with two parts:

1. **Success Prediction**: Based on the trajectory, predict whether this was likely successful or not
2. **Mistake Analysis**: Identify which mistake types are present (if any)

**Mistake Categories:**
1. **no_post_fix_verification** - Failed to run reproduction scripts after implementing fixes
2. **incomplete_fix_implementation** - Addressing only part of the problem or introducing new bugs  
3. **missing_edge_cases** - Not considering all code paths or scenarios
4. **poor_file_management** - Leaving test files, not cleaning up, or environment issues
5. **inadequate_reproduction** - Not properly demonstrating the issue exists
6. **inefficient_bash_usage** - Excessive file exploration, redundant commands, or wrong tools
7. **over_engineering** - Creating complex fixes when simple ones would work
8. **missing_integration_testing** - Not testing within the actual framework/system context
9. **incorrect_problem_understanding** - Misinterpreting what needs to be fixed
10. **failed_to_follow_instructions** - Not following explicit requirements or task instructions
11. **dependency_environment_issues** - Problems with package installation, imports, or environment setup
12. **malformed_tool_calls** - Incorrect tool usage, syntax errors in tool parameters, or broken tool invocations
13. **empty_prompts** - Using empty, null, or meaningless prompts that don't provide useful information

**Response Format:**
Return an analysis of the misatkes, and then a valid JSON object:
```json
{
  "predicted_success": true/false,
  "confidence": "high/medium/low",
  "no_post_fix_verification": true/false,
  "incomplete_fix_implementation": true/false,
  "missing_edge_cases": true/false,
  "poor_file_management": true/false,
  "inadequate_reproduction": true/false,
  "inefficient_bash_usage": true/false,
  "over_engineering": true/false,
  "missing_integration_testing": true/false,
  "incorrect_problem_understanding": true/false,
  "failed_to_follow_instructions": true/false,
  "dependency_environment_issues": true/false,
  "malformed_tool_calls": true/false,
  "empty_prompts": true/false
}
```""",
                }
            ],
        )
        return response.content[0].text
    except Exception as e:
        return f"Error analyzing trajectory: {str(e)}"


def main():
    basedir = Path(
        #"trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16" # i think this one is swe-verified
        #"trajectories/bmr_30E9pubjh5nUCg3RXgfN8/openai/c3-111b-code-sft-souwe4re-fp16-vllm" # 131/356???
        #"trajectories/bmr_30ELK7vPvQtw35dT0Nq6K/openai/c3-111b-code-sft-souwe4re-fp16-vllm" # 130/355??
        #"trajectories/bmr_30EVU63rKBHb9kK5n2pVx/openai/c3-111b-code-sft-souwe4re-fp16-vllm" # 143/351
        #"trajectories/bmr_30EsdNYc79kYThT0n1KAw/openai/c3-111b-code-sft-souwe4re-fp16-vllm" # 138/354
        #"trajectories/bmr_30EsdSVxuSp65kXqeFYpA/openai/c3-111b-code-sft-souwe4re-fp16-vllm" # 130/353
        #"trajectories/bmr_30DgR3vdfdhLwoH0tF4sI/deepseek/deepseek-chat" # 119/355
        #"trajectories/bmr_30FfKreLUBJqRJk484VPB/deepseek/deepseek-chat" # 130/355
        #"trajectories/scoped-fast-sample-SWE-bench/SWE-smith-2025-06-25-03-36-18/openai/c3-111b-code-sft-souwe4re-fp16-vllm"
        #"trajectories/scoped-fast-sample-SWE-bench/SWE-smith-2025-06-25-13-22-52/claude-sonnet-4-20250514"
        # full swesmith, but temperature 1 results in bad trajecotires. likely due to undertraining
        #"trajectories/SWE-bench/SWE-smith-2025-06-26-05-15-47/openai/c3-111b-code-sft-souwe4re-fp16-vllm"
        # full swesmith greedy?
        #"trajectories/SWE-bench/SWE-smith-2025-06-27-19-24-13/openai/c3-111b-code-sft-souwe4re-fp16-vllm"
        #"trajectories/princeton-nlp/SWE-bench_Verified-2025-07-02-17-19-25/rawco/c3-111b-code-sft-souwe4re-fp16-vllm/"
        #"trajectories/princeton-nlp/SWE-bench_Verified-2025-07-03-18-10-44/rawco/c3-sweep-ecsydrkq-690h-fp16"
        #"trajectories/princeton-nlp/SWE-bench_Verified-2025-07-04-00-29-22/co/c3-sweep-ecsydrkq-690h-fp16"
        # swesmith
        "trajectories/swesmith-nonempty-SWE-bench/SWE-smith-2025-07-06-21-56-58/co/c3-sweep-ecsydrkq-690h-fp16"
        #"trajectories/swesmith-nonempty-SWE-bench/SWE-smith-2025-07-06-21-39-06/deepseek/deepseek-chat"
        #"trajectories/swesmith-nonempty-SWE-bench/SWE-smith-2025-07-06-21-41-52/claude-sonnet-4-20250514/"
    )

    trajectories = []
    total_score = 0

    for exampledir in basedir.iterdir():
        with (exampledir / "score.json").open("r") as f:
            score = json.load(f)["score"]
        traj_data = None
        for traj_file in exampledir.glob("*.traj"):
            with traj_file.open("r") as f:
                try:
                    traj_data = json.load(f)
                    break
                except json.JSONDecodeError:
                    print(f"Skipping empty or invalid trajectory file: {traj_file}")
                    continue

        if traj_data is None:
            print(f"No valid trajectory file found in {exampledir.name}")
            continue

        turns = traj_data["history"]

        #print(f"\n=== Analyzing trajectory in {exampledir.name} (score: {score}) ===")
        trajectories.append((exampledir, score, turns))
        total_score += score

    print(
        f"\nTotal score: {total_score}/{len(trajectories)} = {total_score / len(trajectories):.3f}"
        if trajectories
        else "No trajectories found"
    )
    import pdb; pdb.set_trace()

    if trajectories:
        print(f"\nAnalyzing {len(trajectories)} trajectories with Claude...")

        # Initialize error counts
        error_counts = {
            "no_post_fix_verification": 0,
            "incomplete_fix_implementation": 0,
            "missing_edge_cases": 0,
            "poor_file_management": 0,
            "inadequate_reproduction": 0,
            "inefficient_bash_usage": 0,
            "over_engineering": 0,
            "missing_integration_testing": 0,
            "incorrect_problem_understanding": 0,
            "failed_to_follow_instructions": 0,
            "dependency_environment_issues": 0,
            "malformed_tool_calls": 0,
            "empty_prompts": 0,
        }

        total_mistakes_found = 0
        correct_predictions = 0
        total_predictions = 0

        for i, (exampledir, score, turns) in enumerate(tqdm(
            trajectories, desc="Processing Claude analyses"
        ), 1):
            analysis = analyze_mistakes_with_claude(turns)

            print(f"Claude's Analysis for {exampledir.name}:\n{analysis}\n")
            print("=" * 80)

            with (exampledir / "claude_analysis.txt").open("w") as f:
                f.write(analysis)

            # Try to parse as JSON and save
            try:
                # First try to extract JSON from markdown code blocks
                json_match = re.search(r"```json\s*\n(.*?)\n```", analysis, re.DOTALL)
                if json_match:
                    json_text = json_match.group(1)
                else:
                    json_text = analysis

                analysis_json = json.loads(json_text)
                with (exampledir / "error_analysis.json").open("w") as f:
                    json.dump(analysis_json, f, indent=2)

                # Count errors
                trajectory_mistakes = 0
                trajectory_mistake_types = []
                for error_type, is_present in analysis_json.items():
                    if error_type in error_counts and is_present:
                        error_counts[error_type] += 1
                        trajectory_mistakes += 1
                        trajectory_mistake_types.append(error_type)

                total_mistakes_found += trajectory_mistakes

                # Check prediction accuracy
                predicted_success = analysis_json.get("predicted_success", None)
                confidence = analysis_json.get("confidence", "unknown")
                actual_success = score > 0

                if predicted_success is not None:
                    total_predictions += 1
                    if predicted_success == actual_success:
                        correct_predictions += 1
                        prediction_status = "✓"
                    else:
                        prediction_status = "✗"

                    print(f"[{i}/{len(trajectories)}] Trajectory {exampledir.name} (Score: {score})")
                    print(f"  Predicted: {'Success' if predicted_success else 'Failure'} ({confidence} confidence) {prediction_status}")
                    print(f"  Actual: {'Success' if actual_success else 'Failure'}")
                    print(f"  Mistakes found: {trajectory_mistakes} (Total: {total_mistakes_found})")
                else:
                    print(f"[{i}/{len(trajectories)}] Trajectory {exampledir.name} (Score: {score})")
                    print(f"  Prediction: N/A")
                    print(f"  Mistakes found: {trajectory_mistakes} (Total: {total_mistakes_found})")

                # Print running mistake type counts
                if trajectory_mistake_types:
                    print(f"  Mistake types found: {', '.join(trajectory_mistake_types)}")
                print(f"  Running totals: ", end="")
                active_counts = [(k, v) for k, v in error_counts.items() if v > 0]
                if active_counts:
                    count_strs = [f"{k}: {v}" for k, v in sorted(active_counts, key=lambda x: x[1], reverse=True)]
                    print(", ".join(count_strs))
                else:
                    print("No mistakes found yet")

                if total_predictions > 0:
                    accuracy = (correct_predictions / total_predictions) * 100
                    print(f"  Prediction accuracy so far: {correct_predictions}/{total_predictions} ({accuracy:.1f}%)")
                print()

            except json.JSONDecodeError:
                print(f"Warning: Could not parse JSON for {exampledir.name}")

        # Print summary statistics
        total_trajectories = len(trajectories)
        print(f"\n{'=' * 60}")
        print(f"SUMMARY ACROSS {total_trajectories} TRAJECTORIES")
        print(f"{'=' * 60}")

        # Prediction accuracy summary
        if total_predictions > 0:
            final_accuracy = (correct_predictions / total_predictions) * 100
            print(f"PREDICTION ACCURACY: {correct_predictions}/{total_predictions} ({final_accuracy:.1f}%)")
            print()

        # Error summary
        print("ERROR BREAKDOWN:")
        for error_type, count in sorted(
            error_counts.items(), key=lambda x: x[1], reverse=True
        ):
            percentage = (count / total_trajectories) * 100
            print(f"{error_type:<35}: {count:3d} ({percentage:5.1f}%)")

        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
