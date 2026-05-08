import ast
import base64
import inspect
import io
import json
import os
import re
from typing import List, Union, Any, Literal
from urllib.parse import urlparse

import openai
import requests
import tiktoken
from PIL import Image
from openai._types import NOT_GIVEN
from pdf2image import convert_from_bytes
from pydub import AudioSegment
from utils_b_infra.generic import retry_with_timeout

TRANSCRIPTION_AUDIO_CHANNELS = 1
TRANSCRIPTION_AUDIO_FRAME_RATE = 16000
TRANSCRIPTION_AUDIO_BITRATE = "64k"
TRANSCRIPTION_AUDIO_FORMAT = "mp3"


def count_tokens_per_text(text: str) -> int:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    tokens = len(tokens)
    return tokens


def calculate_openai_price(text: str, output_tokens: int, model: str) -> float:
    """
    Calculate the price for the OpenAI API based on the input text and the output tokens.
    :return: The total price in USD.
    """
    # Input token counts
    input_token_count = count_tokens_per_text(text)

    # Price (USD) per model per 1M tokens (input, output)
    prices = {
        'gpt-4.5-preview': (75, 150),
        'gpt-4o': (2.5, 10),
        'gpt-4o-audio-preview': (2.5, 10),
        'gpt-4o-realtime-preview': (5, 20),
        'gpt-4o-mini': (0.15, 0.60),
        'gpt-4o-mini-audio-preview': (0.15, 0.60),
        'gpt-4o-mini-realtime-preview': (0.60, 2.40),
        'o1': (15, 60),
        'o1-pro': (150, 600),
        'o3-mini': (1.1, 4.4),
        'o1-mini': (1.1, 4.4),
        'gpt-4o-mini-search-preview': (0.15, 0.60),
        'gpt-4o-search-preview': (5.00, 20.00),
    }

    # Calculate price
    price_per_million_input, price_per_million_output = prices[model]
    total_price = ((input_token_count * price_per_million_input) + (
            output_tokens * price_per_million_output)) / 1_000_000

    return total_price


def extract_json_from_text(text_):
    # Regular expression to match the outermost curly braces and their contents
    match = re.search(r'\{.*\}', text_, re.DOTALL)
    if match:
        return match.group(0)
    return None


class TextGenerator:
    def __init__(self, openai_client: openai.Client):
        self.openai_client = openai_client

    # -------------- TEXT-ONLY FUNCTIONALITY --------------

    @staticmethod
    def _parse_json(ai_text):
        for parser in (json.loads, ast.literal_eval):
            try:
                return parser(ai_text)
            except Exception as e:
                last_exception = e
                continue
        print('Error loading JSON from AI text:', last_exception)
        raise ValueError('Invalid JSON format') from last_exception

    @staticmethod
    def _supports_api_param(api_method: Any, param_name: str) -> bool:
        try:
            return param_name in inspect.signature(api_method).parameters
        except (TypeError, ValueError):
            return False

    @retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2)
    def generate_text_embeddings(self, content, model="text-embedding-3-small"):
        content = content.encode(encoding='ASCII', errors='ignore').decode()
        content = content.replace("\n", " ")
        emb = self.openai_client.embeddings.create(input=content, model=model)
        return emb.data[0].embedding

    @retry_with_timeout(retries=3, timeout=300, initial_delay=10, backoff=2)
    def generate_ai_response(
            self,
            prompt: str,
            user_text: Any = None,
            gpt_model: str = 'gpt-5',
            max_output_tokens: int = NOT_GIVEN,
            temperature: float = 0.5,
            verbosity: Literal["low", "medium", "high"] = "medium",
            reasoning_effort: Literal["minimal", "low", "medium", "high"] = "medium",
            store: bool = False,
            json_mode: bool = False
    ) -> dict | str:
        """
        Generate AI response for the provided user text.
        To process file or audio, use process_file or transcribe_audio_file.

        models 5 and o require reasoning_effort and verbosity parameters,
            and they don't support temperature and max_output_tokens.
        models 4.x support temperature and max_output_tokens,
            but don't support reasoning_effort and verbosity parameters.

        :param prompt: Prompt to be used for the AI model
        :param user_text: Text or JSON object to be used as input
        :param gpt_model: Model to be used for the AI response
        :param max_output_tokens: Max output tokens
        :param temperature: Temperature for the AI model
        :param verbosity: Verbosity level for reasoning models
        :param reasoning_effort: Reasoning effort for reasoning models
        :param store: If True, the response will be stored in the OpenAI API
        :param json_mode: If True, the response will be in JSON format
        :return: AI response as a string or JSON object
        """

        if user_text and not isinstance(user_text, str):
            user_text = json.dumps(user_text)

        # Build the new "input" list
        input_list = [{
            "role": "developer" if gpt_model.startswith('gpt-5') or gpt_model.startswith('o') else "system",
            "content": [
                {"type": "input_text", "text": prompt}
            ]
        }]
        if user_text:
            input_list.append({
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_text}
                ]
            })

        # Output format for JSON mode:
        request_kwargs = {
            "text": {
                "format": {
                    "type": "json_object" if json_mode else "text"
                },
            }
        }
        if gpt_model.startswith('gpt-5'):
            request_kwargs["text"]["verbosity"] = verbosity

        if gpt_model.startswith('gpt-5') or gpt_model.startswith('o'):
            # Reasoning models
            ai_resp = self.openai_client.responses.create(
                model=gpt_model,
                input=input_list,
                reasoning={"effort": reasoning_effort},
                store=store,
                **request_kwargs
            )
        else:
            # gpt 4 models
            ai_resp = self.openai_client.responses.create(
                model=gpt_model,
                input=input_list,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                store=store,
                **request_kwargs
            )

        ai_text = ai_resp.output_text

        if ai_text and json_mode:
            ai_text = self._parse_json(ai_text)

        ai_text = "" if ai_text == "''" else ai_text

        return ai_text

    # -------------- IMAGE & FILE HANDLING FUNCTIONALITY --------------

    @staticmethod
    def _get_file_extension(path: str) -> str:
        return os.path.splitext(urlparse(path).path)[-1].lstrip(".").lower()

    @staticmethod
    def _download_file_into_bytes(url: str) -> Union[io.BytesIO, None]:
        response = requests.get(url)
        if response.status_code == 200:
            return io.BytesIO(response.content)
        print(f"Failed to download file. Status code: {response.status_code}")
        return None

    @staticmethod
    def _load_local_file_into_bytes(file_path: str) -> Union[io.BytesIO, None]:
        try:
            with open(file_path, "rb") as f:
                return io.BytesIO(f.read())
        except Exception as e:
            print(f"Failed to read local file: {e}")
            return None

    @staticmethod
    def _pdf_page_to_image_from_bytes(pdf_data: Union[bytes, io.BytesIO]) -> List[Image.Image]:
        if isinstance(pdf_data, io.BytesIO):
            pdf_data = pdf_data.getvalue()
        return convert_from_bytes(pdf_data)

    @staticmethod
    def _encode_image(image: Image.Image, width: int = None, height: int = None) -> str:
        if width and height:
            image = image.resize((width, height), Image.ANTIALIAS)
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _build_image_prompt(self, images: List[Image.Image]) -> dict:
        content_items = [{"type": "image_url", "image_url": {
            "url": f"data:image/png;base64,{self._encode_image(img)}"}} for img in images]

        return {"role": "user", "content": content_items}

    def _get_image_gpt_response(self,
                                model: str,
                                system_prompt: str,
                                images: List[Image.Image],
                                temperature: float = 0.2,
                                json_mode: bool = False,
                                store: bool = False
                                ) -> dict | str:

        messages = [{"role": "system", "content": system_prompt}]
        messages.append(self._build_image_prompt(images))

        request_kwargs = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"} if json_mode else NOT_GIVEN,
            "temperature": temperature,
        }
        if self._supports_api_param(self.openai_client.chat.completions.create, "store"):
            request_kwargs["store"] = store

        gpt_answer = self.openai_client.chat.completions.create(
            **request_kwargs
        )

        ai_text = gpt_answer.choices[0].message.content
        if ai_text and json_mode:
            try:
                ai_text = json.loads(ai_text, strict=False)
            except Exception as e:
                print('error loading json with json.loads')
                try:
                    ai_text = ast.literal_eval(ai_text)
                except Exception as e:
                    print('error loading json with ast.literal_eval')
                    raise e
        return ai_text

    def process_file(self,
                     prompt: str,
                     model: str = 'gpt-4.1',
                     url: str = None,
                     file_path: str = None,
                     temperature: float = 0.2,
                     json_mode: bool = False,
                     store: bool = False
                     ) -> dict | str:
        """
        Process text files like .pdf, .docx, .txt, etc. from a URL or local file.
        Provide either `url` or `file_path`.
        if both are provided, `url` will be used.
        """
        if url:
            ext = self._get_file_extension(url)
            file_data = self._download_file_into_bytes(url)
        elif file_path:
            ext = self._get_file_extension(file_path)
            file_data = self._load_local_file_into_bytes(file_path)
        else:
            raise ValueError("Either 'url' or 'file_path' must be provided.")

        if not file_data:
            return {}

        if ext == 'pdf':
            images = self._pdf_page_to_image_from_bytes(file_data)
        else:
            images = [Image.open(file_data).convert("RGB")]

        return self._get_image_gpt_response(
            model=model,
            system_prompt=prompt,
            images=images,
            temperature=temperature,
            json_mode=json_mode,
            store=store
        )

    def process_local_file(self,
                           prompt: str,
                           file_path: str,
                           model: str = 'gpt-4.1',
                           temperature: float = 0.2,
                           json_mode: bool = False,
                           store: bool = False
                           ) -> dict | str:
        return self.process_file(
            prompt=prompt,
            model=model,
            file_path=file_path,
            temperature=temperature,
            json_mode=json_mode,
            store=store
        )

    @staticmethod
    def _normalize_audio_for_transcription(audio_bytes: io.BytesIO, audio_format: str) -> io.BytesIO:
        """
        Decode the source media and export only its audio stream as MP3 for transcription.
        This avoids sending video containers such as MP4 directly to the transcription API.
        """
        audio_bytes.seek(0)
        source_format = audio_format or None

        try:
            audio = AudioSegment.from_file(audio_bytes, format=source_format)
        except Exception as primary_error:
            if not source_format:
                raise ValueError("Failed to decode audio file for transcription") from primary_error

            audio_bytes.seek(0)
            try:
                audio = AudioSegment.from_file(audio_bytes)
            except Exception as fallback_error:
                raise ValueError(
                    f"Failed to decode audio file for transcription as '{source_format}'"
                ) from fallback_error

        if len(audio) == 0:
            raise ValueError("Audio file contains no audio samples")

        normalized_audio = audio.set_channels(TRANSCRIPTION_AUDIO_CHANNELS)
        normalized_audio = normalized_audio.set_frame_rate(TRANSCRIPTION_AUDIO_FRAME_RATE)

        normalized_bytes = io.BytesIO()
        normalized_audio.export(
            normalized_bytes,
            format=TRANSCRIPTION_AUDIO_FORMAT,
            bitrate=TRANSCRIPTION_AUDIO_BITRATE,
        )
        normalized_bytes.seek(0)
        normalized_bytes.name = f"audio.{TRANSCRIPTION_AUDIO_FORMAT}"
        return normalized_bytes

    def transcribe_audio_file(self,
                              url: str = None,
                              file_path: str = None,
                              model: str = "gpt-4o-transcribe",
                              prompt: str = None,
                              store: bool = False,
                              ) -> str:
        """
        Transcribe an audio file (e.g., .oga, .mp3, .wav) to text using OpenAI's transcription model.
        Supports input from a URL or a local file. If both are provided, URL takes precedence.
        Extracts and normalizes the audio stream to mp3 before calling OpenAI.

        You can use a prompt to improve the quality of the transcripts generated by the Transcriptions
        example: "The following conversation is a lecture about the recent developments around OpenAI, GPT-4.5 and the future of AI."
        """
        if url:
            response = requests.get(url)
            if response.status_code != 200:
                raise Exception(f"Failed to download audio file from URL. Status code: {response.status_code}")
            audio_bytes = io.BytesIO(response.content)
            audio_format = self._get_file_extension(url)
        elif file_path:
            with open(file_path, "rb") as f:
                audio_bytes = io.BytesIO(f.read())
            audio_format = self._get_file_extension(file_path)
        else:
            raise ValueError("Either 'url' or 'file_path' must be provided.")

        # Clean and normalize extension
        audio_format = audio_format.lower()
        audio_format = 'ogg' if audio_format == 'oga' else audio_format

        audio_bytes = self._normalize_audio_for_transcription(audio_bytes, audio_format)

        request_kwargs = {
            "model": model,
            "file": audio_bytes,
            "response_format": "text",
            "prompt": prompt if prompt else NOT_GIVEN,
        }
        if self._supports_api_param(self.openai_client.audio.transcriptions.create, "store"):
            request_kwargs["store"] = store

        transcription = self.openai_client.audio.transcriptions.create(**request_kwargs)

        return transcription
