import ast
import json
import re

import openai
import tiktoken
from utils_b_infra.generic import retry_with_timeout

AI_NO_ANSWER_PHRASES = ["Sorry, I", "AI language model",
                        "cannot provide", "without any input",
                        "There is no raw text", "There is no text",
                        "Please provide "]


def count_tokens_per_text(text: str) -> int:
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    tokens = len(tokens)
    return tokens


def calculate_openai_price(text_: str, output_tokens: int, model: str) -> float:
    """
    Calculate the price for the OpenAI API based on the input text and the output tokens.
    :return: The total price in USD.
    """
    # Input token counts
    input_token_count = count_tokens_per_text(text_)

    # Price (USD) per model per 1M tokens (input, output)
    prices = {
        'gpt-4o-2024-08-06': (2.5, 10),
        'gpt-4o': (5, 15),
        'gpt-4o-2024-05-13': (5, 15),
        'gpt-4-0125-preview': (10, 30),
        'gpt-4-1106-preview': (10, 30),
        'gpt-4-1106-vision-preview': (10, 30),
        'gpt-4': (30, 60),
        'gpt-4-32k': (60, 120),
        'gpt-3.5-turbo-0125': (0.5, 1.5),
        'gpt-3.5-turbo-instruct': (1.5, 2)
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

    @retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2)
    def generate_text_embeddings(self, content, model='text-embedding-ada-002'):
        """
        This function takes a string content as input and computes its GPT-3 embeddings using the specified engine.
        :return: A list containing the GPT-3 embeddings for the input content.
        """
        content = content.encode(encoding='ASCII', errors='ignore').decode()  # fix any UNICODE errors
        content = content.replace("\n", " ")
        emb = self.openai_client.embeddings.create(input=[content], model=model)
        return emb.data[0].embedding

    @retry_with_timeout(retries=3, timeout=200, initial_delay=10, backoff=2)
    def generate_ai_response(self,
                             prompt,
                             user_text,
                             answer_tokens=3000,
                             temperature=0.7,
                             gpt_model='gpt-4o',
                             parse_json_response=False,
                             **kwargs) -> str | dict:
        """
        parse_json_response: if True, the function will try to extract JSON from the response
        **kwargs: additional parameters for OpenAI API like
        response_format={"type": "json_object"}
        """
        if not user_text or (isinstance(user_text, str) and len(user_text) < 20):
            return ''

        if not isinstance(user_text, str):
            user_text = json.dumps(user_text)

        if gpt_model in ('gpt-4o-2024-08-06', 'gpt-4o-mini', 'gpt-4-1106-preview') and parse_json_response:
            kwargs.setdefault('response_format', {"type": "json_object"})

        ai_text = self.openai_client.chat.completions.create(model=gpt_model,
                                                             messages=[
                                                                 {"role": "system", "content": prompt},
                                                                 {"role": "user", "content": user_text}
                                                             ],
                                                             temperature=temperature,
                                                             max_tokens=answer_tokens,
                                                             top_p=1,
                                                             frequency_penalty=0,
                                                             presence_penalty=0,
                                                             **kwargs)

        ai_text = ai_text.choices[0].message.content.strip()
        if ai_text and parse_json_response:
            ai_text = extract_json_from_text(ai_text)
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
