"""
Find all the swesmith problem instances that are non-empty
"""

import datasets
from pathlib import Path


def main():
    # Load the SWE-bench/SWE-smith dataset
    dataset = datasets.load_dataset("SWE-bench/SWE-smith", split="train")

    # Filter examples with non-empty problem_statement using HuggingFace filter
    filtered_dataset = dataset.filter(
        lambda example: example.get("problem_statement")
        and example["problem_statement"].strip()
    )

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    # Convert to DataFrame and save to CSV
    df = filtered_dataset.to_pandas()
    df.to_csv("data/swesmith_nonempty.csv", index=False)

    print(f"Found {len(filtered_dataset)} examples with non-empty problem_statement")
    print("Saved to data/swesmith_nonempty.csv")


if __name__ == "__main__":
    main()
