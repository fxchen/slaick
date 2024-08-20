#!/bin/bash
set -euo pipefail

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
echo "Script directory: ${SCRIPT_DIR}"

# Change to the project root directory
cd "${SCRIPT_DIR}/.." || {
    echo "Failed to change directory"
    exit 1
}
echo "Current working directory: $(pwd)"

# Function to load environment variables
load_env_vars() {
    local env_file="$1"
    local export_vars="${2:-false}"

    if [[ ! -f "$env_file" || ! -r "$env_file" ]]; then
        echo "Error: .env file not found or not readable." >&2
        return 1
    fi

    # Array to store environment variables
    declare -a env_vars

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Ignore comments and empty lines
        if [[ ! "$line" =~ ^\s*#.*$ && -n "$line" ]]; then
            # Extract key and value
            if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
                key="${BASH_REMATCH[1]}"
                value="${BASH_REMATCH[2]}"

                # Remove leading/trailing whitespace and quotes from the value
                value=$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")

                if [[ "$export_vars" == "true" ]]; then
                    export "$key=$value"
                else
                    # Add to env_vars array
                    env_vars+=("-e" "${key}=${value}")
                fi

                # Add to env_vars array
                env_vars+=("-e" "${key}=${value}")
                echo "Loaded: $key=$value"
            fi
        fi
    done < "$env_file"

    # Export the env_vars array
    ENV_VARS=("${env_vars[@]}")
}

# Load environment
ENV_FILE="./.env"
load_env_vars "$ENV_FILE" true

# Verify that required environment variables are set
REQUIRED_VARS=("SLACK_BOT_TOKEN" "SLACK_APP_TOKEN")
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "Error: Required environment variable $var is not set." >&2
        exit 1
    fi
done

# Optional: Build the Docker image (if not already built)
docker build -t slaick-app . || {
    echo "Docker build failed"
    exit 1
}

echo "Starting Docker container..."
# Run the Docker container with the loaded environment variables
if [ -n "${ENV_VARS+x}" ]; then
    docker run "${ENV_VARS[@]}" slaick-app || { echo "Docker run failed"; exit 1; }
else
    echo "Warning: No environment variables loaded. Running Docker without environment variables."
    docker run slaick-app || { echo "Docker run failed"; exit 1; }
fi