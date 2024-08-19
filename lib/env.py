import os

# General Settings
PROVIDER = os.environ.get("PROVIDER", "openai")
TIMEOUT_SECONDS = int(os.environ.get("TIMEOUT_SECONDS", 30))
TEMPERATURE = float(os.environ.get("TEMPERATURE", 1.0))
SYSTEM_TEXT = os.environ.get(
    "SYSTEM_TEXT",
    """
You are a bot in a slack chat room. You might receive messages from multiple people.
Format bold text *like this*, italic text _like this_ and strikethrough text ~like this~.
Slack user IDs match the regex `<@U.*?>`.
Your Slack user ID is <@{bot_user_id}>.
Each message has the author's Slack user ID prepended, like the regex `^<@U.*?>: ` followed by the message text.
Do not use headings for markdown, instead use bold text.
For section breaks, use a horizontal rule `---`.
""",
)
MAX_RESPONSE_TOKENS = os.environ.get("MAX_RESPONSE_TOKENS", 1024)

# OpenAI Configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
OPENAI_IMAGE_GENERATION_MODEL = os.environ.get("OPENAI_IMAGE_GENERATION_MODEL", "dall-e-3")
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", None)
OPENAI_DEPLOYMENT_ID = os.environ.get("OPENAI_DEPLOYMENT_ID", None)
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID", None)
OPENAI_FUNCTION_CALL_MODULE_NAME = os.environ.get("OPENAI_FUNCTION_CALL_MODULE_NAME", None)

# Anthropic Configuration
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")
ANTHROPIC_API_BASE = os.environ.get("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")
ANTHROPIC_API_VERSION = os.environ.get("ANTHROPIC_API_VERSION", None)

# Amazon Bedrock Configuration
BEDROCK_ASSUME_ROLE = os.environ.get("BEDROCK_ASSUME_ROLE")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "us-east-1")
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0")
BEDROCK_API_BASE = os.environ.get("BEDROCK_API_BASE", "https://api.bedrock.aws/v1")
BEDROCK_IMAGE_MODEL = os.environ.get(
    "BEDROCK_IMAGE_MODEL", "bedrock/stability.stable-diffusion-xl-v0"
)

# Feature Flags
USE_SLACK_LANGUAGE = os.environ.get("USE_SLACK_LANGUAGE", "true") == "true"
SLACK_APP_LOG_LEVEL = os.environ.get("SLACK_APP_LOG_LEVEL", "DEBUG")
TRANSLATE_MARKDOWN = os.environ.get("TRANSLATE_MARKDOWN", "false") == "true"
REDACTION_ENABLED = os.environ.get("REDACTION_ENABLED", "false") == "true"
FILE_ACCESS_ENABLED = os.environ.get("FILE_ACCESS_ENABLED", "false") == "true"

# Redaction patterns
REDACT_EMAIL_PATTERN = os.environ.get(
    "REDACT_EMAIL_PATTERN",
    r"\b[A-Za-z0-9.*%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
REDACT_PHONE_PATTERN = os.environ.get(
    "REDACT_PHONE_PATTERN", r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
)
REDACT_CREDIT_CARD_PATTERN = os.environ.get(
    "REDACT_CREDIT_CARD_PATTERN", r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"
)
REDACT_SSN_PATTERN = os.environ.get("REDACT_SSN_PATTERN", r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b")
# For REDACT_USER_DEFINED_PATTERN, the default will never match anything
REDACT_USER_DEFINED_PATTERN = os.environ.get("REDACT_USER_DEFINED_PATTERN", r"(?!)")
