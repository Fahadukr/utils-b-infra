import hashlib
import json
import logging
import os
import traceback
from datetime import datetime, date, time
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import sys
from slack_sdk import WebClient as SlackWebClient


def safe_serialize(obj):
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode()
        except Exception:
            return str(obj)
    if isinstance(obj, (Decimal, UUID, Path, Enum, complex)):
        return str(obj)
    if isinstance(obj, Exception):
        return str(obj)
    if hasattr(obj, '__dict__'):
        return vars(obj)
    return str(obj)


class SlackLogLevel(str, Enum):
    INFO = "good"
    WARNING = "warning"
    ERROR = "danger"
    DEBUG = "#CCCCCC"  # light gray

    @property
    def prefix(self) -> str:
        if self == SlackLogLevel.DEBUG:
            return "*DEBUG*: "
        elif self == SlackLogLevel.WARNING:
            return "*WARNING*: "
        return ""


class BotIconEmoji(str, Enum):
    """
    Enum for Slack icon emojis.
    The SLACK_LOGGER_EMOJI is a reference to an environment variable
        that can be set to customize the emoji used by the Slack logger.
        If not set, it will default to `:robot_face:`
    """
    TECHNOLOGIST = ":technologist:"
    ROBOT_FACE = ":robot_face:"
    SLACK_LOGGER_EMOJI = "SLACK_LOGGER_EMOJI"  # symbolic reference, value will be os.getenv("SLACK_LOGGER_EMOJI")


class SlackLogger:
    def __init__(
            self,
            project_name: str,
            slack_token: str,
            subprocess: str = None,
            add_subprocess_to_info: bool = True,
            default_channel_id: str = None,
            info_channel_id: str = None,
            error_channel_id: str = None,
            icon_emoji: str | BotIconEmoji = None,
    ) -> None:
        """
        Initialize the SlackLogger instance.

        :param project_name: name of the project for logging purposes (used in the username of the slack bot)
        :param slack_token: Slack API token to authenticate the Slack client.
        :param subprocess: (Optional) Name of the subprocess for logging context. This will be prefixed to messages.
        :param add_subprocess_to_info: Whether to include the subprocess name in info messages. Default to True.
        :param default_channel_id: default Slack channel ID to send messages to if no specific channel is provided.
        :param info_channel_id: default Slack channel ID for info messages.
        :param error_channel_id: default Slack channel ID for error messages.
        :param icon_emoji:
            - str (custom emoji), e.g. ":robot_face:"
            - BotIconEmoji Enum member, e.g. BotIconEmoji.TECHNOLOGIST
            If neither is provided, defaults to:
              - BotIconEmoji.SLACK_LOGGER_EMOJI (if set via environment),
              - otherwise BotIconEmoji.TECHNOLOGIST.
        :raises ValueError: If no channel IDs are provided.
        """
        if not any([default_channel_id, info_channel_id, error_channel_id]):
            raise ValueError("At least one channel ID must be provided.")

        self._project_name = project_name
        self._slack_client = SlackWebClient(slack_token)

        self._default_channel_id = default_channel_id or info_channel_id or error_channel_id
        self._info_channel_id = info_channel_id
        self._error_channel_id = error_channel_id

        self._provided_icon_emoji = icon_emoji
        self._icon_emoji = self._get_bot_emoji()

        self._last_messages = []
        self._subprocess = subprocess
        self._add_subprocess_to_info = add_subprocess_to_info

    def _get_bot_emoji(self) -> str:
        """
        Determines the emoji to use for the Slack bot.
        if icon_emoji is set to BotIconEmoji.SLACK_LOGGER_EMOJI,
            it will check for the environment variable `SLACK_LOGGER_EMOJI`
            if not set, it will fallback to the default `:robot_face:`.
        :return: str representation of the emoji to use for the Slack bot.
        """
        env_emoji = os.getenv("SLACK_LOGGER_EMOJI")

        if self._provided_icon_emoji == BotIconEmoji.SLACK_LOGGER_EMOJI:
            if env_emoji:
                return env_emoji
            logging.warning("Warning: SLACK_LOGGER_EMOJI environment variable is not set, "
                            "falling back to default icon :robot_face:")
            return BotIconEmoji.ROBOT_FACE.value

        if self._provided_icon_emoji:
            if isinstance(self._provided_icon_emoji, BotIconEmoji):
                self._provided_icon_emoji = self._provided_icon_emoji.value
            return self._provided_icon_emoji

        return env_emoji or BotIconEmoji.TECHNOLOGIST.value

    def clone(self,
              *,
              subprocess: str = None,
              add_subprocess_to_info: bool = True,
              default_channel_id: str = None,
              info_channel_id: str = None,
              error_channel_id: str = None,
              icon_emoji: str | BotIconEmoji = None
              ) -> "SlackLogger":
        """
        Clone the current SlackLogger instance, allowing for different configurations.
        """
        return SlackLogger(
            project_name=self._project_name,
            slack_token=self._slack_client.token,
            subprocess=subprocess or self._subprocess,
            add_subprocess_to_info=add_subprocess_to_info if add_subprocess_to_info is not None else self._add_subprocess_to_info,
            default_channel_id=default_channel_id or self._default_channel_id,
            info_channel_id=info_channel_id or self._info_channel_id,
            error_channel_id=error_channel_id or self._error_channel_id,
            icon_emoji=icon_emoji or self._icon_emoji
        )

    def _resolve_channel(self, provided_channel_id: str, is_error: bool) -> str:
        """
        Resolve the channel ID to use for posting messages.
        """
        if is_error:
            return provided_channel_id or self._error_channel_id or self._default_channel_id
        return provided_channel_id or self._info_channel_id or self._default_channel_id

    def _hash_error(self, error_text: str) -> str:
        """
        Generate a hash for the error text to avoid duplicate messages.
        """
        return hashlib.md5(error_text.encode()).hexdigest()

    @staticmethod
    def _serialize_context_data(context_data: Any) -> str:
        """
        Serialize context data to a string format for logging.
        """
        if isinstance(context_data, str):
            return context_data

        return json.dumps(context_data, indent=4, default=safe_serialize, ensure_ascii=False)

    def _post_to_slack(self,
                       message: str,
                       level: SlackLogLevel,
                       subprocess: str = None,
                       error_text: str = None,
                       channel_id: str = None,
                       user_name: str = None,
                       color: str = None) -> None:
        """ Post ordinary messages as warning or error messages as danger
        :param message: message to post
        :param level: message level (error, warning, info)
        :param subprocess: Optional subprocess name to include in the message.
        :param error_text: error text to post
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param user_name: Optional username to use for the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        """

        message = level.prefix + message if message else level.prefix

        subprocess_name = subprocess or self._subprocess

        if level == SlackLogLevel.INFO and not self._add_subprocess_to_info:
            """
            Do not include subprocess in info messages unless explicitly included in the constructor.
            This allows cleaner info messages without subprocess context.
            """
            subprocess_name = None

        message = f"[{subprocess_name}]: {message}" if subprocess_name else message

        attachments = {
            "text": message,
            "fallback": message,
            "color": color or level.value
        }

        if level == SlackLogLevel.ERROR and error_text:
            attachments.update({
                "text": error_text,
                "pretext": message,
                "fallback": message,
                "title": "Error traceback"
            })

        self._slack_client.chat_postMessage(
            channel=self._resolve_channel(channel_id, is_error=level == SlackLogLevel.ERROR),
            attachments=[attachments],
            username=user_name or self._project_name.lower(),
            icon_emoji=self._icon_emoji
        )

    def _write_error_log_and_post(self,
                                  error_text: str,
                                  message: str,
                                  subprocess: str = None,
                                  channel_id: str = None,
                                  user_name: str = None,
                                  color: str = None):
        self._last_messages.append({
            'date': datetime.now().replace(microsecond=0),
            'message_hash': self._hash_error(error_text)
        })

        if not os.path.exists("logs"):
            os.makedirs("logs")

        with open(f"logs/{self._project_name}.log", "w", encoding='utf-8') as file:
            file.write(f'\n\nDATE: {datetime.now().replace(microsecond=0)}: ERROR in {message}\n\n')
            e_type, e_val, e_tb = sys.exc_info()
            traceback.print_exception(e_type, e_val, e_tb, file=file)

        truncated = error_text[-8000:] if len(error_text) > 8000 else error_text
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.ERROR,
            subprocess=subprocess,
            error_text=truncated,
            channel_id=channel_id,
            user_name=user_name,
            color=color
        )

    def error(self,
              exc: Exception,
              subprocess: str = None,
              header_message: str = None,
              context_data: Any = None,
              channel_id: str = None,
              user_name: str = None,
              color: str = None) -> None:
        """
        :param exc: Exception object appears as red text in slack.
        :param subprocess: Optional subprocess name to include in the message.
        :param header_message: bold text appears above the error message - usually the place where the error occurred
        :param context_data: Additional data to be added to the error message like variables, API json payload, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param user_name: Optional username to use for the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        error_text = ''.join(traceback.format_exception(None, exc, exc.__traceback__))
        if context_data:
            context_data = self._serialize_context_data(context_data)

            if header_message:
                header_message += f"\nContext data:\n{context_data}"
            else:
                header_message = f"Context data:\n{context_data}"

        error_hash = self._hash_error(error_text)
        two_minutes_ago = datetime.now() - timedelta(minutes=2)
        self._last_messages = [
            item for item in self._last_messages if item['date'] > two_minutes_ago
        ]
        if error_hash in [item['message_hash'] for item in self._last_messages]:
            return

        self._write_error_log_and_post(
            error_text=error_text,
            message=header_message,
            subprocess=subprocess,
            channel_id=channel_id,
            user_name=user_name,
            color=color
        )

    def info(self,
             message: str,
             subprocess: str = None,
             context_data: Any = None,
             channel_id: str = None,
             user_name: str = None,
             color: str = None) -> None:
        """
        Post an info message to Slack with green color.
        :param message: message appears as an info message in slack without error
        :param subprocess: Optional subprocess name to include in the message.
        :param context_data: Additional data to be added to the info message like variables, API json payload, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param user_name: Optional username to use for the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        if context_data:
            context_data = self._serialize_context_data(context_data)
            message += f"\n\nContext data:\n{context_data}"

        self._post_to_slack(
            message=message,
            level=SlackLogLevel.INFO,
            subprocess=subprocess,
            channel_id=channel_id,
            user_name=user_name,
            color=color
        )

    def warning(self,
                message: str,
                subprocess: str = None,
                context_data: Any = None,
                channel_id: str = None,
                user_name: str = None,
                color: str = None) -> None:
        """
        Post a warning message to Slack with yellow color.
        :param message: message appears as a warning message in slack without error
        :param subprocess: Optional subprocess name to include in the message.
        :param context_data: Additional data to be added to the warning message like variables, API json payload, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param user_name: Optional username to use for the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        if context_data:
            context_data = self._serialize_context_data(context_data)
            message += f"\n\nContext data:\n{context_data}"
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.WARNING,
            subprocess=subprocess,
            channel_id=channel_id,
            user_name=user_name,
            color=color
        )

    def debug(self,
              message: str,
              subprocess: str = None,
              context_data: Any = None,
              channel_id: str = None,
              user_name: str = None,
              color: str = None) -> None:
        """
        Post a debug message to Slack with gray color.
        :param message: message appears as a debug message in slack without error
        :param subprocess: Optional subprocess name to include in the message.
        :param context_data: Additional data to be added to the debug message like variables, API json payload, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param user_name: Optional username to use for the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        if context_data:
            context_data = self._serialize_context_data(context_data)
            message += f"\n\nContext data:\n{context_data}"
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.DEBUG,
            subprocess=subprocess,
            channel_id=channel_id,
            user_name=user_name,
            color=color
        )
