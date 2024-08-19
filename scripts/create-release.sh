#!/bin/bash

# Get the directory of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the project root directory
cd "${SCRIPT_DIR}/.." || exit 1

set -eo pipefail

# Function to display usage information
usage() {
    echo "Usage: $0 -n <checkpoint_name> [-m <custom_message>] [-d] [-h]"
    echo "  -n <checkpoint_name>  Name for this checkpoint (e.g. v1.0, feature-x-complete)"
    echo "  -m <custom_message>   Custom message for the release commit (optional)"
    echo "  -d                    Perform a dry run without pushing changes"
    echo "  -h                    Display this help message"
    echo "Example: ./scripts/create_release.sh -n \"v1.0\" -m \"First major release\""
    exit 1
}

# Parse command line arguments
while getopts "n:m:dh" opt; do
    case ${opt} in
        n ) CHECKPOINT_NAME=$OPTARG ;;
        m ) CUSTOM_MESSAGE=$OPTARG ;;
        d ) DRY_RUN=true ;;
        h ) usage ;;
        \? ) usage ;;
    esac
done

# Check if required arguments are provided
if [[ -z "$CHECKPOINT_NAME" ]]; then
    echo "Error: Checkpoint name is required."
    usage
fi

# Environment variables
SLAICK_PUBLIC_REPO_URL=${SLAICK_PUBLIC_REPO_URL:-"https://github.com/username/public-repo.git"}
SLAICK_PUBLIC_REPO_PAT=${SLAICK_PUBLIC_REPO_PAT:-"your_personal_access_token"}

# Validate environment variables
if [[ -z "$SLAICK_PUBLIC_REPO_URL" ]]; then
    echo "Error: SLAICK_PUBLIC_REPO_URL is not set. Please set this environment variable."
    exit 1
fi

if [[ -z "$SLAICK_PUBLIC_REPO_PAT" ]]; then
    echo "Error: SLAICK_PUBLIC_REPO_PAT is not set. Please set this environment variable."
    exit 1
fi

# Create a temporary directory
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Clone the original repo to the temporary directory
git clone . "$TEMP_DIR"
cd "$TEMP_DIR"

# Setup Git
git config user.name "github-actions"
git config user.email "github-actions@github.com"

# Fetch public repo
echo "Fetching public repo..."
git remote add public "https://${SLAICK_PUBLIC_REPO_PAT}@${SLAICK_PUBLIC_REPO_URL#https://}"
git fetch public

# Create checkpoint with squashed commits
echo "Starting checkpoint creation process..."

if git ls-remote --exit-code --heads public main; then
    echo "Public main branch found. Creating temp branch..."
    git checkout -b temp public/main
else
    echo "Public main branch not found. Creating orphan branch..."
    git checkout --orphan temp
    git rm -rf .
    git commit --allow-empty -m "Initial commit"
fi

LATEST_PRIVATE_COMMIT=$(git rev-parse origin/main)
echo "Latest private commit: $LATEST_PRIVATE_COMMIT"

LAST_CHECKPOINT=$(git log --grep="^Release:" --format="%H" -n 1 temp)
[[ -n "$LAST_CHECKPOINT" ]] && echo "Last checkpoint found: $LAST_CHECKPOINT" || echo "No previous checkpoint found."

if [[ -n "$CUSTOM_MESSAGE" ]]; then
    echo "Using custom message for release."
    SQUASH_MESSAGE="Release: $CHECKPOINT_NAME. $CUSTOM_MESSAGE"
else
    echo "Generating release message from commit history."
    if [[ -n "$LAST_CHECKPOINT" ]]; then
        COMMIT_MESSAGES=$(git log --pretty=format:"- %s" $LAST_CHECKPOINT..$LATEST_PRIVATE_COMMIT)
    else
        COMMIT_MESSAGES=$(git log --pretty=format:"- %s" $LATEST_PRIVATE_COMMIT)
    fi
    SQUASH_MESSAGE="Release: $CHECKPOINT_NAME. Included commits:. $COMMIT_MESSAGES"
fi

echo "Creating squashed commit..."
git rm -rf . 2>/dev/null || true
git clean -fdx
git checkout $LATEST_PRIVATE_COMMIT -- .
git add .
git commit -m "$SQUASH_MESSAGE"

echo "Creating checkpoint commit..."
echo "Checkpoint: $CHECKPOINT_NAME" > CHECKPOINT.md
echo "Created at: $(date)" >> CHECKPOINT.md
git add CHECKPOINT.md
git commit -m "Checkpoint: $CHECKPOINT_NAME"

echo "Checkpoint creation process completed successfully."

# Push to public repo
if [[ "$DRY_RUN" != true ]]; then
    echo "Pushing changes to public repo..."
    git push public temp:main || { echo "Failed to push to public repo. Check your credentials and repo settings."; exit 1; }
    echo "Changes pushed to public repo successfully."
else
    echo "Dry run completed. Changes were not pushed to the public repo."
    echo "Summary of changes:"
    git log --oneline public/main..temp
fi

echo "Script completed successfully."