import logging
import mimetypes
from typing import List, Optional

import requests
from slack_sdk.errors import SlackApiError

SUPPORTED_FILE_TYPES = {
    "image": ["png", "jpeg", "gif", "webp"],
    "document": ["pdf", "doc", "docx", "txt"],
    "code": ["py", "js", "html", "css", "json"],
    "spreadsheet": ["csv", "xlsx"],
    "presentation": ["ppt", "pptx"],
}


def categorize_file(
    file_extension: str,
) -> str:
    for category, extensions in SUPPORTED_FILE_TYPES.items():
        if file_extension in extensions:
            return "image_url" if category == "image" else "text"
    return "text"


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

    # List of supported MIME types
    supported_mime_types = [
        "image/",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.",
        "text/plain",
        "text/csv",
        "application/json",
        "text/html",
        "text/css",
        "application/javascript",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    ]

    # Check if the content type is supported
    if not any(content_type.startswith(mime) for mime in supported_mime_types):
        error = f"Unsupported content type: {content_type}"
        raise SlackApiError(error, response)

    return response.content


def get_file_content_if_exists(
    *,
    bot_token: str,
    files: List[dict],
    content: List[dict],
    logger: logging.Logger,
) -> Optional[List[dict]]:
    if files is None or len(files) == 0:
        return None

    for file in files:
        mime_type = file.get("mimetype")
        if mime_type is None:
            continue

        file_type = mime_type.split("/")[0]
        file_extension = mimetypes.guess_extension(mime_type)

        if file_extension:
            file_extension = file_extension[1:]  # Remove the leading dot
        else:
            logger.info(f"Couldn't determine file extension for mime type: {mime_type}")
            continue

        if file_type in SUPPORTED_FILE_TYPES and file_extension in SUPPORTED_FILE_TYPES[file_type]:
            file_url = file.get("url_private", "")
            file_content = download_slack_file_content(file_url, bot_token)
            content_type = categorize_file(file_extension)

            if file_content:
                encoded_content = base64.b64encode(file_content).decode("utf-8")
                # https://platform.openai.com/docs/guides/vision?lang=python

                if content_type == "image_url":
                    content_item = {
                        "type": "text",
                        "file_content": {"mime_type": mime_type, "data": encoded_content},
                    }
                elif content_type == "text":
                    content_item = {
                        "type": "text",
                        "text": f"File: {file.get('name', '')}\n```{file_content.decode('utf-8')}```",
                    }
                else:
                    logger.info(f"Unsupported content type: {content_type}")
                    continue

                content.append(content_item)
            else:
                logger.info(f"Failed to download file content: {file_url}")
        else:
            logger.info(f"Skipped unsupported file type: {mime_type}")

    return content
