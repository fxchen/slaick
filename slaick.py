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
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.web import WebClient

vendor_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "vendor/chatgptinslack"))
sys.path.insert(0, vendor_dir)

from lib import env, formatting, llm, slack
from plugins.base_plugin import PluginManager
from vendor.chatgptinslack.app.i18n import translate
from vendor.chatgptinslack.app.sensitive_info_redaction import redact_string
from vendor.chatgptinslack.app.slack_constants import TIMEOUT_ERROR_MESSAGE
from vendor.chatgptinslack.app.slack_ops import find_parent_message, is_this_app_mentioned


class Slaick:
    MESSAGE_SUBTYPES_TO_SKIP = ["message_changed", "message_deleted"]
    llm_client = llm.LLMClient()
    plugin_manager = None

    @classmethod
    def initialize(cls, plugins=None):
        cls.plugin_manager = PluginManager()

        if plugins:
            for plugin in plugins:
                cls.plugin_manager.register_plugin(plugin)

    def __init__(self, plugins=None):
        if Slaick.plugin_manager is None:
            self.initialize(plugins)

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
    def setup_middleware(app: App):
        """
        Set up all middleware for the Slack app.
        """
        app.middleware(Slaick.before_authorize)
        app.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=2))

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
            and slack.is_bot_mentioned_in_thread(client, context, payload)
        ):
            Slaick._process_message(context, payload, client, logger)

    @classmethod
    def _process_message(
        cls,
        context: BoltContext,
        payload: dict,
        client: WebClient,
        logger: logging.Logger,
    ):
        """
        Process a message for both app mentions and direct messages.
        This method handles the core logic of interacting with the LiteLLM API and responding in Slack.
        """

        # Check if LLM API key is configured
        llm_api_key = env.LLM_API_KEY
        if not llm_api_key and (env.PROVIDER == "bedrock" and env.AWS_ACCESS_KEY_ID is None):
            client.chat_postMessage(
                channel=context.channel_id,  # type: ignore
                text="To use this app, please configure your LLM API key first",
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
                and not slack.is_bot_mentioned(context, payload)
            ):
                return

            # Retrieve relevant messages for context
            messages_in_context = slack.get_messages_in_context(
                context, client, payload, is_in_dm_with_bot, thread_ts
            )

            # Return if there are no messages AND it's not a new conversation
            if not messages_in_context and not Slaick._is_new_conversation(payload):
                return

            # Prepare messages for calling LiteLLM
            messages = Slaick._prepare_messages(context, messages_in_context)
            user_id = context.actor_user_id or context.user_id

            # Send a "work in progress" message to Slack
            wip_reply = slack.send_wip_message(context, client, payload, messages)

            # Ensure messages fit within the context window
            messages, num_context_tokens, max_context_tokens = (
                cls.llm_client.messages_within_context_window(
                    messages,
                    context.get("OPENAI_FUNCTION_CALL_MODULE_NAME", ""),
                )
            )

            # Handle cases where the message is too long
            if num_context_tokens > max_context_tokens:
                slack.handle_long_message(
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
            slack.handle_timeout(client, context, wip_reply, env.LLM_API_KEY)  # type: ignore
        except Exception as e:
            # Handle general errors
            slack.handle_error(client, context, wip_reply, logger, str(e), env.LLM_API_KEY)  # type: ignore

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
        system_text = formatting.get_system_text(env.SYSTEM_TEXT, env.TRANSLATE_MARKDOWN, context)
        messages.append({"role": "system", "content": system_text})

        # Process each message in the context
        for reply in messages_in_context:
            msg_user_id = reply.get("user")
            reply_text = redact_string(reply.get("text", ""))
            content = [
                {
                    "type": "text",
                    "text": f"<@{msg_user_id}>: "
                    + formatting.format_message_content_for_llm(reply_text, env.TRANSLATE_MARKDOWN),
                }
            ]

            # process message using plugins
            is_last_message = reply == messages_in_context[-1]
            plugin_content = Slaick.plugin_manager.process_message(context, reply, context.logger, is_last_message)
            content.extend(plugin_content)

            messages.append(
                {
                    "content": content,
                    "role": ("assistant" if msg_user_id == context.bot_user_id else "user"),
                }
            )
        return messages

    @classmethod
    def _process_litellm_response(
        cls,
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
        stream = cls.llm_client.get_completion(messages, stream=True)

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
            timeout_seconds=env.TIMEOUT_SECONDS,
            translate_markdown=env.TRANSLATE_MARKDOWN,
        )

    @classmethod
    def _get_litellm_stream(cls, messages: List[Dict[str, Any]]) -> litellm.completion:
        """Get the litellm response stream."""
        return cls.llm_client.get_completion(messages, stream=True)

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

    @classmethod
    def _consume_litellm_stream(
        cls,
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
                            slack.update_slack_message(
                                client,
                                context,
                                wip_reply,
                                assistant_reply,
                                messages,
                                loading_character,
                                translate_markdown,
                                context.logger,
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
                slack.update_slack_message(
                    client,
                    context,
                    wip_reply,
                    assistant_reply,
                    messages,
                    "",
                    translate_markdown,
                    context.logger,
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

    @classmethod
    def _handle_function_call(
        cls,
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

        cls.llm_client.messages_within_context_window(
            messages,
            function_call_module_name,
        )

        sub_stream = cls.llm_client.get_completion(messages, stream=True)

        cls._consume_litellm_stream(
            client=client,
            context=context,
            wip_reply=wip_reply,
            messages=messages,
            stream=sub_stream,
            timeout_seconds=int(remaining_timeout),
            translate_markdown=translate_markdown,
        )
