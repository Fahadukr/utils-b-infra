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


def is_running_locally():
    """Checks whether the code is running locally or in a Docker container.
    IS_RUNNING_IN_DOCKER should be set to 'true' in the Dockerfile: ENV IS_RUNNING_IN_DOCKER true
    """
    return not os.getenv('IS_RUNNING_IN_DOCKER', False) == 'true'


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
    Split a list of nums into groups of close nums and return the group with the most nums
    Example:
        [4, 5, 100, 1000, 1500, 1300, 1230, 5000] -> [1000, 1230, 1300, 1500]

    If convert_nums_to_closest_100 is True, the function will convert the nums to the closest 100
    Example:
        [4, 5, 100, 1000, 1500, 1300, 1230, 5000] -> [1000, 1200, 1300, 1500]

    If the list contains less than 4 nums, the function will return the list as is
    If the max num is less than 10000 and less than 3 times the min num, the function will return the list as is
    If the max num is more than 10000 and less than 2 times the min num, the function will return the list as is

    The algorithm will calculate the median of the list and group the nums that are close to the median
    """
    # convert any item in the list to int if it's str
    num_list = [int(float(num)) if isinstance(num, str) else num for num in num_list]
    if convert_nums_to_closest_100:
        num_list = [round(num / 100) * 100 for num in num_list]

    num_list = list(set(num_list))

    num_list.sort()
    if len(num_list) < 4:
        return num_list

    max_num = max(num_list)
    min_num = min(num_list)
    if ((max_num < 10000) and (max_num <= 3 * min_num)) or ((max_num > 10000) and (max_num <= 2 * min_num)):
        return num_list

    median = statistics.median(num_list)
    if len(num_list) > 5:
        diff = [abs(num - median) for num in num_list]
        threshold = 0.5
        if max_num > (min_num * 4):
            threshold = 0.6
        median_border = median * threshold
        close_group = [num_list[i] for i in range(len(num_list)) if diff[i] <= median_border]
        if not close_group:
            return num_list

        return close_group

    differences = [abs(num_list[i] - median) for i in range(len(num_list))]

    threshold = statistics.median(differences)
    if min_num > 5000:
        threshold = 3 * threshold

    if threshold < 1000 and max(differences) < 1000:
        return num_list

    groups = []
    current_group = [num_list[0]]
    for i in range(1, len(num_list)):
        if num_list[i] - num_list[i - 1] <= threshold:
            current_group.append(num_list[i])
        else:
            groups.append(current_group)
            current_group = [num_list[i]]
    groups.append(current_group)

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


def date_formatter(date, is_event_time=False, is_mongo_id_object=False, is_mongo_time_object=False):
    """
    Extract date in format 'YYYY-MM-DD HH:MM:SS' from different date formats including MongoDB date objects.
    :param date: str, int, dict, datetime or MongoDB date object
    :param is_event_time: if it's an event time object in the format 'YYYY-MM-DD HH:MM:SS GMT'
    :param is_mongo_id_object: if it's a MongoDB ID object string
    :param is_mongo_time_object: if it's a MongoDB date object
    :return: string in the format 'YYYY-MM-DD HH:MM:SS' or None if invalid
    """
    if not date or date in {pd.NaT, np.nan, 'nan', 'NaT', 'None'}:
        return None

    # Handle different cases based on type of the 'date' and flags
    try:
        if isinstance(date, datetime):
            return date.strftime('%Y-%m-%d %H:%M:%S')

        if is_event_time:
            # Assumes date is a string from which 'GMT' and fractional seconds can be removed
            return datetime.strptime(date.replace('GMT', '').strip().split('.')[0], "%Y-%m-%d %H:%M:%S").strftime(
                '%Y-%m-%d %H:%M:%S')

        if is_mongo_time_object:
            # Parse MongoDB ISO date format
            return datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%f+00:00').strftime('%Y-%m-%d %H:%M:%S')

        if is_mongo_id_object:
            # Convert from MongoDB ObjectId
            return ObjectId(date).generation_time.strftime('%Y-%m-%d %H:%M:%S')

        if isinstance(date, dict):
            # Handle dict containing date details
            date = date.get('milliseconds') or date.get('$date', {}).get('$numberLong')
            date = int(float(date))

        if is_numeric_value(date):
            # Handle numeric timestamps
            if len(str(date)) > 10:
                date = str(date)[:10]
            timestamp = int(float(date))
            return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

        if isinstance(date, str):
            # Try parsing ISO format or other standard date strings
            return datetime.fromisoformat(date.rstrip('Z')).strftime('%Y-%m-%d %H:%M:%S')

    except (ValueError, TypeError, KeyError):
        print(f"Failed to parse date: {date}")
        return None

    return None
