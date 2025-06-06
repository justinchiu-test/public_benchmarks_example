import re
import subprocess
import sys

def parse_running_devboxes(filename):
    try:
        with open(filename, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: {filename} not found. Please run 'uv run rl devbox list --status running > devbox_output.txt' first.")
        return []
    
    # Split by devbox entries (each starts with "devbox={")
    devbox_entries = re.split(r'devbox=\{', content)[1:]  # Skip first empty part
    
    running_ids = []
    
    for entry in devbox_entries:
        # Add back the opening brace
        entry = '{' + entry
        
        # Extract ID
        id_match = re.search(r'"id":\s*"([^"]+)"', entry)
        if not id_match:
            continue
        
        devbox_id = id_match.group(1)
        
        # Check if status is running
        status_match = re.search(r'"status":\s*"([^"]+)"', entry)
        if status_match and status_match.group(1) == "running":
            running_ids.append(devbox_id)
    
    return running_ids

def shutdown_devboxes(ids_file):
    """Shutdown devboxes using the IDs from the file"""
    try:
        with open(ids_file, 'r') as f:
            devbox_ids = f.read().strip().split('\n')
        
        if not devbox_ids or devbox_ids == ['']:
            print("No devbox IDs found to shutdown")
            return
        
        print(f"Shutting down {len(devbox_ids)} devboxes...")
        
        for devbox_id in devbox_ids:
            if devbox_id.strip():
                print(f"Shutting down devbox: {devbox_id}")
                try:
                    result = subprocess.run(
                        ['uv', 'run', 'rl', 'devbox', 'shutdown', '--id', devbox_id.strip()],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode == 0:
                        print(f"✓ Successfully shutdown {devbox_id}")
                    else:
                        print(f"✗ Failed to shutdown {devbox_id}: {result.stderr}")
                except subprocess.TimeoutExpired:
                    print(f"✗ Timeout shutting down {devbox_id}")
                except Exception as e:
                    print(f"✗ Error shutting down {devbox_id}: {e}")
        
        print("Shutdown process completed")
        
    except FileNotFoundError:
        print(f"Error: {ids_file} not found. Please run the parsing first.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--shutdown":
        # Shutdown mode
        shutdown_devboxes("devbox_ids.txt")
    else:
        # Parse mode (default)
        # from `uv run rl devbox list --status running > devbox_output.txt`
        running_ids = parse_running_devboxes("devbox_output.txt")
        
        if running_ids:
            # Write to devbox_ids.txt
            with open("devbox_ids.txt", "w") as f:
                for devbox_id in running_ids:
                    f.write(devbox_id + "\n")
            
            print(f"Found {len(running_ids)} running devboxes")
            print("IDs written to devbox_ids.txt")
            print("To shutdown all devboxes, run: python parse_devboxes.py --shutdown")
        else:
            print("No running devboxes found")
