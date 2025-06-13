import json
from pathlib import Path

path = Path("trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16/914210/914210.traj")
path = Path("trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16/914210/914210.traj")
#path = Path("trajectories/bmr_308GDsPUn0YWiGBi4npNO/claude-sonnet-4-20250514/914210/914210.traj")


paths = Path("trajectories/bmr_307qEKQLh1AMbrudtpBJE/openai/c3-sweep-tkbjm9b4-mc01-fp16")
paths = Path("trajectories/bmr_308GDsPUn0YWiGBi4npNO/claude-sonnet-4-20250514")

for path in paths.glob("*/*.traj"):
    with path.open("r") as f:
        traj = json.load(f)

    out = []
    for i, turn in enumerate(traj["trajectory"]):
        print(turn["action"].split("\n")[0])
        print(turn["response"])
        out.append(f"# Turn {i}\n\nRESPONSE\n\n{turn['response']}\n\nOBSERVATION\n\n{turn['observation']}")

    with open("responses.txt", "w") as f:
        f.write("\n\n".join(out))
    import pdb; pdb.set_trace()
