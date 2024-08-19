#!/bin/bash

set -euo pipefail

# Function to display usage information
usage() {
    echo "Usage: $0 -n <checkpoint_name> [-m <custom_message>] [-d] [-h]"
    echo "  -n <checkpoint_name>  Name for this checkpoint (e.g. v1.0, feature-x-complete)"
    echo "  -m <custom_message>   Custom message for the release commit (optional)"
    echo "  -d                    Perform a dry run without pushing changes"
    echo "  -h                    Display this help message"
    echo "Example: ./scripts/release.sh -n \"v1.0\" -m \"First major release\""
    exit 1
}

# Function to get the last private commit from the public repo
get_last_private_commit() {
    echo "Attempting to get last private commit from CHECKPOINT.md in the public repository..." >&2
    
    # Ensure we have the latest from the public repository
    git fetch public || { echo "Error: Failed to fetch from public repository." >&2; return 1; }
    
    # Check if CHECKPOINT.md exists in the public main branch
    if ! git ls-tree -r public/main | grep -q "CHECKPOINT.md"; then
        echo "Note: CHECKPOINT.md not found in the public repository. This might be the first release." >&2
        return 0
    fi
    
    # Extract the Checkpoint-Commit from CHECKPOINT.md
    local checkpoint_commit
    checkpoint_commit=$(git show public/main:CHECKPOINT.md | grep "Checkpoint-Commit:" | cut -d ' ' -f 2)
    
    if [[ -z "$checkpoint_commit" ]]; then
        echo "Error: CHECKPOINT.md found, but no 'Checkpoint-Commit:' line in the file." >&2
        return 1
    fi
    
    echo "Last private commit from previous release: $checkpoint_commit" >&2
    echo "$checkpoint_commit"
}

check_for_changes() {
    git update-index -q --refresh
    git diff-index --quiet HEAD -- || return 0
    return 1
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
if [[ -z "${CHECKPOINT_NAME:-}" ]]; then
    echo "Error: Checkpoint name is required."
    usage
fi

# Environment variables
SLAICK_PUBLIC_REPO_URL=${SLAICK_PUBLIC_REPO_URL:-""}
SLAICK_PUBLIC_REPO_PAT=${SLAICK_PUBLIC_REPO_PAT:-""}

# Validate environment variables
if [[ -z "$SLAICK_PUBLIC_REPO_URL" ]]; then
    echo "Error: SLAICK_PUBLIC_REPO_URL is not set. Please set this environment variable."
    exit 1
fi

if [[ -z "$SLAICK_PUBLIC_REPO_PAT" ]]; then
    echo "Error: SLAICK_PUBLIC_REPO_PAT is not set. Please set this environment variable."
    exit 1
fi

# Ensure we're in the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "${SCRIPT_DIR}/.." || { echo "Error: Failed to change to project root directory."; exit 1; }

# Create a temporary directory
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Clone the original repo to the temporary directory
git clone . "$TEMP_DIR" || { echo "Error: Failed to clone repository."; exit 1; }
cd "$TEMP_DIR" || { echo "Error: Failed to change to temporary directory."; exit 1; }

# Setup Git
git config user.name "github-actions"
git config user.email "github-actions@github.com"

# Fetch public repo
echo "Fetching public repo..."
git remote add public "https://${SLAICK_PUBLIC_REPO_PAT}@${SLAICK_PUBLIC_REPO_URL#https://}"
git fetch public || { echo "Error: Failed to fetch public repo."; exit 1; }

# Create checkpoint with squashed commits
echo "Starting checkpoint creation process..."

if git ls-remote --exit-code --heads public main; then
    echo "Public main branch found. Creating temp branch..."
    git checkout -b temp public/main || { echo "Error: Failed to create temp branch."; exit 1; }
else
    echo "Public main branch not found. Creating orphan branch..."
    git checkout --orphan temp || { echo "Error: Failed to create orphan branch."; exit 1; }
    git rm -rf .
    git commit --allow-empty -m "Initial commit"
fi


LAST_PRIVATE_COMMIT=$(get_last_private_commit)
LATEST_PRIVATE_COMMIT=$(git rev-parse HEAD)

echo "Last private commit from previous release: ${LAST_PRIVATE_COMMIT:-None}"
echo "Latest private commit for this release: $LATEST_PRIVATE_COMMIT"

# Generate commit messages
if [[ -n "$LAST_PRIVATE_COMMIT" ]]; then
    echo "Attempting to generate release message from commit history since last checkpoint."
    if git rev-parse --quiet --verify "$LAST_PRIVATE_COMMIT^{commit}" >/dev/null 2>&1; then
        COMMIT_MESSAGES=$(git log --pretty=format:"- %s" $LAST_PRIVATE_COMMIT..$LATEST_PRIVATE_COMMIT)
    else
        echo "Warning: Last private commit ($LAST_PRIVATE_COMMIT) not found in the current repository."
        echo "Including all commit messages up to the latest commit."
        COMMIT_MESSAGES=$(git log --pretty=format:"- %s" $LATEST_PRIVATE_COMMIT)
    fi
else
    echo "No previous checkpoint found. Including all commit messages."
    COMMIT_MESSAGES=$(git log --pretty=format:"- %s" $LATEST_PRIVATE_COMMIT)
fi

if [[ -z "$COMMIT_MESSAGES" ]]; then
    echo "No new commits found since last release."
    COMMIT_MESSAGES="No new commits since last release."
fi

if [[ -n "${CUSTOM_MESSAGE:-}" ]]; then
    echo "Using custom message for release."
    SQUASH_MESSAGE="Release: $CHECKPOINT_NAME. $CUSTOM_MESSAGE"
else
    printf "Commit messages to be included:\n%s\n" "$COMMIT_MESSAGES"
    SQUASH_MESSAGE="Release: $CHECKPOINT_NAME. Included commits:
$COMMIT_MESSAGES"
fi


## Squash commit
echo "Creating squashed commit..."

# Create a new orphan branch for the squashed commit
git checkout --orphan temp_branch

# Remove everything from the staging area
git rm -rf . --quiet

# Checkout all files from the latest private commit
git checkout $LATEST_PRIVATE_COMMIT -- .

if check_for_changes; then
    echo "Changes detected. Creating squashed commit..."
    git add .
    git commit -m "$SQUASH_MESSAGE" || { echo "Error: Failed to create squashed commit."; exit 1; }
else
    echo "Warning: No changes detected between the last release and the current state."
    echo "This could mean that no new commits have been made since the last release,"
    echo "or that all changes have already been merged into the public repository."
    
    read -p "Do you want to proceed with creating an empty commit? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Proceeding with empty commit..."
        git commit --allow-empty -m "$SQUASH_MESSAGE" || { echo "Error: Failed to create empty commit."; exit 1; }
    else
        echo "Release process cancelled. No changes were made."
        exit 0
    fi
fi

# Create checkpoint commit
echo "Creating checkpoint commit..."
echo "Checkpoint: $CHECKPOINT_NAME" > CHECKPOINT.md
echo "Created at: $(date)" >> CHECKPOINT.md
echo "Checkpoint-Commit: $LATEST_PRIVATE_COMMIT" >> CHECKPOINT.md
git add CHECKPOINT.md
git commit -m "Checkpoint: $CHECKPOINT_NAME" || { echo "Error: Failed to create checkpoint commit."; exit 1; }

echo "Checkpoint creation process completed successfully."


# Push to public repo
if [[ "${DRY_RUN:-}" != true ]]; then
    echo "Pushing changes to public repo..."
    
    # Ensure we're on the temp_branch
    git checkout temp_branch || { echo "Error: Failed to checkout temp_branch."; exit 1; }
    
    # Fetch the latest changes from the public repo
    git fetch public || { echo "Error: Failed to fetch latest changes from public repo."; exit 1; }
    
    # Create a new branch based on the latest public main
    git checkout -b new_main public/main || { echo "Error: Failed to create new_main branch."; exit 1; }
    
    # Cherry-pick our new commits onto the new_main branch
    git cherry-pick temp_branch || { echo "Error: Failed to cherry-pick new commits."; exit 1; }
    
    # Push the new_main branch to the public repo
    if git push public new_main:main; then
        echo "Changes pushed to public repo successfully."
        echo "Please verify the changes at: ${SLAICK_PUBLIC_REPO_URL}"
    else
        echo "Error: Failed to push to public repo. Check your credentials and repo settings."
        echo "You can try pushing manually with:"
        echo "git push ${SLAICK_PUBLIC_REPO_URL} new_main:main"
        exit 1
    fi
else
    echo "Dry run completed. Changes were not pushed to the public repo."
    echo "Summary of changes that would be pushed:"
    git log --oneline public/main..temp_branch
fi

# Cleanup
cd "${SCRIPT_DIR}/.." || { echo "Error: Failed to change back to original directory."; exit 1; }
rm -rf "$TEMP_DIR"

echo "Script completed successfully."