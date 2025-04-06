import hashlib
import os
import traceback
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import sys
from slack_sdk import WebClient as SlackWebClient


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
            print("Warning: SLACK_LOGGER_EMOJI environment variable is not set, "
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

    def _post_to_slack(self,
                       message: str,
                       level: SlackLogLevel,
                       error_text: str = None,
                       channel_id: str = None,
                       subprocess: str = None,
                       color: str = None) -> None:
        """ Post ordinary messages as warning or error messages as danger
        :param message: message to post
        :param level: message level (error, warning, info)
        :param error_text: error text to post
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        """

        message = level.prefix + message

        subprocess_name = subprocess or self._subprocess

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
            username=f"{self._project_name.lower()}-logger",
            icon_emoji=self._icon_emoji
        )

    def _write_error_log_and_post(self,
                                  error_text: str,
                                  message: str,
                                  channel_id: str = None,
                                  subprocess: str = None,
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
            error_text=truncated,
            channel_id=channel_id,
            subprocess=subprocess,
            color=color
        )

    def error(self,
              exc: Exception,
              header_message: str,
              error_additional_data: Any = None,
              channel_id: str = None,
              subprocess: str = None,
              color: str = None) -> None:
        """
        :param exc: Exception object appears as red text in slack.
        :param header_message: bold text appears above the error message - usually the place where the error occurred
        :param error_additional_data: Additional data to be added to the error message like variables, etc.
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param subprocess: Optional subprocess name to include in the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        error_text = ''.join(traceback.format_exception(None, exc, exc.__traceback__))
        if error_additional_data:
            error_text += f"\n\nAdditional data:\n{error_additional_data}"

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
            channel_id=channel_id,
            subprocess=subprocess,
            color=color
        )

    def info(self,
             message: str,
             channel_id: str = None,
             subprocess: str = None,
             color: str = None) -> None:
        """
        Post an info message to Slack with green color.
        :param message: message appears as an info message in slack without error
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :param subprocess: Optional subprocess name to include in the message.
        :return: None
        """
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.INFO,
            channel_id=channel_id,
            subprocess=subprocess,
            color=color
        )

    def warning(self,
                message: str,
                channel_id: str = None,
                subprocess: str = None,
                color: str = None) -> None:
        """
        Post a warning message to Slack with yellow color.
        :param message: message appears as a warning message in slack without error
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param subprocess: Optional subprocess name to include in the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.WARNING,
            channel_id=channel_id,
            subprocess=subprocess,
            color=color
        )

    def debug(self,
              message: str,
              channel_id: str = None,
              subprocess: str = None,
              color: str = None) -> None:
        """
        Post a debug message to Slack with gray color.
        :param message: message appears as a debug message in slack without error
        :param channel_id: Slack channel ID to send the message to, if different from the default
        :param subprocess: Optional subprocess name to include in the message.
        :param color: Optional HEX or Slack-supported color ('good', 'warning', 'danger').
        :return: None
        """
        self._post_to_slack(
            message=message,
            level=SlackLogLevel.DEBUG,
            channel_id=channel_id,
            subprocess=subprocess,
            color=color
        )
