from importlib import import_module
from typing import Dict, List, Optional, Tuple, Union

import litellm
from slack_bolt import BoltContext

from lib.env import MAX_RESPONSE_TOKENS

# TODO Use create_litellm_client

FUNCTION_CALL_TOKEN_COUNT = 100  # Placeholder value, adjust based on your function call complexity


def create_litellm_client(context: BoltContext):
    litellm.REPEATED_STREAMING_CHUNK_LIMIT = (
        100  # Prevents infinite loop in case of repeated streaming chunks
    )
    if context.get("OPENAI_API_KEY"):
        litellm.api_base = context.get("OPENAI_API_BASE")
        litellm.api_key = context.get("OPENAI_API_KEY")
        litellm.organization = context.get("OPENAI_ORG_ID")
    elif context.get("ANTHROPIC_API_KEY"):
        litellm.api_base = context.get("ANTHROPIC_API_BASE")
        litellm.api_key = context.get("ANTHROPIC_API_KEY")
        litellm.organization = context.get("ANTHROPIC_ORG_ID")
    else:
        raise ValueError("No API key found")


def messages_within_context_window(
    messages: List[Dict[str, Union[str, Dict[str, str]]]],
    model: str,
    max_tokens: int = int(MAX_RESPONSE_TOKENS),
    function_call_module_name: str = "",
) -> Tuple[List[Dict[str, Union[str, Dict[str, str]]]], int, int]:
    """
    Adjusts a list of messages to ensure they fit within the token context window
    for a specified model, taking into account the maximum response tokens and
    optionally the complexity of function calls.

    Parameters:
    - messages (List[Dict[str, Union[str, Dict[str, str]]]]): The list of messages to be checked.
    - model (str): The name of the model to check against.
    - max_tokens (int, optional): The maximum number of tokens allowed for the response. Defaults
        to the value of MAX_RESPONSE_TOKENS.
    - function_call_module_name (str, optional): The name of the module for function calls whose
        complexity might affect the token budget. Defaults to an empty string.

    Returns:
    - Tuple[List[Dict[str, Union[str, Dict[str, str]]]], int, int]: A tuple containing:
        - The adjusted list of messages that fit within the context window.
        - The number of tokens used by the remaining messages.
        - The maximum number of context tokens available given the model and constraints.
    """
    # Get the context length for the specified model
    max_context_tokens = litellm.model_cost[model]["max_input_tokens"] - max_tokens - 1

    if function_call_module_name:
        # Assuming a fixed token count for function call, adjust as needed
        max_context_tokens -= FUNCTION_CALL_TOKEN_COUNT

    num_context_tokens = 0

    while True:
        # Calculate total tokens for all messages
        num_tokens = sum(
            litellm.token_counter(model=model, text=str(message)) for message in messages
        )

        if num_tokens <= max_context_tokens:
            break

        # Remove the oldest message that is not a system message
        removed = False
        for i, message in enumerate(messages):
            if message["role"] in ("user", "assistant", "function"):
                num_context_tokens = num_tokens
                del messages[i]
                removed = True
                break

        if not removed:
            # If we can't remove any more messages, break the loop
            break

    # Final token count after removals
    num_context_tokens = sum(
        litellm.token_counter(model=model, text=str(message)) for message in messages
    )

    return messages, num_context_tokens, max_context_tokens


def make_synchronous_litellm_call(
    *,
    model: str,
    temperature: float,
    messages: List[Dict[str, Union[str, Dict[str, str]]]],
    user: str,
    timeout_seconds: int,
) -> Dict:
    """
    Makes a synchronous call to the LiteLLM API to generate a completion.

    Parameters:
    - model (str): The model to use for the completion.
    - temperature (float): Sampling temperature; higher values make the output more random, while
        lower values make it more deterministic.
    - messages (List[Dict[str, Union[str, Dict[str, str]]]]): A list of messages that serve as the
        prompt for the completion.
    - user (str): The user ID making the request.
    - timeout_seconds (int): The time limit for the call in seconds.

    Returns:
    - Dict: The API response containing the completion result.
    """
    return litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=MAX_RESPONSE_TOKENS,
        user=user,
        timeout=timeout_seconds,
    )


def start_litellm_stream(
    *,
    model: str,
    temperature: float,
    messages: List[Dict[str, Union[str, Dict[str, str]]]],
    user: str,
    function_call_module_name: Optional[str],
):
    """
    Initiates a streaming response from the LiteLLM API.

    Parameters:
    - model (str): The model to use for the completion.
    - temperature (float): Sampling temperature; higher values make the output more random, while
        lower values make it more deterministic.
    - messages (List[Dict[str, Union[str, Dict[str, str]]]]): A list of messages that serve as the
        prompt for the completion.
    - user (str): The user ID making the request.
    - function_call_module_name (Optional[str]): The name of the module for function calls whose
        functions might affect the generation process. If None, no functions are used.

    Returns:
    - ModelResponse: A response object containing the generated completion and associated metadata.
    """
    kwargs = {}
    if function_call_module_name is not None:
        kwargs["functions"] = import_module(function_call_module_name).functions

    return litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=MAX_RESPONSE_TOKENS,
        user=user,
        stream=True,
        **kwargs,
    )
