import datetime
import json
from decimal import Decimal
from typing import (
    Any,
    Callable,
    Dict,
    TypeVar,
)

import pendulum
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

_T = TypeVar("_T", bound=type)

CONVERTERS: Dict[str, Callable[[str], Any]] = {
    # Pendulum 3.0.0 adds parse to __all__, at which point these ignores can be removed
    "date": lambda x: pendulum.parse(x, exact=True),  # type: ignore[attr-defined]
    "datetime": lambda x: pendulum.parse(x, exact=True),  # type: ignore[attr-defined]
    "decimal": Decimal,
}


def object_hook(obj: Any) -> Any:
    _spec_type = obj.get("_spec_type")
    if not _spec_type:
        return obj

    if _spec_type in CONVERTERS:
        return CONVERTERS[_spec_type](obj["val"])
    else:
        raise TypeError(f"Unknown {_spec_type}")


class JsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime.datetime):
            return {"val": str(o), "_spec_type": "datetime"}
        elif isinstance(o, datetime.date):
            return {"val": str(o), "_spec_type": "date"}
        elif isinstance(o, Decimal):
            return {"val": str(o), "_spec_type": "decimal"}
        else:
            return jsonable_encoder(o)


class Coder:
    """
    Parent class for encoding and decoding operations.
    """

    @staticmethod
    def encode(data):
        raise NotImplementedError

    @staticmethod
    def decode(data):
        raise NotImplementedError


class JsonCoder(Coder):
    @classmethod
    def encode(cls, value: Any) -> bytes:
        if isinstance(value, JSONResponse):
            return value.body
        return json.dumps(value, cls=JsonEncoder).encode()

    @classmethod
    def decode(cls, value: bytes) -> Any:
        # explicitly decode from UTF-8 bytes first, as otherwise
        # json.loads() will first have to detect the correct UTF-
        # encoding used.
        return json.loads(value.decode(), object_hook=object_hook)
