import base64
import logging
from typing import List, Optional

import requests
from slack_bolt import BoltContext
from slack_sdk.errors import SlackApiError

from lib.env import FILE_ACCESS_ENABLED

# Define supported file types and their corresponding categories
# https://api.slack.com/types/file
SUPPORTED_FILE_TYPES = {
    "text": [
        "text",
        "applescript",
        "boxnote",
        "c",
        "csharp",
        "cpp",
        "css",
        "csv",
        "clojure",
        "coffeescript",
        "cfm",
        "d",
        "dart",
        "diff",
        "dockerfile",
        "email",
        "fsharp",
        "fortran",
        "go",
        "groovy",
        "html",
        "handlebars",
        "haskell",
        "haxe",
        "java",
        "javascript",
        "json",
        "kotlin",
        "latex",
        "lisp",
        "lua",
        "markdown",
        "matlab",
        "mumps",
        "objc",
        "ocaml",
        "pascal",
        "perl",
        "php",
        "pig",
        "post",
        "powershell",
        "puppet",
        "python",
        "r",
        "rtf",
        "ruby",
        "rust",
        "sql",
        "sass",
        "scala",
        "scheme",
        "shell",
        "smalltalk",
        "swift",
        "tsv",
        "vb",
        "vbscript",
        "vcard",
        "velocity",
        "verilog",
        "xml",
        "yaml",
    ],
    "image": ["ai", "bmp", "eps", "gif", "indd", "jpg", "png", "psd", "svg", "tiff"],
}


def categorize_file(file_extension: str) -> str:
    """
    Categorize a file based on its extension.

    This function takes a file extension and determines its category
    based on the SUPPORTED_FILE_TYPES dictionary. If the extension
    is not found in any category, it defaults to "text".

    Args:
        file_extension (str): The file extension to categorize (without the leading dot).

    Returns:
        str: The category of the file ("text" or "image").
              Returns "other" if the extension is not found in SUPPORTED_FILE_TYPES.

    Example:
        >>> categorize_file("jpg")
        "image"
        >>> categorize_file("py")
        "text"
        >>> categorize_file("unknown")
        "other"
    """
    for category, extensions in SUPPORTED_FILE_TYPES.items():
        if file_extension in extensions:
            return category
    return "other"  # Default to text if not found


def download_slack_file_content(file_url: str, bot_token: str) -> bytes:
    """
    Download file content from Slack.

    Args:
        file_url (str): The URL of the file to download.
        bot_token (str): The Slack bot token for authentication.

    Returns:
        bytes: The content of the file.

    Raises:
        SlackApiError: If there's an error downloading the file or if the file type is unsupported.
    """
    response = requests.get(
        file_url,
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    if response.status_code != 200:
        error = f"Request to {file_url} failed with status code {response.status_code}"
        raise SlackApiError(error, response)

    content_type = response.headers.get("content-type", "")

    # Check for HTML response, which usually indicates a lack of permissions
    if content_type.startswith("text/html"):
        error = f"You don't have the permission to download this file: {file_url}"
        raise SlackApiError(error, response)

    return response.content


def get_file_content_if_exists(
    *,
    context: BoltContext,
    bot_token: str,
    files: List[dict],
    content: List[dict],
    logger: logging.Logger,
) -> Optional[List[dict]]:
    if not files:
        return None

    for file in files:
        slack_filetype = file.get("filetype")
        slack_mimetype = file.get("mimetype")
        if not slack_filetype or not slack_mimetype:
            logger.info(f"Skipped unsupported file type: {slack_filetype}")
            continue

        file_url = file.get("url_private", "")
        try:
            file_content = download_slack_file_content(file_url, bot_token)
        except SlackApiError as e:
            logger.error(f"Failed to download file content: {e}")
            continue

        encoded_content = base64.b64encode(file_content).decode("utf-8")
        content_type = categorize_file(slack_filetype)
        content_item = {}

        # https://platform.openai.com/docs/guides/vision?lang=python
        if content_type == "image":
            if not is_model_able_to_receive_images(context):
                logger.info("Model does not support images.")
                continue
            content_item = {
                "type": "image_url",
                "image_url": {"url": f"data:{slack_mimetype};base64,{encoded_content}"},
            }
        elif content_type == "text":
            content_item = {
                "type": "text",
                "text": f"File: {file.get('name', '')}\n```{file_content.decode('utf-8')}```",
            }
        else:
            logger.info(f"Skipped unsupported file type: {slack_filetype}")
            continue
        content.append(content_item)
    return content


def is_bot_able_to_access_files(context: BoltContext) -> bool:
    """
    Check if the bot is able to access files.

    Args:
        context (BoltContext): The Bolt context object.

    Returns:
        bool: True if the bot is able to access files, False otherwise.
    """
    if FILE_ACCESS_ENABLED is False:
        return False
    bot_scopes = context.authorize_result.bot_scopes or []  # type: ignore
    return bool(context and "files:read" in bot_scopes)


def is_model_able_to_receive_images(context: BoltContext) -> bool:
    """
    Determines if the model is able to receive images.

    Args:
        context (BoltContext): The context object containing the model information.

    Returns:
        bool: True if the model is able to receive images, False otherwise.
    """
    openai_model = context.get("OPENAI_MODEL")
    # More supported models will come. This logic will need to be updated then.
    can_send_image_url = openai_model is not None and openai_model.startswith("gpt-4o")
    return can_send_image_url
