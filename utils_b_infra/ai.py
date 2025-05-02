import ast
import base64
import io
import json
import logging
import os
import re
from typing import List, Union, Any

import openai
import requests
import tiktoken
from PIL import Image
from openai._types import NOT_GIVEN
from pdf2image import convert_from_bytes
from pydub import AudioSegment
from utils_b_infra.generic import retry_with_timeout


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

    @retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2)
    def generate_text_embeddings(self, content, model="text-embedding-3-small"):
        content = content.encode(encoding='ASCII', errors='ignore').decode()
        content = content.replace("\n", " ")
        emb = self.openai_client.embeddings.create(input=content, model=model)
        return emb.data[0].embedding

    @retry_with_timeout(retries=3, timeout=200, initial_delay=10, backoff=2)
    def generate_ai_response(
            self,
            prompt: str,
            user_text: Any = None,
            gpt_model: str = 'gpt-4.1',
            max_output_tokens: int = NOT_GIVEN,
            temperature: float = 0.7,
            json_mode: bool = False,
            **kwargs
    ) -> dict | str:
        """
        Generate AI response for the provided user text.
        To process file or audio, use process_file or transcribe_audio_file.

        :param prompt: Prompt to be used for the AI model
        :param user_text: Text or JSON object to be used as input
        :param gpt_model: Model to be used for the AI response
        :param max_output_tokens: Max output tokens
        :param temperature: Temperature for the AI model
        :param json_mode: If True, the response will be in JSON format
        :param kwargs: Additional parameters for the AI model, supports legacy 'answer_tokens'
        :return: AI response as a string or JSON object
        """

        # Handle legacy parameter
        if 'answer_tokens' in kwargs:
            logging.warning("[DEPRECATION] `answer_tokens` is deprecated. Use `max_output_tokens` instead.")
            if max_output_tokens is NOT_GIVEN:
                max_output_tokens = kwargs['answer_tokens']

            # remove kwargs['answer_tokens']
            del kwargs['answer_tokens']

        if user_text and not isinstance(user_text, str):
            user_text = json.dumps(user_text)

        # Build the new "input" list
        input_list = [{
            "role": "developer" if gpt_model in ('o3-mini', 'o3', 'o4-mini') else "system",
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
        request_kwargs = {}
        if json_mode:
            request_kwargs["text"] = {
                "format": {
                    "type": "json_object"
                }
            }

        if gpt_model in ('o3-mini', 'o3', 'o4-mini'):
            # Reasoning models
            reasoning_effort = kwargs.get('reasoning_effort')
            if not reasoning_effort or reasoning_effort not in ('high', 'medium', 'low'):
                raise ValueError(
                    'reasoning_effort is required for reasoning models and must be one of: high, medium, low')

            ai_resp = self.openai_client.responses.create(
                model=gpt_model,
                input=input_list,
                reasoning={"effort": reasoning_effort},
                store=False,
                **request_kwargs
            )
        else:
            ai_resp = self.openai_client.responses.create(
                model=gpt_model,
                input=input_list,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
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
        return os.path.splitext(path)[-1].lstrip(".").lower()

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
                                json_mode: bool = False
                                ) -> dict | str:

        messages = [{"role": "system", "content": system_prompt}]
        messages.append(self._build_image_prompt(images))

        gpt_answer = self.openai_client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"} if json_mode else NOT_GIVEN,
            temperature=temperature
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
                     json_mode: bool = False
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
            json_mode=json_mode
        )

    def transcribe_audio_file(self,
                              url: str = None,
                              file_path: str = None,
                              model: str = "gpt-4o-transcribe",
                              prompt: str = None,
                              ) -> str:
        """
        Transcribe an audio file (e.g., .oga, .mp3, .wav) to text using OpenAI's transcription model.
        Supports input from a URL or a local file. If both are provided, URL takes precedence.
        Converts to mp3 only if format is not directly supported by OpenAI.

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

        if audio_format not in {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"}:  # Supported formats by OpenAI
            # Convert to MP3 using pydub if not supported
            audio = AudioSegment.from_file(audio_bytes, format=audio_format)
            audio_bytes = io.BytesIO()
            audio.export(audio_bytes, format="mp3")
            audio_bytes.seek(0)
            audio_bytes.name = "converted.mp3"
        else:
            # Ensure the buffer is ready for reading
            audio_bytes.seek(0)
            audio_bytes.name = f"audio.{audio_format}"

        transcription = self.openai_client.audio.transcriptions.create(
            model=model,
            file=audio_bytes,
            response_format="text",
            prompt=prompt if prompt else NOT_GIVEN,
        )

        return transcription
