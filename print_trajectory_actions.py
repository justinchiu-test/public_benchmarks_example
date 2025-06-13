import json
from pathlib import Path

path = Path("trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16/914210/914210.traj")
path = Path("trajectories/bmr_308GDsPUn0YWiGBi4npNO/claude-sonnet-4-20250514/914210/914210.traj")


with path.open("r") as f:
    traj = json.load(f)

for turn in traj["trajectory"]:
    print(turn["action"].split("\n")[0])
