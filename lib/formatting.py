from typing import List

from slack_bolt import BoltContext

from vendor.chatgptinslack.app.openai_ops import (
    build_system_text,
    format_assistant_reply,
    format_openai_message_content,
)

MAX_CHUNK_LENGTH = 3000  # 4000 is approximately the maximum length of a Slack message


def format_llm_message_for_slack(content: str, translate_markdown: bool) -> str:
    """
    Format message from LiteLLM to display in Slack.
    Args:
        content (str): The content of the message from OpenAI.
        translate_markdown (bool): Whether to translate markdown in the message.

    Returns:
        str: The formatted message to display in Slack.

    """
    return format_assistant_reply(content, translate_markdown) or ""


def format_message_content_for_llm(content: str, translate_markdown: bool) -> str:
    """
    Format message from Slack to send to LiteLLM.

    Args:
        content (str): The content of the message from Slack.
        translate_markdown (bool): Whether to translate markdown in the message.

    Returns:
        str: The formatted message to send to LiteLLM.

    """
    return format_openai_message_content(content, translate_markdown) or ""


def get_system_text(
    system_text_template: str, translate_markdown: bool, context: BoltContext
) -> str:
    """
    Get system text for the given template.

    Args:
        system_text_template (str): The template for the system text.
        translate_markdown (bool): Whether to translate markdown in the system text.
        context (BoltContext): The context object for the Bolt framework.

    Returns:
        str: The generated system text.

    """
    return build_system_text(system_text_template, translate_markdown, context)


def split_message(message: str, max_chunk_length: int = MAX_CHUNK_LENGTH) -> List[str]:
    """
    Split a long message into chunks that fit within the specified max_chunk_length.

    This method processes a given message string and splits it into smaller chunks
    so that each chunk's length does not exceed the provided max_chunk_length. It can handle
    multi-line messages by splitting them appropriately at newline characters while
    ensuring that each resulting chunk is within the length constraint.

    Args:
        message (str): The input message string to be split into chunks.
        max_chunk_length (int): The maximum allowed length for each chunk.

    Returns:
        List[str]: A list of message chunks, each of which adheres to the max_length constraint.

    Behavior:
        - The method iterates through each line in the input message.
        - It accumulates lines into the current_chunk until adding another line would
            exceed the max_length.
        - If adding another line exceeds the max_length, the current_chunk is added to
            the chunks list and reset.
        - If an individual line exceeds the max_length by itself, it is split into
            smaller parts that fit within the max_length.
        - The accumulated current_chunk (if any) is appended to the chunks list at the end.
    """
    chunks = []
    current_chunk = ""

    for line in message.split("\n"):
        if len(current_chunk) + len(line) + 1 > max_chunk_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # If a single line is longer than max_length, split it
            while len(line) > max_chunk_length:
                chunks.append(line[:max_chunk_length])
                line = line[max_chunk_length:]

        current_chunk += line + "\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks
