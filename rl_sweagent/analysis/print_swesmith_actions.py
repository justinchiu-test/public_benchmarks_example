import datasets
import re

def extract_commands_only(text: str) -> list[tuple[str, str]]:
    """
    Extract only function names and command parameters.
    
    Args:
        text: The text containing XML-like function calls
        
    Returns:
        List of tuples (function_name, command_value)
    """
    results = []
    
    # Pattern to match function blocks
    function_pattern = r'<function=([^>]+)>(.*?)</function>'
    function_matches = re.findall(function_pattern, text, re.DOTALL)
    
    for function_name, function_content in function_matches:
        # Look for command parameter specifically
        command_pattern = r'<parameter=command>(.*?)</parameter>'
        command_match = re.search(command_pattern, function_content, re.DOTALL)
        
        if command_match:
            command_value = command_match.group(1).strip()
            results.append((function_name, command_value))
        else:
            # Include functions without command parameter with None
            results.append((function_name, None))
    
    return results


dataset = datasets.load_dataset("SWE-bench/SWE-smith-trajectories", split="train")
turns = dataset[200]["messages"]

for turn in turns:
    if turn["role"] == "assistant":
        content = turn["content"]
        print(extract_commands_only(content))
#import pdb; pdb.set_trace()
