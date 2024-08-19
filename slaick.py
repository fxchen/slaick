import json
import logging
import os
import sys
import threading
import time
from importlib import import_module
from typing import Any, Callable, Dict, List, Optional

import litellm
import openai
from slack_bolt import App, BoltContext, BoltResponse
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt.request.payload_utils import is_event
from slack_sdk.errors import SlackApiError
from slack_sdk.web import WebClient

from lib.env import (
    MAX_RESPONSE_TOKENS,
    OPENAI_API_BASE,
    OPENAI_API_VERSION,
    OPENAI_DEPLOYMENT_ID,
    OPENAI_FUNCTION_CALL_MODULE_NAME,
    OPENAI_IMAGE_GENERATION_MODEL,
    OPENAI_MODEL,
    OPENAI_ORG_ID,
    SYSTEM_TEXT,
    TEMPERATURE,
    TIMEOUT_SECONDS,
    TRANSLATE_MARKDOWN,
)

vendor_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "vendor/chatgptinslack"))
sys.path.insert(0, vendor_dir)

from lib.files import get_file_content_if_exists, is_bot_able_to_access_files
from lib.formatting import (
    format_llm_message_for_slack,
    format_message_content_for_llm,
    get_system_text,
    split_message,
)
from lib.llm import messages_within_context_window, start_litellm_stream
from vendor.chatgptinslack.app.i18n import translate
from vendor.chatgptinslack.app.sensitive_info_redaction import redact_string
from vendor.chatgptinslack.app.slack_constants import DEFAULT_LOADING_TEXT, TIMEOUT_ERROR_MESSAGE
from vendor.chatgptinslack.app.slack_ops import (
    find_parent_message,
    is_this_app_mentioned,
    post_wip_message,
    update_wip_message,
)

logger = logging.getLogger(__name__)


class Slaick:
    MESSAGE_SUBTYPES_TO_SKIP = ["message_changed", "message_deleted"]

    @staticmethod
    def before_authorize(body: dict, payload: dict, logger: logging.Logger, next_):
        """
        Middleware function to skip processing of certain message subtypes.

        This function acts as a middleware to avoid processing Slack events that
        are of certain message subtypes such as "message_changed" or "message_deleted".
        This helps in reducing unnecessary workload, particularly for events
        involving messages that change rapidly.
        Args:
            body (dict): The entire request payload including the event and context.
            payload (dict): The specific event payload data.
            logger (logging.Logger): Logger object for recording debug and error information.
            next_ (Callable): A function to pass control to the next middleware in the chain.

        Returns:
            BoltResponse: A Slack SDK BoltResponse object with status 200
            and an empty body if the event is to be skipped.
        Notes:
            - If the event is a message event of a subtype listed in MESSAGE_SUBTYPES_TO_SKIP,
              the function logs a debug message and returns a BoltResponse to skip further processing.
            - If not, it passes control to the next middleware or handler by calling next_().
        """
        if (
            is_event(body)
            and payload.get("type") == "message"
            and payload.get("subtype") in Slaick.MESSAGE_SUBTYPES_TO_SKIP
        ):
            logger.debug(
                "Skipped the following middleware and listeners "
                f"for this message event (subtype: {payload.get('subtype')})"
            )
            return BoltResponse(status=200, body="")
        next_()

    @staticmethod
    def set_llm_api_keys(context: BoltContext, next_):
        """
        Middleware function to set LLM API key and related configurations in the context.
        """
        context["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
        context["OPENAI_MODEL"] = OPENAI_MODEL
        context["OPENAI_IMAGE_GENERATION_MODEL"] = OPENAI_IMAGE_GENERATION_MODEL
        context["OPENAI_TEMPERATURE"] = TEMPERATURE
        context["OPENAI_API_BASE"] = OPENAI_API_BASE
        context["OPENAI_API_VERSION"] = OPENAI_API_VERSION
        context["OPENAI_DEPLOYMENT_ID"] = OPENAI_DEPLOYMENT_ID
        context["OPENAI_ORG_ID"] = OPENAI_ORG_ID
        context["OPENAI_FUNCTION_CALL_MODULE_NAME"] = OPENAI_FUNCTION_CALL_MODULE_NAME
        next_()

    @staticmethod
    def setup_middleware(app: App):
        """
        Set up all middleware for the Slack app.
        """
        app.middleware(Slaick.before_authorize)
        app.middleware(Slaick.set_llm_api_keys)

    @staticmethod
    def start_socket_mode(app: App):
        """
        Start the SocketModeHandler for the Slack app.
        """
        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        handler.start()

    @staticmethod
    def register_event_handler(app: App, event_type: str, handler: Callable):
        """Register an event handler for a specific Slack event type."""
        app.event(event_type)(ack=lambda ack: ack(), lazy=[handler])

    @staticmethod
    def _is_bot_mentioned(context: BoltContext, payload: dict) -> bool:
        """Check if the bot is mentioned in the message."""
        return f"<@{context.bot_user_id}>" in payload.get("text", "")

    @staticmethod
    def _is_new_conversation(payload: dict) -> bool:
        """Check if this is a new conversation (no thread_ts)."""
        return payload.get("thread_ts") is None

    @staticmethod
    def handle_app_mention(context: BoltContext, payload: dict, client: WebClient, logger):
        """
        Handle app mention events in Slack.

        This method manages situations where the bot is mentioned in a message.
        It works to identify if the mention occurs within a thread and determines
        if a parent message already includes a mention of the bot. If such a mention
        is found, it skips further processing, assuming the message event handler
        will handle the reply.

        Args:
            context (BoltContext): Context object carrying event-related data.
            payload (dict): Dictionary containing the event payload data.
            client (WebClient): WebClient to interact with the Slack API.
            logger (logging.Logger): Logger object for recording debug and error information.
        Returns:
            None
        Notes:
            - If the app is mentioned within a thread, checks the parent message for app mention
              before proceeding.
            - If a parent message already mentions the app, it avoids redundant handling.
            - Delegates actual message processing to `_process_message` method if needed.
        """
        thread_ts = payload.get("thread_ts")
        if thread_ts:
            parent_message = find_parent_message(client, context.channel_id, thread_ts)
            if parent_message and is_this_app_mentioned(context, parent_message):
                return  # The message event handler will reply to this

        Slaick._process_message(context, payload, client, logger)

    @staticmethod
    def handle_message(context: BoltContext, payload: dict, client: WebClient, logger):
        """
        Handle new message events in Slack.

        This method processes messages in two main scenarios:
        1. Direct Messages (DMs) to the bot.
        2. Threads where the bot is mentioned.

        For DMs, it will always process the message.
        For threads, it will verify if the bot is mentioned in the thread before processing.

        Args:
            context (BoltContext): The Bolt context object containing the event's contextual data.
            payload (dict): A dictionary containing the event payload data.
            client (WebClient): The Slack WebClient used to interact with the Slack API.
            logger (logging.Logger): The logger object for logging debug and error information.

        Returns:
            None

        Notes:
            - Skips processing if the message is from a bot (excluding the current bot).
            - Ensures that direct messages (DMs) and multi-party instant messages (MPIMs) are processed.
            - For threads, it checks if the bot is mentioned before processing.
        """
        if payload.get("bot_id") and payload.get("bot_id") != context.bot_id:
            return  # Skip messages from other bots

        is_in_dm = payload.get("channel_type") == "im" or payload.get("channel_type") == "mpim"
        thread_ts = payload.get("thread_ts")

        if is_in_dm or (
            not is_in_dm
            and thread_ts
            and Slaick._is_bot_mentioned_in_thread(client, context, payload)
        ):
            Slaick._process_message(context, payload, client, logger)

    @staticmethod
    def _process_message(
        context: BoltContext,
        payload: dict,
        client: WebClient,
        logger: logging.Logger,
    ):
        """
        Process a message for both app mentions and direct messages.
        This method handles the core logic of interacting with the LiteLLM API and responding in Slack.
        """
        # Check if OpenAI API key is configured
        openai_api_key = context.get("OPENAI_API_KEY")
        if not openai_api_key:
            client.chat_postMessage(
                channel=context.channel_id,  # type: ignore
                text="To use this app, please configure your OpenAI API key first",
            )
            return

        try:
            # Determine if the message is in a DM or a thread
            is_in_dm_with_bot = payload.get("channel_type") in ["im", "mpim"]
            thread_ts = payload.get("thread_ts")

            # Process messages in DMs, threads, or when the bot is mentioned
            if (
                not is_in_dm_with_bot
                and not thread_ts
                and not Slaick._is_bot_mentioned(context, payload)
            ):
                return

            # Retrieve relevant messages for context
            messages_in_context = Slaick._get_messages_in_context(
                context, client, payload, is_in_dm_with_bot, thread_ts
            )

            # Return if there are no messages AND it's not a new conversation
            if not messages_in_context and not Slaick._is_new_conversation(payload):
                return

            # Prepare messages for calling LiteLLM
            messages = Slaick._prepare_messages(context, messages_in_context)
            user_id = context.actor_user_id or context.user_id

            # Send a "work in progress" message to Slack
            wip_reply = Slaick._send_wip_message(context, client, payload, messages)

            # Ensure messages fit within the context window
            messages, num_context_tokens, max_context_tokens = messages_within_context_window(
                messages,
                context.get("OPENAI_MODEL", ""),
                int(MAX_RESPONSE_TOKENS),
                context.get("OPENAI_FUNCTION_CALL_MODULE_NAME", ""),
            )

            # Handle cases where the message is too long
            if num_context_tokens > max_context_tokens:
                Slaick._handle_long_message(
                    client,
                    context,
                    wip_reply,
                    num_context_tokens,
                    max_context_tokens,
                )
            else:
                # Process the OpenAI response
                Slaick._process_litellm_response(
                    context,
                    client,
                    payload,
                    messages,
                    wip_reply,
                    user_id,  # type: ignore
                )

        except openai.APITimeoutError:
            # Handle timeout errors
            Slaick._handle_timeout(client, context, wip_reply, openai_api_key)  # type: ignore
        except Exception as e:
            # Handle general errors
            Slaick._handle_error(client, context, wip_reply, logger, str(e), openai_api_key)  # type: ignore

    @staticmethod
    def _get_messages_in_context(
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

    @staticmethod
    def _prepare_messages(
        context: BoltContext, messages_in_context: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Prepare messages for the LiteLLM API, including system message and formatting user messages.

        Args:
            context (BoltContext): The Bolt context object.
            messages_in_context (List[Dict[str, Any]]): The list of messages in the context.

        Returns:
            List[Dict[str, Any]]: The prepared messages for the LiteLLM API.
        """
        messages = []
        system_text = get_system_text(SYSTEM_TEXT, TRANSLATE_MARKDOWN, context)
        messages.append({"role": "system", "content": system_text})

        # Process each message in the context
        for reply in messages_in_context:
            msg_user_id = reply.get("user")
            reply_text = redact_string(reply.get("text", ""))
            content = [
                {
                    "type": "text",
                    "text": f"<@{msg_user_id}>: "
                    + format_message_content_for_llm(reply_text, TRANSLATE_MARKDOWN),
                }
            ]

            # Handle files content if present and allowed
            if reply.get("bot_id") is None and is_bot_able_to_access_files(context):
                maybe_new_content = get_file_content_if_exists(
                    context=context,
                    bot_token=context.bot_token,  # type: ignore
                    files=reply.get("files", []),
                    content=content,
                    logger=context.logger,
                )
                if maybe_new_content:
                    content = maybe_new_content

            # Add formatted message to the list
            messages.append(
                {
                    "content": content,
                    "role": ("assistant" if msg_user_id == context.bot_user_id else "user"),
                }
            )
        return messages

    @staticmethod
    def _send_wip_message(
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

    @staticmethod
    def _handle_long_message(
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

    @staticmethod
    def _process_litellm_response(
        context: BoltContext,
        client: WebClient,
        payload: dict,
        messages: List[Dict[str, Any]],
        wip_reply: dict,
        user_id: str,
    ):
        """
        Process the litellm API response and update the Slack message accordingly.
        """
        # Get the litellm response stream
        stream = Slaick._get_litellm_stream(context, messages)

        # Check if a new reply has come in since we started processing
        latest_replies = client.conversations_replies(
            channel=context.channel_id,  # type: ignore
            ts=wip_reply.get("ts"),  # type: ignore
            include_all_metadata=True,
            limit=1000,
        )
        if latest_replies.get("messages", [])[-1]["ts"] != wip_reply["message"]["ts"]:  # type: ignore
            # A new reply has come in, so abandon this one
            client.chat_delete(
                channel=context.channel_id,  # type: ignore
                ts=wip_reply["message"]["ts"],
            )
            return

        # Consume the LiteLLM stream and update the Slack message
        Slaick._consume_litellm_stream(
            client=client,
            context=context,
            wip_reply=wip_reply,
            messages=messages,
            stream=stream,
            timeout_seconds=TIMEOUT_SECONDS,
            translate_markdown=TRANSLATE_MARKDOWN,
        )

    @staticmethod
    def _get_litellm_stream(
        context: BoltContext, messages: List[Dict[str, Any]]
    ) -> litellm.completion:
        """Get the litellm response stream."""
        return start_litellm_stream(
            model=context["OPENAI_MODEL"],
            temperature=context["OPENAI_TEMPERATURE"],
            messages=messages,
            user=context.user_id,  # type: ignore
            function_call_module_name=context.get("OPENAI_FUNCTION_CALL_MODULE_NAME", ""),
        )

    @staticmethod
    def _update_slack_message(
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
                return Slaick._send_long_message_in_chunks(
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

    @staticmethod
    def _send_long_message_in_chunks(
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

    @staticmethod
    def _handle_timeout(
        client: WebClient,
        context: BoltContext,
        wip_reply: Optional[dict],
        openai_api_key: str,
    ):
        """Handle timeout errors."""
        if wip_reply:
            text = (
                (wip_reply.get("message", {}).get("text", "") or "")
                + "\n\n"
                + translate(
                    openai_api_key=openai_api_key,
                    context=context,
                    text=TIMEOUT_ERROR_MESSAGE,
                )
            )
            client.chat_update(
                channel=context.channel_id,  # type: ignore
                ts=wip_reply["message"]["ts"],
                text=text,
            )

    @staticmethod
    def _consume_litellm_stream(
        client: WebClient,
        context: BoltContext,
        wip_reply: dict,
        messages: List[Dict[str, Any]],
        stream: litellm.completion,
        timeout_seconds: int,
        translate_markdown: bool,
    ):
        """
        Consume the LiteLLM stream and update the Slack message.

        This method processes a streaming response from LiteLLM, updating a
        Slack message in real-time. It handles function calls embedded in
        the stream and processes message chunks to ensure the message
        does not exceed Slack's length limitations.

        Parameters:
        - client: WebClient instance for Slack API interactions.
        - context: BoltContext containing contextual information like user and channel IDs.
        - wip_reply: Dictionary maintaining the in-progress reply message.
        - messages: List of message dictionaries to be augmented with the assistant's reply.
        - stream: LiteLLM completion stream, providing the assistant's response in chunks.
        - timeout_seconds: Integer representing the timeout duration for the streaming process.
        - translate_markdown: Boolean flag indicating whether markdown should be translated.

        Raises:
        - TimeoutError: If the processing exceeds the allocated time.

        Behavior:
        - The method processes the LiteLLM stream in chunks, updating the Slack message as it receives responses.
        - It handles function calls embedded in the stream, executing the functions and updating the message accordingly.
        - The method ensures that the message does not exceed Slack's length limitations by splitting it into chunks.
        """
        start_time = time.time()
        assistant_reply = {"role": "assistant", "content": ""}
        messages.append(assistant_reply)
        word_count = 0
        threads = []
        function_call = {"name": "", "arguments": ""}
        loading_character = " ... :writing_hand:"
        try:
            for chunk in stream:  # type: ignore
                spent_seconds = time.time() - start_time
                if timeout_seconds < spent_seconds:
                    raise TimeoutError()

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                if delta.content is not None:
                    word_count += 1
                    assistant_reply["content"] += delta.get("content")
                    if word_count >= 20:

                        def update_message():
                            Slaick._update_slack_message(
                                client,
                                context,
                                wip_reply,
                                assistant_reply,
                                messages,
                                loading_character,
                                translate_markdown,
                                logger,
                            )

                        thread = threading.Thread(target=update_message)
                        thread.daemon = True
                        thread.start()
                        threads.append(thread)
                        word_count = 0
                elif delta.get("function_call") is not None:  # type: ignore
                    if assistant_reply["content"] == "":
                        for k in function_call.keys():
                            function_call[k] += delta["function_call"].get(k) or ""  # type: ignore
                        assistant_reply["function_call"] = function_call  # type: ignore

            for t in threads:
                try:
                    if t.is_alive():
                        t.join()
                except Exception:
                    pass

            if function_call["name"] != "":
                Slaick._handle_function_call(
                    client,
                    context,
                    wip_reply,
                    messages,
                    function_call,
                    timeout_seconds - (time.time() - start_time),
                    translate_markdown,
                )
            else:
                Slaick._update_slack_message(
                    client,
                    context,
                    wip_reply,
                    assistant_reply,
                    messages,
                    "",
                    translate_markdown,
                    logger,
                )

        finally:
            for t in threads:
                try:
                    if t.is_alive():
                        t.join()
                except Exception:
                    pass
            try:
                if stream is not None and hasattr(stream, "close"):
                    stream.close()
            except Exception:
                pass

    @staticmethod
    def _handle_error(
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

    @staticmethod
    def _is_bot_mentioned_in_thread(client: WebClient, context: BoltContext, payload: dict) -> bool:
        """Check if the bot is mentioned in the thread."""
        thread_ts = payload.get("thread_ts")
        if not thread_ts:
            return False
        parent_message = find_parent_message(client, context.channel_id, thread_ts)
        return parent_message is not None and is_this_app_mentioned(context, parent_message)

    @staticmethod
    def _handle_function_call(
        client: WebClient,
        context: BoltContext,
        wip_reply: dict,
        messages: List[Dict[str, Any]],
        function_call: Dict[str, str],
        remaining_timeout: float,
        translate_markdown: bool,
    ):
        """Handle function calls from the OpenAI response."""
        function_call_module_name = context.get("OPENAI_FUNCTION_CALL_MODULE_NAME", "")
        function_call_module = import_module(function_call_module_name)  # type: ignore
        function_to_call = getattr(function_call_module, function_call["name"])
        function_args = json.loads(function_call["arguments"])
        function_response = function_to_call(**function_args)
        function_message = {
            "role": "function",
            "name": function_call["name"],
            "content": function_response,
        }
        messages.append(function_message)

        messages_within_context_window(
            messages,
            context.get("OPENAI_MODEL", ""),
            int(MAX_RESPONSE_TOKENS),
            function_call_module_name,
        )
        sub_stream = start_litellm_stream(
            model=context.get("OPENAI_MODEL"),  # type: ignore
            temperature=context.get("OPENAI_TEMPERATURE"),  # type: ignore
            messages=messages,
            user=context.user_id,  # type: ignore
            function_call_module_name=function_call_module_name,
        )
        Slaick._consume_litellm_stream(
            client=client,
            context=context,
            wip_reply=wip_reply,
            messages=messages,
            stream=sub_stream,
            timeout_seconds=int(remaining_timeout),
            translate_markdown=translate_markdown,
        )
