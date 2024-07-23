from typing import Literal, get_args, Final

from pydantic import BaseModel, model_validator, field_validator
from utils_b_infra.caching.coder import JsonCoder, Coder

SUPPORTED_CACHE_TYPES = Literal["SimpleCache", "RedisCache", "MongoCache"]


class CacheConfig(BaseModel):
    cache_type: SUPPORTED_CACHE_TYPES = "SimpleCache"
    default_timeout: int = 300
    app_space: str = "cacher"
    coder: Coder = JsonCoder
    sliding_expiration: bool = False  # if True, the expiration time will be reset on every access
    ONE_HOUR: Final[int] = 3600
    THREE_HOURS: Final[int] = ONE_HOUR * 3
    FIVE_HOURS: Final[int] = ONE_HOUR * 5
    EIGHT_HOURS: Final[int] = ONE_HOUR * 8
    ONE_DAY: Final[int] = ONE_HOUR * 24
    ONE_WEEK: Final[int] = ONE_DAY * 7
    ONE_MONTH: Final[int] = ONE_DAY * 30
    ONE_YEAR: Final[int] = ONE_DAY * 365

    simple_cache_threshold: int = 100

    redis_url: str = ""
    redis_host: str = None
    redis_port: int = 6379
    redis_password: str = None
    redis_db: int = 0

    mongo_url: str = ""
    mongo_database: str = "cacher"
    mongo_collection: str = "cache"
    mongo_direct_connection: bool = False

    @field_validator('cache_type')
    def validate_cache_type(cls, value):
        """validate that the cache_type is supported"""
        if value not in get_args(SUPPORTED_CACHE_TYPES):
            raise ValueError(f'cache_type must be one of {SUPPORTED_CACHE_TYPES}')
        return value

    @model_validator(mode='after')
    def validate_connection_attributes(cls, values):
        if values.cache_type == 'RedisCache':
            if not values.redis_url and not all([values.redis_host, values.redis_password]):
                raise ValueError(
                    'With RedisCache, either redis_url must be provided or (redis_host, '
                    'redis_password) must be provided.'
                )

        elif values.cache_type == 'MongoCache':
            if not values.mongo_url:
                raise ValueError('With MongoCache, either mongo_url must be provided.')

        return values

    class Config:
        arbitrary_types_allowed = True
