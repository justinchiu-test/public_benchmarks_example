import asyncio
import json
import os
from pathlib import Path
from anthropic import AsyncAnthropic
from tqdm.asyncio import tqdm

from tools import SWEAGENT_TOOLS_RAW

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


TOOLS = []
for x in SWEAGENT_TOOLS_RAW:
    tool = x["function"].copy()
    tool["input_schema"] = tool.pop("parameters")
    TOOLS.append(tool)


async def analyze_mistakes_with_claude(messages, semaphore):
    """Send trajectory to Claude for mistake analysis."""
    async with semaphore:
        if messages[0]["role"] == "system":
            messages.pop(0)
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                tools=TOOLS,
                messages=[
                    dict(
                        role="user" if x["role"] == "tool" else x["role"],
                        content=x["content"],
                    )
                    for x in messages
                ]
                + [
                    {
                        "role": "user",
                        "content": """Analyze this failed trajectory and identify the key mistakes that led to a low score. Report on:
1. Inefficient bash usage
2. Lacking or incorrect testing
3. Mistakes in code repair
4. Missing edge cases

Please provide a concise analysis of the main mistakes.""",
                    }
                ],
            )
            return response.content[0].text
        except Exception as e:
            return f"Error analyzing trajectory: {str(e)}"


async def main():
    basedir = Path(
        "trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16"
    )
    semaphore = asyncio.Semaphore(32)

    tasks = []
    trajectories = []
    total_score = 0

    for exampledir in basedir.iterdir():
        print(list(exampledir.iterdir()))
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

        print(f"\n=== Analyzing trajectory in {exampledir.name} (score: {score}) ===")
        trajectories.append((exampledir, score, turns))
        total_score += score
        task = analyze_mistakes_with_claude(turns, semaphore)
        tasks.append((task, exampledir))

    print(
        f"\nTotal score: {total_score}/{len(trajectories)} = {total_score / len(trajectories):.3f}"
        if trajectories
        else "No trajectories found"
    )

    if tasks:
        print(f"\nAnalyzing {len(tasks)} trajectories with Claude...")
        task_list = [task for task, _ in tasks]
        exampledir_list = [exampledir for _, exampledir in tasks]

        results = await tqdm.gather(*task_list, desc="Processing Claude analyses")

        for result, exampledir in zip(results, exampledir_list):
            if isinstance(result, Exception):
                analysis = f"Error analyzing trajectory: {str(result)}"
                print(f"Error analyzing {exampledir.name}: {str(result)}")
            else:
                analysis = result

            print(f"Claude's Analysis for {exampledir.name}:\n{analysis}\n")
            print("=" * 80)

            with (exampledir / "claude_analysis.txt").open("w") as f:
                f.write(analysis)


if __name__ == "__main__":
    asyncio.run(main())
