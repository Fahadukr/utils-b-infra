import hashlib
import os
import traceback
from datetime import datetime, timedelta
from typing import Any

import sys
from slack_sdk import WebClient as SlackWebClient


class SlackApi:
    def __init__(self,
                 project_name: str,
                 slack_token: str,
                 default_channel_id: str,
                 info_channel_id: str = None,
                 error_channel_id: str = None) -> None:
        """
        :param project_name: Name of the project to be used in the logger.
        :param slack_token: Slack token for authentication.
        :param default_channel_id: Fallback channel used if no specific info/error channel is provided.
        :param info_channel_id: Channel used for info or warning messages (color: yellow),
                                if not provided, default_channel_id is used.
        :param error_channel_id: Channel used for error messages (color: red)
                                if not provided, default_channel_id is used.
        """
        self._client = SlackWebClient(slack_token)
        self._project_name = project_name
        self._default_channel_id = default_channel_id
        self._info_channel_id = info_channel_id
        self._error_channel_id = error_channel_id

    def _resolve_channel(self, provided_channel_id: str, is_error: bool) -> str:
        """
        Resolve the channel ID to use for posting messages.
        :param provided_channel_id: The channel ID provided by the user.
        :param is_error: Boolean indicating if the message is an error message.
        :return: The resolved channel ID.
        """
        if is_error:
            return provided_channel_id or self._error_channel_id or self._default_channel_id
        return provided_channel_id or self._info_channel_id or self._default_channel_id

    def post_message(self,
                     message: str,
                     error_text: str = None,
                     channel_id: str = None,
                     color: str = None) -> None:
        """ Post ordinary messages as warning or error messages as danger
        :param message: message to post
        :param error_text: error text to post
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        """
        attachments = {
            "text": message,
            "fallback": message,
            "color": "danger" if error_text else (color or "warning")
        }

        if error_text:
            pre_text = f"[{self._project_name}]: {message}"
            attachments.update({
                "text": error_text,
                "pretext": pre_text,
                "fallback": pre_text,
                "title": "Error traceback"
            })

        self._client.chat_postMessage(
            channel=self._resolve_channel(channel_id, is_error=True if error_text else False),
            attachments=[attachments],
            username=f"{self._project_name.lower()}-logger",
            icon_emoji=":robot_face:"
        )


class SlackLogger:
    def __init__(self,
                 project_name: str,
                 slack_token: str,
                 default_channel_id: str,
                 info_channel_id: str = None,
                 error_channel_id: str = None) -> None:
        """
        :param project_name: Name of the project to be used in the logger.
        :param slack_token: Slack token for authentication.
        :param default_channel_id: Fallback channel used if no specific info/error channel is provided.
        :param info_channel_id: Channel used for info or warning messages (color: yellow),
                                if not provided, default_channel_id is used.
        :param error_channel_id: Channel used for error messages (color: red)
                                if not provided, default_channel_id is used.
        """
        self._project_name = project_name
        self.slacker = SlackApi(
            project_name=project_name,
            slack_token=slack_token,
            default_channel_id=default_channel_id,
            info_channel_id=info_channel_id,
            error_channel_id=error_channel_id
        )
        self._last_messages = []

    @staticmethod
    def _hash_error(error_text):
        return hashlib.md5(error_text.encode()).hexdigest()

    def _save_and_post_to_slack(self, error_text: str, message: str, channel_id: str):
        self._last_messages.append({
            'date': datetime.now().replace(microsecond=0),
            'message_hash': self._hash_error(error_text)
        })

        truncated_error_text = error_text[-8000:] if len(error_text) > 8000 else error_text
        self.slacker.post_message(message=message, error_text=truncated_error_text, channel_id=channel_id)
        # create logs directory if not exists
        if not os.path.exists("logs"):
            os.makedirs("logs")
        with open(f"logs/{self._project_name}.log", "w", encoding='utf-8') as file:
            file.write(f'\n \n DATE: {datetime.now().replace(microsecond=0)}: ERROR in {message} \n \n')
            e_type, e_val, e_tb = sys.exc_info()
            traceback.print_exception(e_type, e_val, e_tb, file=file)

    def error(self,
              exc: Exception,
              header_message: str,
              error_additional_data: Any = None,
              channel_id: str = None,
              color: str = None) -> None:
        """
        :param exc: Exception object appears as red text in slack.
        :param header_message: bold text appears above the error message - usually the place where the error occurred
        :param error_additional_data: Additional data to be added to the error message like variables, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        error_text = ''.join(traceback.format_exception(None, exc, exc.__traceback__))
        if error_additional_data:
            error_text += f"\n\n\nAdditional data:\n{error_additional_data}"
        error_text_hash = self._hash_error(error_text)

        two_minutes_ago = datetime.now() - timedelta(minutes=2)
        self._last_messages = [item for item in self._last_messages if item.get('date') > two_minutes_ago]

        last_messages_hashes = [item.get('message_hash') for item in self._last_messages]

        if error_text_hash in last_messages_hashes:
            return

        self._save_and_post_to_slack(
            error_text=error_text,
            message=header_message,
            channel_id=channel_id
        )

    def info(self, message: str, channel_id: str = None, color: str = None) -> None:
        """
        :param message: message appears as a warning message in slack without error
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        self.slacker.post_message(message=message, channel_id=channel_id, color=color)
