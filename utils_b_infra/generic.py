import concurrent.futures
import functools
import os
import re
import statistics
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import time
from bson import ObjectId


class Timer:
    def __init__(self):
        self.start = None
        self.end = None
        self.seconds_taken = None
        self.minutes_taken = None

    def __enter__(self):
        self.start_timer()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_timer()

    def start_timer(self):
        self.start = time.perf_counter()

    def stop_timer(self):
        self.end = time.perf_counter()
        self.seconds_taken = self.end - self.start
        self.minutes_taken = self.seconds_taken / 60


def is_running_locally(env_key: str = 'IS_RUNNING_IN_DOCKER'):
    """
    Checks whether the code is running locally
    For docker containers, set the environment variable IS_RUNNING_IN_DOCKER to 'true' in Dockerfile.
    ENV IS_RUNNING_IN_DOCKER true
    """
    return not os.getenv(env_key, False) == 'true'


def retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2):
    """
    A decorator for retrying a function if it doesn't complete within 'timeout' seconds or if it raises an error.

    !Note!: This decorator cannot cancel ongoing blocking operations (e.g., network I/O with `requests`).
    It is recommended to implement timeouts directly within the function, e.g., `requests.get(url, timeout=seconds)`,
    for more effective timeout handling.

    :param retries: The number of retries.
    :param timeout: The function timeout in seconds.
    :param initial_delay: The initial wait between retries.
    :param backoff: The backoff multiplier for the delay.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = initial_delay
            last_exception = None

            while attempts < retries:
                attempts_left = retries - attempts - 1
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func, *args, **kwargs)
                    try:
                        return future.result(timeout=timeout)
                    except concurrent.futures.TimeoutError:
                        future.cancel()
                        msg = f"Function {func.__name__} timed out after {timeout}s"
                        if attempts_left > 0:
                            msg += f", {attempts_left} attempts left, delay: {current_delay}s..."
                        else:
                            msg += f", no attempts left, raising exception..."
                        print(msg)
                    except Exception as e:
                        last_exception = e
                        msg = f"Function {func.__name__} raised an exception: {e}"
                        if attempts_left > 0:
                            msg += f", {attempts_left} attempts left, delay: {current_delay}s..."
                        else:
                            msg += f", no attempts left, raising exception..."
                        print(msg)

                if attempts < retries - 1:
                    time.sleep(current_delay)
                    current_delay *= backoff
                else:
                    break

                attempts += 1

            raise Exception(
                f"Function {func.__name__} failed after {retries} retries. Last exception: {last_exception}")

        return wrapper

    return decorator


def valid_date(date):
    if date:
        date = str(date)
        try:
            x = datetime.strptime(date.strip(), "%d-%m-%Y").strftime("%Y-%m-%d")
            return x
        except ValueError:
            return date.strip()
    return np.nan


def get_closest_num_group(num_list: list[int], convert_nums_to_closest_100: bool = False) -> list:
    """
    Split a list of nums into groups of close nums and return the group with the most nums.
    Example:
        [4, 5, 100, 1000, 1500, 1300, 1230, 5000] -> [1000, 1500, 1300, 1230]

    If convert_nums_to_closest_100 is True, the function will convert the nums to the closest 100.
    Example:
        [4, 5, 100, 1020, 1710, 2220, 2295, 5000] -> [1000, 1700, 2200, 2300]

    If the list contains less than 4 nums, the function will return the list as is.
    If the max num is less than 10000 and less than 3 times the min num, the function will return the list as is.
    If the max num is more than 10000 and less than 2 times the min num, the function will return the list as is.

    The algorithm will calculate the median of the list and group the nums that are close to the median.
    """

    # Convert any string elements in the list to integers
    num_list = [int(float(num)) if isinstance(num, str) else num for num in num_list]

    # Convert numbers to the closest 100 if the flag is set
    if convert_nums_to_closest_100:
        num_list = [round(num / 100) * 100 for num in num_list]

    # Remove duplicates and sort the list
    num_list = list(set(num_list))
    num_list.sort()

    # If the list contains less than 4 numbers, return the list as is
    if len(num_list) < 4:
        return num_list

    max_num = max(num_list)
    min_num = min(num_list)

    # Return the list as is if the max number is less than 10,000 and less than 3 times the min number
    # or if the max number is more than 10,000 and less than 2 times the min number
    if ((max_num < 10000) and (max_num <= 3 * min_num)) or ((max_num > 10000) and (max_num <= 2 * min_num)):
        return num_list

    # Calculate the median of the list
    median = statistics.median(num_list)

    # If the list is long enough, group numbers close to the median
    if len(num_list) > 5:
        diff = [abs(num - median) for num in num_list]  # Calculate the absolute differences from the median
        threshold = 0.5  # Default threshold as 50% of the median

        # Increase the threshold if the range is very wide
        if max_num > (min_num * 4):
            threshold = 0.6

        median_border = median * threshold  # Calculate the boundary for close numbers
        close_group = [num_list[i] for i in range(len(num_list)) if diff[i] <= median_border]  # Group close numbers

        # If no close group is found, return the original list
        if not close_group:
            return num_list

        return close_group

    # Calculate the differences from the median
    differences = [abs(num_list[i] - median) for i in range(len(num_list))]

    threshold = statistics.median(differences)  # Use the median of differences as the threshold

    # Increase the threshold if the minimum number is large
    if min_num > 5000:
        threshold = 3 * threshold

    # If the differences are small, return the list as is
    if threshold < 1000 and max(differences) < 1000:
        return num_list

    groups = []
    current_group = [num_list[0]]

    # Group numbers that are within the threshold
    for i in range(1, len(num_list)):
        if num_list[i] - num_list[i - 1] <= threshold:
            current_group.append(num_list[i])
        else:
            groups.append(current_group)
            current_group = [num_list[i]]
    groups.append(current_group)

    # Return the largest group
    max_group = max(groups, key=len)

    return max_group


def run_threaded(job_func, *args, **kwargs):
    """Run a function in a separate thread"""
    job_thread = threading.Thread(target=job_func, args=args, kwargs=kwargs)
    job_thread.start()


def generate_dates(start_date: str) -> list[str]:
    """
    Generate a list of dates from the start date to today
    :param start_date: The start date in the format 'YYYY-MM-DD'
    """
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    today = datetime.now()

    dates = []
    current_date = start_date
    while current_date <= today:
        dates.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)

    return dates


def get_local_files_mapping(root_path: str = 'modules/ddl_files') -> dict[str, str]:
    """
    Get a mapping of the files in the root path.
    :return: a dictionary with the file name as the key and the full path as the value
    """
    file_mapping = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        for filename in filenames:
            if filename in file_mapping:
                # Handle potential name conflicts by appending the directory to the name.
                # For example: directory1_filename.sql, directory2_filename.sql
                directory = os.path.basename(dirpath)
                unique_filename = f"{directory}_{filename}"
                file_mapping[unique_filename] = os.path.join(dirpath, filename)
            else:
                file_mapping[filename] = os.path.join(dirpath, filename)
    return file_mapping


def get_sql_ddl_commands_from_file(file_name: str, ddl_files_paths: dict[str, str]) -> list[str]:
    """
    Read SQL file and return a list of SQL commands
    """
    if file_name not in ddl_files_paths:
        raise ValueError(f"{file_name} not found in the directory!")

    file_path = ddl_files_paths[file_name]
    print(file_path)
    sql_commands = []
    with open(file_path, 'r') as sql_file:
        for command in sql_file.read().split(';'):
            command = command.strip()
            if command in ('', '\n'):
                continue
            sql_commands.append(command + ';')

    return sql_commands


def is_numeric_value(value):
    """
    Check if a value is numeric:
    True: 123, 123.456, -123, -123.456, '123', '123.456', '-123'
    """
    if not value and value != 0:
        return False

    value = str(value).strip()

    pattern = r"^-?\d*\.?\d*$"

    if re.match(pattern, value):
        return True
    return False


def run_func_in_background(task, *args, **kwargs):
    """Run the provided function in a background thread."""
    threading.Thread(target=task, args=args, kwargs=kwargs).start()


def date_formatter(date,
                   input_format: str = None,
                   output_format: str = "%Y-%m-%d %H:%M:%S",
                   is_event_time=False,
                   is_mongo_id_object=False,
                   is_mongo_time_object=False):
    """
    Extract date in the desired format from different date formats including MongoDB date objects.
    :param date: str, int, dict, datetime, or MongoDB date object.
    :param output_format: Desired output format like "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", etc.
    :param input_format: Input date format if the input date is in a specific string format (e.g., "YYYYMMDD").
    :param is_event_time: If it's an event time object in the format 'YYYY-MM-DD HH:MM:SS GMT'.
    :param is_mongo_id_object: If it's a MongoDB ObjectId.
    :param is_mongo_time_object: If it's a MongoDB ISO date string.
    :return: string in the desired format or None if invalid
    """
    if not date or date in {pd.NaT, np.nan, 'nan', 'NaT', 'None'}:
        return None

    try:
        if isinstance(date, datetime):
            # If the date is a datetime object, format it to the desired output format.
            return date.strftime(output_format)

        if is_event_time:
            # Handle event time by removing 'GMT' and fractional seconds
            return datetime.strptime(date.replace('GMT', '').strip().split('.')[0], "%Y-%m-%d %H:%M:%S").strftime(
                output_format)

        if is_mongo_time_object:
            # Parse MongoDB ISO date format
            return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f+00:00').strftime(output_format)

        if is_mongo_id_object:
            # Convert MongoDB ObjectId to datetime and format it
            return ObjectId(date).generation_time.strftime(output_format)

        if isinstance(date, dict):
            # Handle dictionaries that may contain timestamps (e.g., milliseconds or $date)
            date = date.get('milliseconds') or date.get('$date', {}).get('$numberLong')
            date = int(float(date))

        if is_numeric_value(date) and not input_format:
            # Handle numeric timestamps (milliseconds or seconds)
            if len(str(date)) > 10:
                date = str(date)[:10]  # Truncate to 10 digits if needed
            timestamp = int(float(date))
            return datetime.utcfromtimestamp(timestamp).strftime(output_format)

        if isinstance(date, str):
            if input_format:
                # Convert the date string from input format to output format
                return datetime.strptime(date, input_format).strftime(output_format)
            # Try to handle ISO or other standard date strings
            return datetime.fromisoformat(date.rstrip('Z')).strftime(output_format)

    except (ValueError, TypeError, KeyError) as e:
        print(f"Failed to parse date: {date}. Error: {e}")
        return None

    return None


def seconds_to_hhmmss(seconds: int) -> str:
    if not is_numeric_value(seconds):
        raise ValueError("Input must be a numeric value representing seconds.")
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02}"
