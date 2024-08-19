# Slaick

Slaick is a configurable Slack bot that integrates with various AI providers. Use it to bootstrap your own AI powered tool. It offers features like markdown translation, data redaction, and file access.

<p align="center">
  <kbd>
    <img width="634" alt="Slaick bot interface" src="https://github.com/user-attachments/assets/f556fbca-57b3-4866-b840-c5249f62a58e">
  </kbd>
</p>

## Quick Start

The default AI provider is OpenAI. To get started quickly:

1. Copy the `sample.env` file to `.env`:
   ```
   cp sample.env .env
   ```
2. Open the `.env` file and set your API keys and other configuration options.
3. Run the application:
   ```
   ./scripts/start.sh
   ```

<!-- 
Note: If you're using OpenAI (the default provider), make sure to set the `OPENAI_API_KEY` in your `.env` file.
To use an alternate provider, set the `PROVIDER` variable in your `.env` file to the desired provider (e.g., `PROVIDER=anthropic` or `PROVIDER=bedrock`). Make sure to set the corresponding API keys for the chosen provider. -->


## 
<details open>
<summary>Slack bot Settings</summary>

- `SLACK_BOT_TOKEN`: Your Slack bot token (**required**)
- `SLACK_APP_TOKEN`: Your Slack app token (**required**)

</details>

<details open>
<summary>Feature Settings</summary>

- `USE_SLACK_LANGUAGE`: Enables Slack-specific language features (default: `true`)
- `SLACK_APP_LOG_LEVEL`: Sets the log level for the Slack app (default: `"DEBUG"`)
- `TRANSLATE_MARKDOWN`: Enables/disables Markdown translation (default: `false`)
- `REDACTION_ENABLED`: Enables/disables data redaction (default: `false`)
- `FILE_ACCESS_ENABLED`: Toggles file access feature (default: `false`)

</details>

<details open>
<summary>Global Parameters</summary>

<!-- - `PROVIDER`: AI provider to use (default: `"openai"`) -->
- `TIMEOUT_SECONDS`: Request timeout in seconds (default: `30`)
- `TEMPERATURE`: AI model temperature setting (default: `1.0`)
- `SYSTEM_TEXT`: System prompt for the AI model (default: `[env.py](https://github.com/fxchen/slaick/blob/main/lib/env.py)`)
- `MAX_RESPONSE_TOKENS`: Maximum tokens in AI response (default: `1024`)

</details>

## AI Provider Configuration

<details open>
<summary>OpenAI</summary>
<!-- (Default Provider) -->

- `OPENAI_API_KEY`: Your OpenAI API key (**required**)
- `OPENAI_MODEL`: OpenAI model to use (default: `"gpt-4o"`)
- `OPENAI_IMAGE_GENERATION_MODEL`: Model for image generation (default: `"dall-e-3"`)
- `OPENAI_API_BASE`: OpenAI API base URL (optional)
- `OPENAI_API_VERSION`: API version (optional)
- `OPENAI_DEPLOYMENT_ID`: Deployment ID (optional)
- `OPENAI_ORG_ID`: Organization ID (optional)

</details>

<!-- <details>
<summary>Anthropic</summary>

- `ANTHROPIC_API_KEY`: Your Anthropic API key (**required**)
- `ANTHROPIC_MODEL`: Anthropic model to use (default: `"claude-3-5-sonnet-20240620"`)
- `ANTHROPIC_API_BASE`: Anthropic API base URL (optional)

</details>

<details>
<summary>Amazon Bedrock</summary>

- `AWS_ACCESS_KEY_ID`: AWS access key ID (**required**)
- `AWS_SECRET_ACCESS_KEY`: AWS secret access key (**required**)
- `BEDROCK_ASSUME_ROLE`: AWS role for Bedrock access (**alternative auth**)
- `AWS_REGION_NAME`: AWS region (default: `"us-east-1"`)
- `BEDROCK_MODEL`: Bedrock model to use (default: `bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0`)
- `BEDROCK_IMAGE_MODEL`: Bedrock model for image generation (default: `bedrock/stability.stable-diffusion-xl-v0`)
- `BEDROCK_API_BASE`: Bedrock API base URL (optional)

</details> -->

## Data Redaction

When enabled, the application can redact sensitive information using regex patterns. To customize redaction patterns, set the corresponding environment variables:

<details>
<summary>Redaction Patterns</summary>

- `REDACT_EMAIL_PATTERN`: For email addresses
- `REDACT_PHONE_PATTERN`: For phone numbers
- `REDACT_CREDIT_CARD_PATTERN`: For credit card numbers
- `REDACT_SSN_PATTERN`: For Social Security Numbers (SSNs)
- `REDACT_USER_DEFINED_PATTERN`: Custom user-defined pattern

</details>

## Roadmap

Here's what's coming soon:

- Amazon Bedrock Integration: Seamless integration with Amazon's AI services.
- Anthropic Integration: Full support for Anthropic's AI models.
- Image Generation: Create images directly from your Slack conversations.

## Inspirations

This project is inspired by and uses code from @seratch's [ChatGPT-in-Slack](https://github.com/seratch/ChatGPT-in-Slack/).
