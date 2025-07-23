#!/usr/bin/env python3
"""Inspect the fields available in SWE-Gym dataset examples."""

import json

from datasets import load_dataset


def inspect_swegym_fields():
    print("[INFO] Loading SWE-Gym dataset...")
    dataset = load_dataset("SWE-Gym/SWE-Gym", split="train", streaming=True)

    # Get the first example
    example = next(iter(dataset))

    print("\n[INFO] Available fields in SWE-Gym example:")
    print("=" * 80)

    for key in sorted(example.keys()):
        value = example[key]
        value_type = type(value).__name__

        print(f"\n{key} ({value_type}):")
        print("-" * len(key))

        if isinstance(value, str):
            if len(value) > 200:
                print(f"{value[:100]}...")
                print("...")
                print(f"...{value[-100:]}")
                print(f"\n(Total length: {len(value)} characters)")
            else:
                print(value)
        elif isinstance(value, (list, dict)):
            print(json.dumps(value, indent=2))
        else:
            print(value)

    print("\n" + "=" * 80)

    # Look specifically for test-related fields
    print("\n[INFO] Test-related fields:")
    for key in example.keys():
        if any(
            term in key.lower() for term in ["test", "eval", "score", "check", "verify"]
        ):
            print(f"- {key}: {type(example[key]).__name__}")
            if isinstance(example[key], str) and len(example[key]) < 500:
                print(f"  Content: {example[key]}")


if __name__ == "__main__":
    inspect_swegym_fields()
