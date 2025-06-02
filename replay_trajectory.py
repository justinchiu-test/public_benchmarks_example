#!/usr/bin/env python3
"""
Standalone script to replay the first interaction from a SWE-agent trajectory.
Extracts system prompt, user query, and tools from trajectory and config files.
"""

import json
import os
import argparse
from openai import OpenAI
from typing import Dict, List, Any


def get_swe_agent_tools() -> List[Dict[str, Any]]:
    """Define all SWE-agent tools manually."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "runs the given command directly in bash",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The bash command to execute.",
                        }
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "str_replace_editor",
                "description": "Custom editing tool for viewing, creating and editing files. State is persistent across command calls and discussions with the user. If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep. The `create` command cannot be used if the specified `path` already exists as a file. If a `command` generates a long output, it will be truncated and marked with `<response clipped>`. The `undo_edit` command will revert the last edit made to the file at `path`. Notes for using the `str_replace` command: The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces! If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique. The `new_str` parameter should contain the edited lines that should replace the `old_str`",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The commands to run. Allowed options are: `view`, `create`, `str_replace`, `insert`, `undo_edit`.",
                            "enum": [
                                "view",
                                "create",
                                "str_replace",
                                "insert",
                                "undo_edit",
                            ],
                        },
                        "path": {
                            "type": "string",
                            "description": "Absolute path to file or directory, e.g. `/testbed/file.py` or `/testbed`.",
                        },
                        "file_text": {
                            "type": "string",
                            "description": "Required parameter of `create` command, with the content of the file to be created.",
                        },
                        "old_str": {
                            "type": "string",
                            "description": "Required parameter of `str_replace` command containing the string in `path` to replace.",
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.",
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.",
                        },
                        "view_range": {
                            "type": "array",
                            "description": "Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": ["command", "path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit",
                "description": "submits the current file",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    return tools


def get_trajectory_messages() -> List[Dict[str, str]]:
    """Get the hardcoded messages from the trajectory file."""
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that can interact with a computer to solve tasks.",
        },
        {
            "role": "user",
            "content": "<uploaded_files>\n/SWE-agent__test-repo\n</uploaded_files>\nI've uploaded a python code repository in the directory /SWE-agent__test-repo. Consider the following PR description:\n\n<pr_description>\nSyntaxError: invalid syntax\nI'm running `missing_colon.py` as follows:\r\n\r\n```python\r\ndivision(23, 0)\r\n```\r\n\r\nbut I get the following error:\r\n\r\n```\r\n  File \"/Users/fuchur/Documents/24/git_sync/swe-agent-test-repo/tests/./missing_colon.py\", line 4\r\n    def division(a: float, b: float) -> float\r\n                                             ^\r\nSyntaxError: invalid syntax\r\n```\n\n</pr_description>\n\nCan you help me implement the necessary changes to the repository so that the requirements specified in the <pr_description> are met?\nI've already taken care of all changes to any of the test files described in the <pr_description>. This means you DON'T have to modify the testing logic or any of the tests in any way!\nYour task is to make the minimal changes to non-tests files in the /SWE-agent__test-repo directory to ensure the <pr_description> is satisfied.\nFollow these steps to resolve the issue:\n1. As a first step, it might be a good idea to find and read code relevant to the <pr_description>\n2. Create a script to reproduce the error and execute it with `python <filename.py>` using the bash tool, to confirm the error\n3. Edit the sourcecode of the repo to resolve the issue\n4. Rerun your reproduce script and confirm that the error is fixed!\n5. Think about edgecases and make sure your fix handles them as well\nYour thinking should be thorough and so it's fine if it's very long.",
        },
    ]
    return messages


def send_openai_request(
    messages: List[Dict[str, str]], tools: List[Dict[str, Any]], model: str, provider: str
) -> Dict[str, Any]:
    """Send request to OpenAI API with extracted messages and tools."""

    # Initialize OpenAI client based on provider
    if provider == "together":
        client = OpenAI(
            api_key=os.getenv("TOGETHER_API_KEY"),
            base_url="https://api.together.xyz/v1",
        )
    elif provider == "deepseek":
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.6,
            max_tokens=32000,
        )

        return {
            "success": True,
            "response": response,
            "message": response.choices[0].message,
            "usage": response.usage,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Replay SWE-agent trajectory with different providers")
    parser.add_argument(
        "--provider", 
        choices=["together", "deepseek"], 
        default="deepseek",
        help="API provider to use (default: deepseek)"
    )
    args = parser.parse_args()

    # Get SWE-agent tools
    print("Loading SWE-agent tools...")
    tools = get_swe_agent_tools()

    # Get hardcoded messages
    print("Loading hardcoded messages...")
    messages = get_trajectory_messages()

    print("\n=== EXTRACTED MESSAGES ===")
    for i, msg in enumerate(messages):
        print(f"\nMessage {i + 1} ({msg['role']}):")
        print(
            f"Content: {msg['content'][:200]}..."
            if len(msg["content"]) > 200
            else f"Content: {msg['content']}"
        )

    print(f"\n=== EXTRACTED TOOLS ===")
    print(f"Number of tools: {len(tools)}")
    for tool in tools:
        print(
            f"- {tool['function']['name']}: {tool['function']['description'][:100]}..."
        )

    # Check if API key is available for selected provider
    api_key_env = f"{args.provider.upper()}_API_KEY"
    if not os.getenv(api_key_env):
        print(f"\n❌ {api_key_env} environment variable not set!")
        print(f"Set it with: export {api_key_env}='your-api-key-here'")
        return

    # Set model based on provider
    if args.provider == "together":
        model = "deepseek-ai/DeepSeek-R1"
    elif args.provider == "deepseek":
        model = "deepseek-reasoner"

    # Send request to API
    print(f"\n=== SENDING {args.provider.upper()} REQUEST ===")
    result = send_openai_request(
        messages,
        tools,
        model,
        args.provider,
    )

    if result["success"]:
        print("✅ Request successful!")
        print(f"\nModel: {result['response'].model}")
        print(f"Usage: {result['usage']}")
        print(f"\nResponse message:")
        print(f"Role: {result['message'].role}")
        print(f"Content: {result['message'].content}")

        if result["message"].tool_calls:
            print(f"\nTool calls:")
            for tool_call in result["message"].tool_calls:
                print(f"- {tool_call.function.name}: {tool_call.function.arguments}")
        else:
            print("❌ NO TOOL CALLS")
    else:
        print(f"❌ Request failed: {result['error']}")


if __name__ == "__main__":
    main()
