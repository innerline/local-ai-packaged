#!/usr/bin/env python3
"""
start_services.py

This script starts the Supabase stack first, waits for it to initialize, and then starts
the local AI stack. Both stacks use the same Docker Compose project name ("localai")
so they appear together in Docker Desktop.
"""

import os
import subprocess
import shutil
import time
import argparse
import platform
import sys
import yaml

def run_command(cmd, cwd=None, description=None):
    """Run a shell command and print it."""
    if description:
        print(f"Action: {description}")
    print("Running:", " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)
        if result.stdout:
            print("Output:", result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print("Error occurred:")
        print("Return code:", e.returncode)
        print("Command:", e.cmd)
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        raise

def clone_supabase_repo():
    """Clone the Supabase repository using sparse checkout if not already present."""
    if not os.path.exists("supabase"):
        print("Cloning the Supabase repository...")
        run_command([
            "git", "clone", "--filter=blob:none", "--no-checkout",
            "https://github.com/supabase/supabase.git"
        ])
        os.chdir("supabase")
        run_command(["git", "sparse-checkout", "init", "--cone"])
        run_command(["git", "sparse-checkout", "set", "docker"])
        run_command(["git", "checkout", "master"])
        os.chdir("..")
    else:
        print("Supabase repository already exists, updating...")
        os.chdir("supabase")
        run_command(["git", "pull"])
        os.chdir("..")

def prepare_supabase_env():
    """Copy .env to .env in supabase/docker."""
    env_path = os.path.join("supabase", "docker", ".env")
    env_example_path = os.path.join(".env")
    print("Copying .env in root to .env in supabase/docker...")
    shutil.copyfile(env_example_path, env_path)

def check_existing_containers():
    """Check for existing containers that might conflict."""
    print("=== Checking for existing containers ===")
    try:
        # Check all containers in the localai project
        result = run_command([
            "docker", "ps", "-a", "--filter", "name=localai", "--format",
            "table {{.Names}}\t{{.Status}}\t{{.Image}}"
        ], description="List existing localai containers")
        
        # Check specifically for n8n containers
        n8n_result = run_command([
            "docker", "ps", "-a", "--filter", "name=n8n", "--format",
            "table {{.Names}}\t{{.Status}}\t{{.Image}}"
        ], description="List existing n8n containers")
        
        # Check for any containers using the same ports
        print("\n=== Checking for port conflicts ===")
        port_check = run_command([
            "docker", "ps", "--filter", "publish=5678", "--format",
            "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        ], description="Check for port 5678 usage (n8n default)")
        
    except Exception as e:
        print(f"Note: Could not fully check existing containers: {e}")
    
    print("=== End container check ===\n")

def cleanup_stray_containers():
    """Clean up any stray containers that might conflict."""
    print("=== Cleaning up stray containers ===")
    try:
        # Specifically look for and remove any n8n containers that might be lingering
        result = run_command([
            "docker", "ps", "-a", "--filter", "name=n8n", "--format", "{{.Names}}"
        ], description="Find all n8n containers")
        
        n8n_containers = result.stdout.strip().split('\n') if result.stdout else []
        n8n_containers = [c for c in n8n_containers if c]
        
        if n8n_containers:
            print(f"Found existing n8n containers: {n8n_containers}")
            for container in n8n_containers:
                print(f"Removing container: {container}")
                run_command([
                    "docker", "rm", "-f", container
                ], description=f"Force remove {container}")
        else:
            print("No existing n8n containers found")
            
        # Also check for any other containers that might conflict
        print("\n=== Checking for other potential conflicts ===")
        conflicting_containers = [
            "ollama", "flowise", "qdrant", "searxng", "redis",
            "clickhouse", "minio", "langfuse-web", "langfuse-worker"
        ]
        
        for container_name in conflicting_containers:
            try:
                result = run_command([
                    "docker", "inspect", "--format={{.State.Running}}", container_name
                ], description=f"Check if {container_name} is running", check=False)
                
                if result.returncode == 0 and "true" in result.stdout:
                    print(f"Found running {container_name} container")
                    run_command([
                        "docker", "rm", "-f", container_name
                    ], description=f"Remove conflicting {container_name} container")
            except:
                pass  # Container doesn't exist, which is fine
                
    except Exception as e:
        print(f"Note: Error during container cleanup: {e}")
    
    print("=== End container cleanup ===\n")

def stop_existing_containers(profile=None):
    print("Stopping and removing existing containers for the unified project 'localai'...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", "docker-compose.yml", "down"])
    try:
        run_command(cmd, description="Stop and remove localai containers")
    except subprocess.CalledProcessError as e:
        print("Standard docker compose down failed, trying aggressive cleanup...")
        # If standard cleanup fails, try a more aggressive approach
        cleanup_stray_containers()
        # Try again
        run_command(cmd, description="Retry stop and remove localai containers")

def start_supabase(environment=None):
    """Start the Supabase services (using its compose file)."""
    print("Starting Supabase services...")
    cmd = ["docker", "compose", "-p", "localai", "-f", "supabase/docker/docker-compose.yml"]
    if environment and environment == "public":
        cmd.extend(["-f", "docker-compose.override.public.supabase.yml"])
    cmd.extend(["up", "-d"])
    run_command(cmd, description="Start Supabase services")

def comprehensive_cleanup():
    """Perform a comprehensive cleanup of all possible conflicting containers."""
    print("=== Starting comprehensive container cleanup ===")
    
    # List of all possible container names from both compose files
    all_containers = [
        # Main compose file containers
        "localai-flowise-1", "localai-open-webui-1", "localai-n8n-1",
        "localai-n8n-import-1", "localai-qdrant-1", "localai-neo4j-1",
        "localai-caddy-1", "localai-langfuse-worker-1", "localai-langfuse-web-1",
        "localai-clickhouse-1", "localai-minio-1", "localai-redis-1",
        "localai-searxng-1", "localai-ollama-cpu-1", "localai-ollama-gpu-1",
        "localai-ollama-gpu-amd-1", "localai-ollama-pull-llama-cpu-1",
        "localai-ollama-pull-llama-gpu-1", "localai-ollama-pull-llama-gpu-amd-1",
        
        # Supabase containers
        "supabase-studio-1", "supabase-kong-1", "supabase-auth-1",
        "supabase-rest-1", "realtime-dev.supabase-realtime-1", "supabase-storage-1",
        "supabase-imgproxy-1", "supabase-meta-1", "supabase-edge-functions-1",
        "supabase-analytics-1", "supabase-db-1", "supabase-vector-1",
        "supabase-pooler-1", "supabase-mail-1",
        
        # Old hard-coded names (for legacy cleanup)
        "n8n", "ollama", "ollama-pull-llama", "flowise", "open-webui",
        "qdrant", "caddy", "redis", "searxng"
    ]
    
    removed_count = 0
    for container in all_containers:
        try:
            # Check if container exists
            result = run_command([
                "docker", "inspect", "--format={{.Name}}", container
            ], description=f"Check if {container} exists", check=False)
            
            if result.returncode == 0:
                print(f"Found container: {container}")
                # Force remove the container
                run_command([
                    "docker", "rm", "-f", container
                ], description=f"Remove container {container}")
                removed_count += 1
                
        except Exception as e:
            print(f"Note: Could not process {container}: {e}")
    
    print(f"=== Cleanup completed. Removed {removed_count} containers ===\n")
    
    # Clean up any unused networks
    try:
        run_command([
            "docker", "network", "prune", "-f"
        ], description="Clean up unused Docker networks")
    except:
        pass  # Network cleanup is optional

def start_local_ai(profile=None, environment=None):
    """Start the local AI services (using its compose file)."""
    print("Starting local AI services...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", "docker-compose.yml"])
    if environment and environment == "private":
        cmd.extend(["-f", "docker-compose.override.private.yml"])
    if environment and environment == "public":
        cmd.extend(["-f", "docker-compose.override.public.yml"])
    cmd.extend(["up", "-d"])
    try:
        run_command(cmd, description="Start local AI services")
    except subprocess.CalledProcessError as e:
        print("Failed to start services. Attempting comprehensive cleanup and retry...")
        comprehensive_cleanup()
        print("Retrying service startup...")
        run_command(cmd, description="Retry start local AI services")

def generate_searxng_secret_key():
    """Generate a secret key for SearXNG based on the current platform."""
    print("Checking SearXNG settings...")

    # Define paths for SearXNG settings files
    settings_path = os.path.join("searxng", "settings.yml")
    settings_base_path = os.path.join("searxng", "settings-base.yml")

    # Check if settings-base.yml exists
    if not os.path.exists(settings_base_path):
        print(f"Warning: SearXNG base settings file not found at {settings_base_path}")
        return

    # Check if settings.yml exists, if not create it from settings-base.yml
    if not os.path.exists(settings_path):
        print(f"SearXNG settings.yml not found. Creating from {settings_base_path}...")
        try:
            shutil.copyfile(settings_base_path, settings_path)
            print(f"Created {settings_path} from {settings_base_path}")
        except Exception as e:
            print(f"Error creating settings.yml: {e}")
            return
    else:
        print(f"SearXNG settings.yml already exists at {settings_path}")

    print("Generating SearXNG secret key...")

    # Detect the platform and run the appropriate command
    system = platform.system()

    try:
        if system == "Windows":
            print("Detected Windows platform, using PowerShell to generate secret key...")
            # PowerShell command to generate a random key and replace in the settings file
            ps_command = [
                "powershell", "-Command",
                "$randomBytes = New-Object byte[] 32; " +
                "(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes); " +
                "$secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ }); " +
                "(Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml"
            ]
            subprocess.run(ps_command, check=True)

        elif system == "Darwin":  # macOS
            print("Detected macOS platform, using sed command with empty string parameter...")
            # macOS sed command requires an empty string for the -i parameter
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", "", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)

        else:  # Linux and other Unix-like systems
            print("Detected Linux/Unix platform, using standard sed command...")
            # Standard sed command for Linux
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)

        print("SearXNG secret key generated successfully.")

    except Exception as e:
        print(f"Error generating SearXNG secret key: {e}")
        print("You may need to manually generate the secret key using the commands:")
        print("  - Linux: sed -i \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - macOS: sed -i '' \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")
        print("  - Windows (PowerShell):")
        print("    $randomBytes = New-Object byte[] 32")
        print("    (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes)")
        print("    $secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ })")
        print("    (Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml")

def check_and_fix_docker_compose_for_searxng():
    """Check and modify docker-compose.yml for SearXNG first run."""
    docker_compose_path = "docker-compose.yml"
    if not os.path.exists(docker_compose_path):
        print(f"Warning: Docker Compose file not found at {docker_compose_path}")
        return

    try:
        # Read the docker-compose.yml file
        with open(docker_compose_path, 'r') as file:
            content = file.read()

        # Default to first run
        is_first_run = True

        # Check if Docker is running and if the SearXNG container exists
        try:
            # Check if the SearXNG container is running
            container_check = subprocess.run(
                ["docker", "ps", "--filter", "name=searxng", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True
            )
            searxng_containers = container_check.stdout.strip().split('\n')

            # If SearXNG container is running, check inside for uwsgi.ini
            if any(container for container in searxng_containers if container):
                container_name = next(container for container in searxng_containers if container)
                print(f"Found running SearXNG container: {container_name}")

                # Check if uwsgi.ini exists inside the container
                container_check = subprocess.run(
                    ["docker", "exec", container_name, "sh", "-c", "[ -f /etc/searxng/uwsgi.ini ] && echo 'found' || echo 'not_found'"],
                    capture_output=True, text=True, check=False
                )

                if "found" in container_check.stdout:
                    print("Found uwsgi.ini inside the SearXNG container - not first run")
                    is_first_run = False
                else:
                    print("uwsgi.ini not found inside the SearXNG container - first run")
                    is_first_run = True
            else:
                print("No running SearXNG container found - assuming first run")
        except Exception as e:
            print(f"Error checking Docker container: {e} - assuming first run")

        if is_first_run and "cap_drop: - ALL" in content:
            print("First run detected for SearXNG. Temporarily removing 'cap_drop: - ALL' directive...")
            # Temporarily comment out the cap_drop line
            modified_content = content.replace("cap_drop: - ALL", "# cap_drop: - ALL  # Temporarily commented out for first run")

            # Write the modified content back
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)

            print("Note: After the first run completes successfully, you should re-add 'cap_drop: - ALL' to docker-compose.yml for security reasons.")
        elif not is_first_run and "# cap_drop: - ALL  # Temporarily commented out for first run" in content:
            print("SearXNG has been initialized. Re-enabling 'cap_drop: - ALL' directive for security...")
            # Uncomment the cap_drop line
            modified_content = content.replace("# cap_drop: - ALL  # Temporarily commented out for first run", "cap_drop: - ALL")

            # Write the modified content back
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)

    except Exception as e:
        print(f"Error checking/modifying docker-compose.yml for SearXNG: {e}")

def main():
    parser = argparse.ArgumentParser(description='Start the local AI and Supabase services.')
    parser.add_argument('--profile', choices=['cpu', 'gpu-nvidia', 'gpu-amd', 'none'], default='cpu',
                      help='Profile to use for Docker Compose (default: cpu)')
    parser.add_argument('--environment', choices=['private', 'public'], default='private',
                      help='Environment to use for Docker Compose (default: private)')
    args = parser.parse_args()

    clone_supabase_repo()
    prepare_supabase_env()

    # Generate SearXNG secret key and check docker-compose.yml
    generate_searxng_secret_key()
    check_and_fix_docker_compose_for_searxng()

    # Check for existing containers before stopping
    check_existing_containers()
    
    stop_existing_containers(args.profile)

    # Start Supabase first
    start_supabase(args.environment)

    # Give Supabase some time to initialize
    print("Waiting for Supabase to initialize...")
    time.sleep(10)

    # Then start the local AI services
    start_local_ai(args.profile, args.environment)

if __name__ == "__main__":
    main()
