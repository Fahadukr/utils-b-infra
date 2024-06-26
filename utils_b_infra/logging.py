import hashlib
import os
import traceback
from datetime import datetime, timedelta

import sys
from slack_sdk import WebClient as SlackWebClient


class SlackApi:
    def __init__(self, project_name: str, slack_token: str, slack_channel_id: str):
        self.client = SlackWebClient(slack_token)
        self.project_name = project_name
        self.slack_channel_id = slack_channel_id

    def post_message(self, message: str, error_text: str = None):
        """ Post ordinary messages as warning or error messages as danger """
        attachments = {
            "text": message,
            "fallback": message,
            "color": "warning"
        }

        if error_text:
            pre_text = f"[{self.project_name}]: {message}"
            attachments.update({
                "text": error_text,
                "pretext": pre_text,
                "fallback": pre_text,
                "title": "Error traceback",
                "color": "danger"
            })

        self.client.chat_postMessage(channel=self.slack_channel_id,
                                     attachments=[attachments],
                                     username=f"{self.project_name.lower()}-logger",
                                     icon_emoji=":robot_face:")


class SlackLogger:
    def __init__(self, project_name: str, slack_token: str, slack_channel_id: str) -> None:
        self.project_name = project_name
        self.slacker = SlackApi(
            project_name=project_name,
            slack_token=slack_token,
            slack_channel_id=slack_channel_id
        )
        self.last_messages = []

    @staticmethod
    def hash_error(error_text):
        return hashlib.md5(error_text.encode()).hexdigest()

    def save_and_post_to_slack(self, error_text, message):
        self.last_messages.append({
            'date': datetime.now().replace(microsecond=0),
            'message_hash': self.hash_error(error_text)
        })

        truncated_error_text = error_text[-8000:] if len(error_text) > 8000 else error_text
        self.slacker.post_message(message=message, error_text=truncated_error_text)
        # create logs directory if not exists
        if not os.path.exists("logs"):
            os.makedirs("logs")
        with open(f"logs/{self.project_name}.log", "w", encoding='utf-8') as file:
            file.write(f'\n \n DATE: {datetime.now().replace(microsecond=0)}: ERROR in {message} \n \n')
            e_type, e_val, e_tb = sys.exc_info()
            traceback.print_exception(e_type, e_val, e_tb, file=file)

    def error(self, exc: Exception, header_message: str, error_additional_data=None) -> None:
        """
        :param exc: Exception object appears as red text in slack.
        :param header_message: bold text appears above the error message - usually the place where the error occurred
        :param error_additional_data: Additional data to be added to the error message like variables, etc.
        :return: None
        """
        error_text = ''.join(traceback.format_exception(None, exc, exc.__traceback__))
        if error_additional_data:
            error_text += f"\n\n\nAdditional data:\n{error_additional_data}"
        error_text_hash = self.hash_error(error_text)

        two_minutes_ago = datetime.now() - timedelta(minutes=2)
        self.last_messages = [item for item in self.last_messages if item.get('date') > two_minutes_ago]

        last_messages_hashes = [item.get('message_hash') for item in self.last_messages]

        if error_text_hash in last_messages_hashes:
            return

        self.save_and_post_to_slack(error_text, header_message)

    def info(self, message: str) -> None:
        """
        :param message: message appears as a warning message in slack without error
        :return: None
        """
        self.slacker.post_message(message=message)
