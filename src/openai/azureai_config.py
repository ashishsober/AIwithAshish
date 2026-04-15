
import os
from dotenv import load_dotenv
from openai import AzureOpenAI
load_dotenv()


endpoint = "https://hcep-open-ai-as-a-svc.openai.azure.com/"
model_name = "gpt-4o-mini"
DEPLOYMENT = "gpt-4o-mini"

subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = "2024-12-01-preview"

def get_azure_client():
    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=subscription_key,
    )
    return client