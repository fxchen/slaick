#!/bin/bash

# Get the directory of the script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the project root directory
cd "${SCRIPT_DIR}/.." || exit 1

set -eo pipefail

pip install -r requirements.txt
pip install pytest && pytest .
pip install "flake8==6.1.0" && flake8 ./*.py ./lib/*.py
pip install "pytype==2024.4.11" boto3 && pytype ./*.py ./lib/*.py
