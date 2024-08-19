#!/bin/bash
set -euo pipefail

# Get the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
echo "Script directory: ${SCRIPT_DIR}"

# Change to the project root directory
cd "${SCRIPT_DIR}/.." || { echo "Failed to change directory"; exit 1; }
echo "Current working directory: $(pwd)"

# Function to load environment variables
load_env_vars() {
    local env_file="$1"
    local export_vars="${2:-false}"

    if [[ ! -f "$env_file" || ! -r "$env_file" ]]; then
        echo "Error: .env file not found or not readable." >&2
        return 1
    fi

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
                    eval "$key=$value"
                fi
                echo "Loaded: $key=$value"
            fi
        fi
    done < "$env_file"
}

# Load environment
ENV_FILE="./.env"
set -a
load_env_vars "$ENV_FILE"
set +a

# Verify that required environment variables are set
REQUIRED_VARS=("SLACK_BOT_TOKEN" "SLACK_APP_TOKEN")
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "Error: Required environment variable $var is not set." >&2
        exit 1
    fi
done

# Run the Python script
if command -v python3 &> /dev/null; then
    python3 main.py
elif command -v python &> /dev/null; then
    python main.py
else
    echo "Error: Python interpreter not found."
    exit 1
fi