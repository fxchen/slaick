#!/bin/bash
set -euo pipefail

# Get the directory of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the project root directory
cd "${SCRIPT_DIR}/.." || exit 1


# Function to display error messages
error() {
    echo "ERROR: $1" >&2
    exit 1
}

# Function to display informational messages
info() {
    echo "INFO: $1"
}

# Check if we're in a git repository
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    error "Not in a Git repository. Please run this script from within a Git repository."
fi

# Function to create vendor directory if it doesn't exist
create_vendor_dir() {
    if [ ! -d "vendor" ]; then
        info "Creating 'vendor' directory"
        mkdir vendor || error "Failed to create 'vendor' directory"
    else
        info "'vendor' directory already exists"
    fi
}

# Function to reset and update a single submodule
reset_and_update_submodule() {
    local submodule_path="$1"
    info "Resetting and updating submodule: $submodule_path"
    
    # Ensure we're on the main branch (or master, depending on your setup)
    git -C "$submodule_path" checkout main 2>/dev/null || git -C "$submodule_path" checkout master 2>/dev/null || error "Failed to checkout main/master branch in $submodule_path"
    
    # Fetch the latest changes
    git -C "$submodule_path" fetch origin || error "Failed to fetch updates for $submodule_path"
    
    # Reset to origin/main (or origin/master)
    git -C "$submodule_path" reset --hard origin/main 2>/dev/null || git -C "$submodule_path" reset --hard origin/master 2>/dev/null || error "Failed to reset $submodule_path to origin/main or origin/master"
    
    # Clean the submodule working directory
    git -C "$submodule_path" clean -fxd || error "Failed to clean $submodule_path"
}

# Function to create __init__.py if it doesn't exist
create_init_py() {
    local init_file="vendor/__init__.py"
    if [ ! -f "$init_file" ]; then
        info "Creating empty $init_file"
        touch "$init_file" || error "Failed to create $init_file"
    else
        info "$init_file already exists"
    fi
}

# Main script execution
info "Starting submodule reset and sync process..."

# Create vendor directory if it doesn't exist
create_vendor_dir

# Initialize submodules if they haven't been already
git submodule init || error "Failed to initialize submodules"

# Update submodules
git submodule update || error "Failed to update submodules"

# Iterate through each submodule in the vendor directory
while IFS= read -r submodule; do
    if [[ $submodule == vendor/* ]]; then
        reset_and_update_submodule "$submodule"
    fi
done < <(git config --file .gitmodules --get-regexp path | awk '{ print $2 }')

# Create empty __init__.py in vendor directory if it doesn't exist
create_init_py

# Final sync to ensure everything is up to date
git submodule sync || error "Failed to sync submodules"
git submodule update --init --recursive || error "Failed to perform final update of submodules"

info "Submodule reset and sync process completed successfully."