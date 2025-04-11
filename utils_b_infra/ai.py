import ast
import base64
import io
import json
import os
import re
from typing import List, Union, Any

import openai
import requests
import tiktoken
from PIL import Image
from openai._types import NotGiven
from pdf2image import convert_from_bytes
from utils_b_infra.generic import retry_with_timeout

AI_NO_ANSWER_PHRASES = ["Sorry, I", "AI language model",
                        "cannot provide", "without any input",
                        "There is no raw text", "There is no text",
                        "Please provide "]

NOT_GIVEN = NotGiven()


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

    @retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2)
    def generate_text_embeddings(self, content, model="text-embedding-3-small"):
        content = content.encode(encoding='ASCII', errors='ignore').decode()
        content = content.replace("\n", " ")
        emb = self.openai_client.embeddings.create(input=content, model=model)
        return emb.data[0].embedding

    @retry_with_timeout(retries=3, timeout=200, initial_delay=10, backoff=2)
    def generate_ai_response(self,
                             prompt: str,
                             user_text: Any = None,
                             gpt_model: str = 'gpt-4o',
                             answer_tokens: int = None,
                             temperature: float = 0.7,
                             frequency_penalty: float = 0,
                             presence_penalty: float = 0,
                             top_p: float = 1,
                             json_mode: bool = False,
                             **kwargs) -> dict | str:

        if user_text and not isinstance(user_text, str):
            user_text = json.dumps(user_text)

        messages = [{"role": "system", "content": prompt}]
        if user_text:
            messages.append({"role": "user", "content": user_text})

        if json_mode:
            kwargs.setdefault('response_format', {"type": "json_object"})

        if gpt_model in ('o1', 'o1-mini', 'o3-mini'):
            if not kwargs.get('reasoning_effort'):
                raise ValueError('reasoning_effort is required for reasoning models')

        ai_text = self.openai_client.chat.completions.create(
            model=gpt_model,
            messages=messages,
            max_tokens=answer_tokens if answer_tokens else NOT_GIVEN,
            temperature=temperature,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            top_p=top_p,
            **kwargs
        )

        ai_text = ai_text.choices[0].message.content.strip()
        if ai_text and json_mode:
            try:
                ai_text = json.loads(ai_text, strict=False)
            except:
                try:
                    ai_text = ast.literal_eval(ai_text)
                except Exception as e:
                    print('error loading json')
                    raise e

        if isinstance(ai_text, str):
            if any(phrase.lower() in ai_text.lower() for phrase in AI_NO_ANSWER_PHRASES):
                return ''

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

    def process_file_from_url(self,
                              prompt: str,
                              url: str,
                              model: str,
                              temperature: float = 0.2,
                              json_mode: bool = False
                              ) -> dict | str:
        ext = self._get_file_extension(url)
        file_data = self._download_file_into_bytes(url)
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

    def process_local_file(self,
                           prompt: str,
                           file_path: str,
                           model: str,
                           temperature: float = 0.2,
                           json_mode: bool = False
                           ) -> dict | str:
        ext = self._get_file_extension(file_path)
        file_data = self._load_local_file_into_bytes(file_path)
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
