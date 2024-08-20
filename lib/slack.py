import logging
import time
from typing import Any, Dict, List, Optional

from slack_bolt import BoltContext
from slack_sdk.errors import SlackApiError
from slack_sdk.web import WebClient

from lib.formatting import format_llm_message_for_slack, split_message
from vendor.chatgptinslack.app.i18n import translate
from vendor.chatgptinslack.app.slack_constants import DEFAULT_LOADING_TEXT
from vendor.chatgptinslack.app.slack_ops import (
    find_parent_message,
    is_this_app_mentioned,
    post_wip_message,
    update_wip_message,
)


def is_bot_mentioned(context: BoltContext, payload: dict) -> bool:
    """Check if the bot is mentioned in the message."""
    return f"<@{context.bot_user_id}>" in payload.get("text", "")


def send_wip_message(
    context: BoltContext,
    client: WebClient,
    payload: dict,
    messages: List[Dict[str, Any]],
):
    """Send a work-in-progress message."""
    loading_text = translate(
        openai_api_key=context.get("OPENAI_API_KEY"),
        context=context,
        text=DEFAULT_LOADING_TEXT,
    )
    return post_wip_message(
        client=client,
        channel=context.channel_id,  # type: ignore
        thread_ts=payload.get("thread_ts", payload.get("ts")),
        loading_text=loading_text,
        messages=messages,
        user=context.user_id,  # type: ignore
    )


def handle_long_message(
    client: WebClient,
    context: BoltContext,
    wip_reply: dict,
    num_context_tokens: int,
    max_context_tokens: int,
):
    """Handle cases where the message is too long."""
    update_wip_message(
        client=client,
        channel=context.channel_id,  # type: ignore
        ts=wip_reply["message"]["ts"],
        text=f":warning: The previous message is too long ({num_context_tokens}/{max_context_tokens} prompt tokens).",
        messages=[],
        user=context.user_id,  # type: ignore
    )


def is_bot_mentioned_in_thread(client: WebClient, context: BoltContext, payload: dict) -> bool:
    """Check if the bot is mentioned in the thread."""
    thread_ts = payload.get("thread_ts")
    if not thread_ts:
        return False
    parent_message = find_parent_message(client, context.channel_id, thread_ts)
    return parent_message is not None and is_this_app_mentioned(context, parent_message)


def handle_error(
    client: WebClient,
    context: BoltContext,
    wip_reply: Optional[dict],
    logger,
    error_message: str,
    openai_api_key: str,
):
    """Handle general errors."""
    text = (
        (wip_reply.get("message", {}).get("text", "") or "")  # type: ignore
        + "\n\n"
        + translate(
            openai_api_key=openai_api_key,
            context=context,
            text=f":warning: Failed to start a conversation with ChatGPT: {error_message}",
        )
    )
    logger.exception(text)
    if wip_reply:
        client.chat_update(
            channel=context.channel_id,  # type: ignore
            ts=wip_reply["message"]["ts"],
            text=text,
        )


def send_long_message_in_chunks(
    client: WebClient,
    context: BoltContext,
    wip_reply: dict,
    text: str,
    loading_character: str,
    logger: logging.Logger,
):
    """
    Send a long message in chunks as replies to the original message.

    This method handles sending a lengthy message that exceeds Slack's
    message length limitations by splitting it into smaller chunks. The
    first chunk updates the original message, and subsequent chunks are
    sent as threaded replies. Each chunk is appended with a loading
    character to indicate ongoing updates.

    Parameters:
    - client: WebClient instance for Slack API interactions.
    - context: BoltContext containing contextual information like user and channel IDs.
    - wip_reply: Dictionary maintaining the in-progress reply message.
    - text: The long message text to be sent in chunks.
    - loading_character: A string character appended to each chunk to indicate ongoing processing.
    - logger: Logging instance for logging the process details.

    Returns:
    - The response from the Slack API for the last chunk sent.

    Raises:
    - SlackApiError: If there is an error while sending any of the message chunks.
    """
    chunks = split_message(text)

    logger.info(f"Splitting message into {len(chunks)} chunks")

    thread_ts = wip_reply["message"]["ts"]
    first_chunk = True

    for chunk in chunks:
        try:
            if first_chunk:
                # Update the original message with the first chunk
                response = client.chat_update(
                    channel=context.channel_id,  # type: ignore
                    ts=thread_ts,
                    text=chunk + loading_character,
                )
                first_chunk = False
            else:
                # Send subsequent chunks as replies
                response = client.chat_postMessage(
                    channel=context.channel_id,  # type: ignore
                    thread_ts=thread_ts,
                    text=chunk + (loading_character if chunk != chunks[-1] else ""),
                )
            logger.info(f"Successfully sent chunk of length {len(chunk)}")
        except SlackApiError as e:
            logger.error(f"Error sending message chunk: {e}")
            raise

    wip_reply["message"]["text"] = text
    return response


def update_slack_message(
    client: WebClient,
    context: BoltContext,
    wip_reply: dict,
    assistant_reply: Dict[str, Any],
    messages: List[Dict[str, Any]],
    loading_character: str,
    translate_markdown: bool,
    logger: logging.Logger,
):
    """Update the Slack message with the latest content, handling long messages and API errors."""

    assistant_reply_text = format_llm_message_for_slack(
        assistant_reply["content"], translate_markdown
    )
    logger.info(f"Formatted reply: {assistant_reply_text}")
    logger.info(f"Formatted reply length: {len(assistant_reply_text)} characters")
    try:
        # Attempt to update the original message
        updated_message = update_wip_message(
            client=client,
            channel=context.channel_id,  # type: ignore
            ts=wip_reply["message"]["ts"],
            text=assistant_reply_text + loading_character,
            messages=messages,
            user=context.user_id,  # type: ignore
        )
        logger.info("Successfully updated message in Slack")
        wip_reply["message"]["text"] = assistant_reply_text
        return updated_message

    except SlackApiError as e:
        if e.response["error"] == "msg_too_long":
            logger.warning("Message too long, attempting to split and send in chunks")
            return send_long_message_in_chunks(
                client,
                context,
                wip_reply,
                assistant_reply_text,
                loading_character,
                logger,
            )
        else:
            logger.error(f"Unexpected Slack API error: {e}")
            raise


def get_messages_in_context(
    context: BoltContext,
    client: WebClient,
    payload: dict,
    is_in_dm_with_bot: bool,
    thread_ts: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant messages for context based on whether its a DM or a thread.

    Args:
        context (BoltContext): The Bolt context object.
        client (WebClient): The Slack WebClient object.
        payload (dict): The payload containing information about the event.
        is_in_dm_with_bot (bool): Indicates if the conversation is a direct message with the bot.
        thread_ts (Optional[str]): The timestamp of the thread, if applicable.

    Returns:
        List[Dict[str, Any]]: A list of relevant messages for the given context.
    """
    if is_in_dm_with_bot and not thread_ts:
        # For DMs, get recent message history
        past_messages = client.conversations_history(  # type: ignore
            channel=context.channel_id,  # type: ignore
            include_all_metadata=True,
            limit=100,
        ).get("messages", [])
        past_messages.reverse()
        # Filter messages from the last 24 hours
        return [msg for msg in past_messages if time.time() - float(msg.get("ts", 0)) < 86400]
    elif thread_ts:
        # For threads, get all replies
        return client.conversations_replies(
            channel=context.channel_id,  # type: ignore
            ts=thread_ts,
            include_all_metadata=True,
            limit=1000,
        ).get("messages", [])

    # For new conversations, return the current message
    return [payload]
