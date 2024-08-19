# Slaick


## Usage


```
# Set up environment variables
SLACK_APP_TOKEN="xapp-..." \
SLACK_BOT_TOKEN="xoxb-..." \
OPENAI_API_KEY="sk-..." \
TRANSLATE_MARKDOWN="true" \
REDACTION_ENABLED="true" \
OPENAI_ORG_ID="org-..." \
python main.py
```

## Configuration

### Essential Flags

- SLACK_BOT_TOKEN
- SLACK_APP_TOKEN

### Feature Flags:

- USE_SLACK_LANGUAGE: Determines if Slack-specific language features should be used. Default is "true".
- SLACK_APP_LOG_LEVEL: Specifies the log level for the Slack app. Default is "DEBUG".
- TRANSLATE_MARKDOWN: Flag to enable or disable Markdown translation. Default is "false".
- REDACTION_ENABLED: Flag to enable or disable data redaction. Default is "false".
- IMAGE_FILE_ACCESS_ENABLED: Allows toggling the image file access feature. Default is "false".

### Redaction Patterns:

- REDACT_EMAIL_PATTERN: Regex pattern for redacting email addresses. Default pattern matches standard email formats.
- REDACT_PHONE_PATTERN: Regex pattern for redacting phone numbers. Default pattern matches typical phone number formats.
- REDACT_CREDIT_CARD_PATTERN: Regex pattern for redacting credit card numbers. Default pattern matches standard credit card formats.
- REDACT_SSN_PATTERN: Regex pattern for redacting Social Security Numbers (SSNs). Default pattern matches typical SSN formats.
- REDACT_USER_DEFINED_PATTERN: User-defined regex pattern for redaction, with a default that never matches anything.

## Inspirations

Inspired by and forked from @seratch/[ChatGPT-in-Slack](https://github.com/seratch/ChatGPT-in-Slack/)
