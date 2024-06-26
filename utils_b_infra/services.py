import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

DEFAULT_GOOGLE_SCOPES = ['https://www.googleapis.com/auth/drive',
                         'https://www.googleapis.com/auth/spreadsheets',
                         'https://www.googleapis.com/auth/drive.file']


def get_google_service(google_token_path: str = 'common/google_token.json',
                       google_credentials_path: str = 'common/google_credentials.json',
                       service_name: str = 'sheets',
                       google_scopes: list[str] = None):
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

    if service_name == 'sheets':
        service = build(service_name, 'v4', credentials=creds)
    else:
        raise ValueError(f"Service {service_name} is not supported")

    return service
