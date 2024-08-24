import logging
import os
from importlib import import_module
from typing import Dict, List, Optional, Tuple, Union

import litellm

from lib import env

# TODO Use create_litellm_client

FUNCTION_CALL_TOKEN_COUNT = 100  # Placeholder value, adjust based on your function call complexity


class LLMClient:
    def __init__(self) -> None:
        self.setup_litellm()
        self.logger: logging.Logger = logging.getLogger(__name__)

    def setup_litellm(self) -> None:
        litellm.REPEATED_STREAMING_CHUNK_LIMIT = 100
        litellm.api_base = env.LLM_API_BASE  # type: ignore
        litellm.api_key = env.LLM_API_KEY
        litellm.organization = env.LLM_ORG_ID  # type: ignore

        if env.PROVIDER == "bedrock":
            self.setup_bedrock()

    def setup_bedrock(self) -> None:
        if env.BEDROCK_ASSUME_ROLE:
            self.assume_role()

        # Set up AWS credentials for Bedrock
        os.environ["AWS_ACCESS_KEY_ID"] = env.AWS_ACCESS_KEY_ID
        os.environ["AWS_SECRET_ACCESS_KEY"] = env.AWS_SECRET_ACCESS_KEY
        os.environ["AWS_SESSION_TOKEN"] = env.AWS_SESSION_TOKEN
        os.environ["AWS_REGION_NAME"] = env.AWS_REGION_NAME
        # self.test_bedrock_connection()

    def assume_role(self) -> None:
        import boto3

        sts_client = boto3.client("sts")
        assumed_role_object = sts_client.assume_role(
            RoleArn=env.BEDROCK_ASSUME_ROLE, RoleSessionName="AssumeRoleSession"
        )
        credentials = assumed_role_object["Credentials"]

        os.environ["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
        os.environ["AWS_SESSION_TOKEN"] = credentials["SessionToken"]

    def test_bedrock_connection(self) -> None:
        try:
            response = litellm.completion(
                model=env.LLM_MODEL,
                messages=[{"role": "user", "content": "Hello, how are you?"}],
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                aws_session_token=os.environ["AWS_SESSION_TOKEN"],
                aws_region_name=os.environ["AWS_REGION_NAME"],
            )
            print("Bedrock connection successful!")
        except Exception as e:
            print(f"Error connecting to Bedrock: {str(e)}")

    def get_completion(
        self,
        messages: List[Dict[str, Union[str, Dict[str, str]]]],
        stream: bool = False,
        function_call_module_name: Optional[str] = None,
    ) -> Union[Dict, litellm.ModelResponse]:
        kwargs = {}

        if function_call_module_name is not None:
            kwargs["functions"] = import_module(function_call_module_name).functions

        if env.PROVIDER == "bedrock":
            kwargs["aws_access_key_id"] = env.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = env.AWS_SECRET_ACCESS_KEY
            kwargs["aws_region_name"] = env.AWS_REGION_NAME

        return litellm.completion(
            model=env.LLM_MODEL,
            messages=messages,
            temperature=env.TEMPERATURE,
            max_tokens=env.MAX_RESPONSE_TOKENS,
            stream=stream,
            **kwargs,
        )

    @staticmethod
    def is_model_able_to_receive_images() -> bool:
        """
        Determines if the model is able to receive images.

        Args:
            context (BoltContext): The context object containing the model information.

        Returns:
            bool: True if the model is able to receive images, False otherwise.
        """
        model = env.LLM_MODEL
        can_send_image_url = model is not None and litellm.supports_vision(model)
        return can_send_image_url

    def messages_within_context_window(
        self,
        messages: List[Dict[str, Union[str, Dict[str, str]]]],
        function_call_module_name: str = "",
    ) -> Tuple[List[Dict[str, Union[str, Dict[str, str]]]], int, int]:
        """
        Adjusts a list of messages to ensure they fit within the token context window
        for the configured model.
        """
        model = env.LLM_MODEL
        max_tokens = env.MAX_RESPONSE_TOKENS
        max_context_tokens = litellm.model_cost[model]["max_input_tokens"] - max_tokens - 1

        if function_call_module_name:
            max_context_tokens -= 100  # Assuming a fixed token count for function calls

        self.logger.info(f"Max context tokens: {max_context_tokens}")

        def count_tokens(msgs):
            return sum(litellm.token_counter(model=model, text=str(msg)) for msg in msgs)

        # Always keep the system message if present
        system_message = next((msg for msg in messages if msg["role"] == "system"), None)
        messages_to_trim = [msg for msg in messages if msg["role"] != "system"]

        initial_token_count = count_tokens(messages)
        self.logger.info(f"Initial token count: {initial_token_count}")

        while (
            count_tokens(messages_to_trim)
            + (count_tokens([system_message]) if system_message else 0)
            > max_context_tokens
        ):
            if not messages_to_trim:
                self.logger.warning(
                    "All trimmable messages removed, but still exceeding token limit."
                )
                break
            removed_message = messages_to_trim.pop(0)
            self.logger.info(f"Removed message: {removed_message['role']}")

        # Reconstruct the messages list
        final_messages = ([system_message] if system_message else []) + messages_to_trim

        final_token_count = count_tokens(final_messages)
        self.logger.info(f"Final token count: {final_token_count}")

        if final_token_count > max_context_tokens:
            self.logger.warning(
                f"Final token count ({final_token_count}) exceeds max context tokens ({max_context_tokens})"
            )

        return final_messages, final_token_count, max_context_tokens
