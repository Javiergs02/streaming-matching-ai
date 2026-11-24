import json
from typing import Union
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from .config_models import YT_Credentials

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtubepartner",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
]

def load_yt_credentials(path: str) -> Union[YT_Credentials, service_account.Credentials]:
    """
    Loads YouTube credentials from JSON file.
    Supports both Google Cloud Service Account keys (type='service_account')
    and OAuth 2.0 user tokens (client_id, refresh_token).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Direct Service Account JSON
    if data.get("type") == "service_account":
        return service_account.Credentials.from_service_account_info(
            data,
            scopes=YOUTUBE_SCOPES
        )

    # 2. OAuth 2.0 User Tokens
    return YT_Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_url=data.get("token_uri") or "https://oauth2.googleapis.com/token",
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or YOUTUBE_SCOPES
    )

def _get_google_auth(creds_data: Union[YT_Credentials, service_account.Credentials]):
    if isinstance(creds_data, (service_account.Credentials, Credentials)):
        return creds_data

    google_creds = Credentials(
        token=creds_data.token,
        refresh_token=creds_data.refresh_token,
        token_uri=creds_data.token_url,
        client_id=creds_data.client_id,
        client_secret=creds_data.client_secret,
        scopes=creds_data.scopes
    )
    
    if not google_creds.valid:
        if google_creds.expired and google_creds.refresh_token:
            google_creds.refresh(Request())
            
    return google_creds

def get_youtube_client(creds_data: Union[YT_Credentials, service_account.Credentials]):
    auth = _get_google_auth(creds_data)
    return build('youtube', 'v3', credentials=auth)

def get_youtube_analytics_client(creds_data: Union[YT_Credentials, service_account.Credentials]):
    auth = _get_google_auth(creds_data)
    return build('youtubeAnalytics', 'v2', credentials=auth)

def load_drive_credentials(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _get_drive_google_auth(creds_dict: dict) -> service_account.Credentials:
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    return service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes
    )

def get_google_drive_client(creds_dict: dict):
    auth = _get_drive_google_auth(creds_dict)
    return build('drive', 'v3', credentials=auth, cache_discovery=False)
