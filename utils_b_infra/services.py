import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

DEFAULT_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/admin.directory.user",
    'https://mail.google.com/',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
]

GOOGLE_DEFAULT_VERSIONS = {
    'sheets': 'v4',
    'drive': 'v3',
    'docs': 'v1',
    'gmail': 'v1',
}


def get_google_service(
        service_name: str = 'sheets',
        version: str = None,
        google_scopes: list[str] = None,
        google_token_path: str = 'common/google_token.json',
        google_credentials_path: str = 'common/google_credentials.json',
) -> build:
    if service_name not in GOOGLE_DEFAULT_VERSIONS:
        raise NotImplementedError(f"Service {service_name} is not supported")

    if not google_scopes:
        google_scopes = DEFAULT_GOOGLE_SCOPES
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists(google_token_path):
        creds = Credentials.from_authorized_user_file(google_token_path, google_scopes)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                google_credentials_path, google_scopes)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(google_token_path, 'w') as token:
            token.write(creds.to_json())

    if not version:
        version = GOOGLE_DEFAULT_VERSIONS[service_name]

    return build(service_name, version, credentials=creds)
