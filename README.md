# utils-b-infra

`utils-b-infra` is a collection of utility functions and classes designed to streamline and enhance your Python
projects. The
library is organized into several modules, each catering to different categories of utilities, including logging, client
interactions, data manipulation with pandas, and general-purpose functions.

# Supported Python Versions

Python >= 3.10

# Unsupported Python Versions

Python < 3.10

## Installation

You can install `utils-b-infra` using pip:

```bash
pip install utils-b-infra
```

## Structure

The library is organized into the following modules:

1. logging.py: Utilities for logging with SlackAPI and writing to a file.
2. ai.py: Utilities for working with AI models, such as token count, tokenization, and text generation.
3. translation.py: Utilities for working with translation APIs (Supported Google Translate and DeepL).
4. services.py: Services-related utilities, such as creating google service.
5. pandas.py: Utilities for working with pandas dataframes, (df cleaning, insertion into databases...)
6. generic.py: Miscellaneous utilities that don't fit into the other specific categories (retry, run in thread,
   validate, etc.).

## Usage

Here are few examples, for more details, please refer to the docstrings in the source code.

Logging Utilities

```python
from utils_b_infra.logging import SlackLogger

logger = SlackLogger(project_name="your-project-name", slack_token="your-slack-token", slack_channel_id="channel-id")
logger.info("This is an info message")
logger.error(exc=Exception, header_message="Header message appears above the exception message in the Slack message")
```

Services Utilities

```python
from utils_b_infra.services import get_google_service

google_sheet_service = get_google_service(google_token_path='common/google_token.json',
                                          google_credentials_path='common/google_credentials.json',
                                          service_name='sheets')
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

