from typing import Literal

import math
import numpy as np
import pandas as pd
import sqlalchemy
from sqlalchemy import text
from utils_b_infra.generic import retry_with_timeout


def clean_dataframe(df: pd.DataFrame, replace_pandas_nan=False, orders_dataframe: bool = True) -> pd.DataFrame:
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)

    cleaning = {
        '0000-00-00': None,
        'None': None,
        'nan': None,
        'NaN': None,
        'NAN': None,
        '': None
    }

    if replace_pandas_nan:
        cleaning.update({pd.NaT: None,
                         np.nan: None})

        df = df.map(lambda x: None if isinstance(x, float) and math.isnan(x) else x)

    df.replace(cleaning, inplace=True)

    if orders_dataframe:
        df.fillna({
            'user_country_code': '',
            'user_country_code_ip': '',
            'feedback_domain': '',
        }, inplace=True)

    return df


@retry_with_timeout(retries=3, timeout=60, initial_delay=10, backoff=2)
def insert_df_chunk_into_db(df: pd.DataFrame,
                            table_name: str,
                            conn: sqlalchemy.engine.Connection,
                            index: bool,
                            if_exists: Literal['replace', 'append'],
                            dtype: dict = None) -> None:
    df.to_sql(table_name, con=conn, index=index, if_exists=if_exists, dtype=dtype)


def insert_df_into_db_in_chunks(df: pd.DataFrame,
                                table_name: str,
                                conn: sqlalchemy.engine.Connection,
                                if_exists: Literal['replace', 'append'] = 'replace',
                                truncate_table: bool = False,
                                index: bool = True,
                                dtype: dict = None,
                                chunk_size: int = 20000) -> None:
    num_chunks = math.ceil(len(df) / chunk_size)

    if truncate_table and if_exists == 'append':
        conn.execute(text(f'TRUNCATE TABLE {table_name};'))

    for i in range(num_chunks):
        start = i * chunk_size
        end = (i + 1) * chunk_size

        df_chunk = df.iloc[start:end]

        if i == 0 and if_exists == 'replace':
            insert_df_chunk_into_db(
                df=df_chunk,
                table_name=table_name,
                conn=conn,
                index=index,
                if_exists='replace',
                dtype=dtype
            )
        else:
            insert_df_chunk_into_db(
                df=df_chunk,
                table_name=table_name,
                conn=conn,
                index=index,
                if_exists='append',
                dtype=dtype
            )
