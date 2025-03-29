Collection of utility functions and classes designed to enhance Python projects.
The library is organized into several modules, including logging, cache, translation models,
client interactions, data manipulation with pandas, and general-purpose functions.

# Supported Python Versions

Python >= 3.10

# Unsupported Python Versions

Python < 3.10

## Installation

You can install `utils-b-infra` using pip:

```bash
pip install utils-b-infra
```

To include the translation utilities:

```bash
pip install utils-b-infra[translation]
````

## Structure

The library is organized into the following modules:

1. logging.py: Utilities for logging with SlackAPI and writing to a file.
2. cache.py: Utilities for caching data in memory, Redis or MongoDB.
3. ai.py: Utilities for working with AI models, such as token count, tokenization, and text generation.
4. translation.py: Utilities for working with translation APIs (Supported Google Translate and DeepL).
5. services.py: Services-related utilities, such as creating google service.
6. pandas.py: Utilities for working with pandas dataframes, (df cleaning, insertion into databases...).
7. generic.py: Miscellaneous utilities that don't fit into the other specific categories (retry, run in thread,
   validate, etc.).

## Usage

Here are few examples, for more details, please refer to the docstrings in the source code.

Logging Utilities

```python
from utils_b_infra.logging import SlackLogger

logger = SlackLogger(project_name="your-project-name", slack_token="your-slack-token", default_channel_id="channel-id")
logger.info("This is an info message")
logger.error(exc=Exception, header_message="Header message appears above the exception message in the Slack message")
```

Cache Utilities

```python
from time import sleep
from utils_b_infra.cache import Cache, CacheConfig

cache_config = CacheConfig(
   cache_type="RedisCache",
   redis_host="host",
   redis_port=6379,
   redis_password="password"
)


@cache.cached(60, namespace="test1", sliding_expiration=False)
def hello(arg1: int, arg2: str) -> dict:
   sleep(5)
   data = {
      "orders": [
         "668abd233909666c44033913",
         "668ab5167a0b54248b044b14",
         "668aad6f1cd076a89e0f4e87",
         "668ac1ff28065eadb408a9b5",
         "668ac23eb6bb7b781f069567"
      ],
      "stats": {
         "1": 10,
         "2": 22
      }
   }
   print(data)
   return data


if __name__ == "__main__":
   hello(arg1=1, arg2="test")
```

Services Utilities

```python
from utils_b_infra.services import get_google_service

google_sheet_service = get_google_service(
   google_token_path='common/google_token.json',
   google_credentials_path='common/google_credentials.json',
   service_name='sheets'
)
```

Pandas Utilities

```python
import pandas as pd
from utils_b_infra.pandas import clean_dataframe, insert_df_into_db_in_chunks

from connections import sqlalchemy_client  # Your database connection client

df = pd.read_csv("data.csv")
clean_df = clean_dataframe(df)
with sqlalchemy_client.connect() as db_connection:
    insert_df_into_db_in_chunks(
        df=clean_df,
        table_name="table_name",
        conn=db_connection,
        if_exists='append',
        truncate_table=True,
        index=False,
        dtype=None,
        chunk_size=20_000
    )
```

Translation Utilities
To use the translation utilities, you need to install the translation extras and set up the necessary environment
variables for Google Translate:

```bash
pip install utils-b-infra[translation]
```

```python
import os
from utils_b_infra.translation import TextTranslator

# Set up Google Cloud credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'path/to/google_service_account.json'

deepl_api_key = 'your-deepl-api-key'
languages = {
   'ru': 'https://ru.example.com',
   'ar': 'https://ar.example.com',
   'de': 'https://de.example.com',
   'es': 'https://es.example.com',
   'fr': 'https://fr.example.com',
   'uk': 'https://ua.example.com'
}
google_project_id = 'your-google-project-id'

translator = TextTranslator(deepl_api_key=deepl_api_key, languages=languages, google_project_id=google_project_id)

text_to_translate = "Hello, world!"
translations = translator.get_translations(
   text=text_to_translate,
   source_language="en",
   target_langs=["ru", "ar", "de"],
   engine="google"
)

for lang, translated_text in translations.items():
   print(f"{lang}: {translated_text}")
```

Generic Utilities

```python
from utils_b_infra.generic import retry_with_timeout, validate_numeric_value, run_threaded, Timer


@retry_with_timeout(retries=3, timeout=5)
def fetch_data(arg1, arg2):
    # function logic here
    pass


with Timer() as t:
    fetch_data("arg1", "arg2")
print(t.seconds_taken)  # Output: Time taken to run fetch_data function (in seconds)
print(t.minutes_taken)  # Output: Time taken to run fetch_data function (in minutes)

run_threaded(fetch_data, arg1="arg1", arg2="arg2")

is_valid = validate_numeric_value(123)
print(is_valid)  # Output: True
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Changelog

For all the changes and version history, see the [CHANGELOG](CHANGELOG.md).

