from .base_plugin import BasePlugin
from typing import List, Dict, Any
from slack_bolt import BoltContext
import logging
from lib import env
from lib.llm import LLMClient
import base64
from io import BytesIO
from PIL import Image
from slack_sdk.errors import SlackApiError


class FilePlugin(BasePlugin):
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB limit for vision API
    MAX_IMAGE_LENGTH = 1024  # Recommended max length for image px

    SUPPORTED_FILE_TYPES = {
        "text": [
            "text", "applescript", "boxnote", "c", "csharp", "cpp", "css", "csv", "clojure",
            "coffeescript", "cfm", "d", "dart", "diff", "dockerfile", "email", "fsharp",
            "fortran", "go", "groovy", "html", "handlebars", "haskell", "haxe", "java",
            "javascript", "json", "kotlin", "latex", "lisp", "lua", "markdown", "matlab",
            "mumps", "objc", "ocaml", "pascal", "perl", "php", "pig", "post", "powershell",
            "puppet", "python", "r", "rtf", "ruby", "rust", "sql", "sass", "scala", "scheme",
            "shell", "smalltalk", "swift", "tsv", "vb", "vbscript", "vcard", "velocity",
            "verilog", "xml", "yaml",
        ],
        "image": ["ai", "bmp", "eps", "gif", "indd", "jpg", "png", "psd", "svg", "tiff"],
    }

    def process_message(self, context: BoltContext, message: Dict[str, Any], logger: logging.Logger) -> List[Dict[str, Any]]:
        content = []
        files = message.get("files", [])
        logger.info(f"FilePlugin processing message: {message.get('text', '')[:100]}")
        if not files or not self.is_bot_able_to_access_files(context):
            return content

        for file in files:
            file_content = self.process_file(context, file, logger)
            if file_content:
                content.append(file_content)

        return content

    def process_file(self, context: BoltContext, file: Dict[str, Any], logger: logging.Logger) -> Dict[str, Any]:
        slack_filetype = file.get("filetype")
        slack_mimetype = file.get("mimetype")
        file_size = file.get("size", 0)

        if not slack_filetype or not slack_mimetype:
            logger.info(f"Skipped unsupported file type: {slack_filetype}")
            return {"type": "text", "text": f"Skipped unsupported file type: {slack_filetype}"}

        if file_size > self.MAX_FILE_SIZE:
            logger.info(f"Skipped file exceeding size limit: {file.get('name', '')} ({file_size} bytes)")
            return {"type": "text", "text": f"Skipped file exceeding size limit: {file.get('name', '')} ({file_size} bytes)"}

        file_url = file.get("url_private", "")
        try:
            file_content = self.download_slack_file_content(file_url, context.bot_token)
        except SlackApiError as e:
            logger.error(f"Failed to download file content: {e}")
            return {"type": "text", "text": f"Failed to download file: {file.get('name', '')}"}

        content_type = self.categorize_file(slack_filetype)

        if content_type == "image":
            return self.process_image(file, file_content, slack_mimetype, logger)
        elif content_type == "text":
            return self.process_text(file, file_content)
        else:
            logger.info(f"Skipped unsupported file type: {slack_filetype}")
            return {"type": "text", "text": f"Skipped unsupported file type: {slack_filetype}"}

    def process_image(self, file: Dict[str, Any], file_content: bytes, slack_mimetype: str, logger: logging.Logger) -> Dict[str, Any]:
        if not LLMClient.is_model_able_to_receive_images():
            logger.info("Model does not support images.")
            return {"type": "text", "text": "Model does not support images."}

        try:
            img = Image.open(BytesIO(file_content))
            img.thumbnail((self.MAX_IMAGE_LENGTH, self.MAX_IMAGE_LENGTH))
            buffer = BytesIO()
            img.save(buffer, format=img.format)
            resized_content = buffer.getvalue()
            encoded_content = base64.b64encode(resized_content).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to process image: {e}")
            return {"type": "text", "text": f"Failed to process image: {file.get('name', '')}"}

        if env.PROVIDER == "bedrock" or env.PROVIDER == "anthropic":
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": f"{slack_mimetype}",
                    "data": f"{encoded_content}",
                }
            }
        else:
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{slack_mimetype};base64,{encoded_content}"},
            }

    def process_text(self, file: Dict[str, Any], file_content: bytes) -> Dict[str, Any]:
        return {
            "type": "text",
            "text": f"File: {file.get('name', '')}\n```{file_content.decode('utf-8')}```",
        }

    @staticmethod
    def categorize_file(file_extension: str) -> str:
        for category, extensions in FilePlugin.SUPPORTED_FILE_TYPES.items():
            if file_extension in extensions:
                return category
        return "other"

    @staticmethod
    def download_slack_file_content(file_url: str, bot_token: str) -> bytes:
        import requests
        response = requests.get(
            file_url,
            headers={"Authorization": f"Bearer {bot_token}"},
        )
        if response.status_code != 200:
            error = f"Request to {file_url} failed with status code {response.status_code}"
            raise SlackApiError(error, response)

        content_type = response.headers.get("content-type", "")

        if content_type.startswith("text/html"):
            error = f"You don't have the permission to download this file: {file_url}"
            raise SlackApiError(error, response)

        return response.content

    @staticmethod
    def is_bot_able_to_access_files(context: BoltContext) -> bool:
        if env.FILE_ACCESS_ENABLED is False:
            return False
        bot_scopes = context.authorize_result.bot_scopes or []  # type: ignore
        return bool(context and "files:read" in bot_scopes)
