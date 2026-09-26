#!/usr/bin/env python3
from __future__ import annotations

import configparser
import hmac

import splunk.Intersplunk as intersplunk
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

import validatectf
from _ctf_common import setup_logger


def _vkey() -> str:
    path = make_splunkhome_path(["etc", "apps", "SA-ctf_scoreboard", "appserver", "controllers", "scoreboard_controller.config"])
    cfg = configparser.ConfigParser()
    if not cfg.read(path):
        raise RuntimeError(f"Unable to read {path}")
    return cfg.get("ScoreboardController", "VKEY")


def main() -> None:
    logger = setup_logger("sa_ctf_scoreboard.validateevents")
    try:
        records, _dummy, _settings = intersplunk.getOrganizedResults()
        key = _vkey()
        fields = (
            "tcode", "user", "Number", "Result", "BasePointsAwarded",
            "SpeedBonusAwarded", "AdditionalBonusAwarded", "Penalty",
        )
        for record in records:
            try:
                supplied = str(record.get("vcode", ""))
                calculated = validatectf.makeVCode(key, *(str(record.get(f, "")) for f in fields))
                record["Validated"] = "1" if hmac.compare_digest(supplied, calculated) else "0"
            except Exception:
                record["Validated"] = "0"
        intersplunk.outputResults(records)
    except Exception as exc:
        logger.exception("validateevents failed")
        intersplunk.generateErrorResults(str(exc))


if __name__ == "__main__":
    main()
