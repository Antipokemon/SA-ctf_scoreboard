#!/usr/bin/env python3
"""Integrity helpers for SA-ctf_scoreboard.

Compatible with Python 3.9 and 3.13 (Splunk Enterprise 10.4 runtimes).
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    raise ValueError("Supplied value must be text or UTF-8 bytes.")


def RepresentsInt(value: Any) -> bool:
    try:
        int(_text(value) if isinstance(value, (str, bytes)) else value)
        return True
    except (TypeError, ValueError):
        return False


def RepresentsEpoch(value: Any) -> bool:
    if not RepresentsInt(value):
        return False
    epoch = int(value)
    return 0 < epoch < 4294967296


def IsSomeKindaString(obj: Any) -> bool:
    return isinstance(obj, (str, bytes))


def makeTCode(epochTime: Any) -> str:
    if not RepresentsEpoch(epochTime):
        raise ValueError("Invalid epoch time value.")
    return str(int(epochTime)).encode("utf-8").hex()


def decodeTCode(tcode: Any) -> str:
    """Decode the hex tcode produced by :func:`makeTCode`."""
    value = _text(tcode)
    try:
        decoded = bytes.fromhex(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid tcode value.") from exc
    if not RepresentsEpoch(decoded):
        raise ValueError("Decoded tcode is not a valid epoch value.")
    return decoded


def makeVCode(
    hkey: Any,
    tcode: Any,
    user: Any,
    Number: Any,
    Result: Any,
    BasePointsAwarded: Any,
    SpeedBonusAwarded: Any,
    AdditionalBonusAwarded: Any,
    Penalty: Any,
) -> str:
    values = {
        "hkey": hkey,
        "tcode": tcode,
        "user": user,
        "Number": Number,
        "Result": Result,
        "BasePointsAwarded": BasePointsAwarded,
        "SpeedBonusAwarded": SpeedBonusAwarded,
        "AdditionalBonusAwarded": AdditionalBonusAwarded,
        "Penalty": Penalty,
    }
    for name, value in values.items():
        if not IsSomeKindaString(value):
            raise ValueError(f"Supplied {name} value is not text.")

    for name in (
        "Number",
        "BasePointsAwarded",
        "SpeedBonusAwarded",
        "AdditionalBonusAwarded",
        "Penalty",
    ):
        if not RepresentsInt(values[name]):
            raise ValueError(f"Supplied {name} does not represent an integer.")

    # tcode is a hex-encoded epoch timestamp. Validate by decoding it rather than
    # incorrectly treating the hexadecimal representation as a decimal integer.
    decodeTCode(tcode)

    # Keep the historical wire format exactly as the original scoreboard used.
    # The missing '=' before the three trailing labels is intentional for
    # compatibility with already indexed events.
    vcode_string = (
        "tcode={},user={},Number={},Result={},BasePointsAwarded={},"
        "SpeedBonusAwarded{},AdditionalBonusAwarded{},Penalty{}"
    ).format(
        _text(tcode),
        _text(user),
        _text(Number),
        _text(Result),
        _text(BasePointsAwarded),
        _text(SpeedBonusAwarded),
        _text(AdditionalBonusAwarded),
        _text(Penalty),
    )

    return hmac.new(
        _text(hkey).encode("utf-8"),
        vcode_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verifyVCode(expected: Any, *args: Any) -> bool:
    return hmac.compare_digest(_text(expected), makeVCode(*args))
