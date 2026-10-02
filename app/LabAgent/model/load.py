import os

from langchain_aws import ChatBedrockConverse

# Scaffold default: global inference profile for Claude Sonnet 4.5.
# https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
# Override with LAB_MODEL_ID if your account cannot invoke it
# (e.g. LAB_MODEL_ID=amazon.nova-micro-v1:0).
MODEL_ID = os.environ.get("LAB_MODEL_ID", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")


def load_model() -> ChatBedrockConverse:
    """Get Bedrock model client using IAM credentials."""
    return ChatBedrockConverse(
        model=MODEL_ID,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
