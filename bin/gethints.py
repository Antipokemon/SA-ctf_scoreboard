#!/usr/bin/env python3
from __future__ import annotations

import json
import splunk.Intersplunk as intersplunk

from _ctf_common import ADMIN_APP, APP, current_username, kv, privileged_session_key, setup_logger, user_to_team

MASKED = "Your team has not purchased this hint yet!"


def main() -> None:
    logger = setup_logger("sa_ctf_scoreboard.gethints")
    try:
        records, _dummy, settings = intersplunk.getOrganizedResults()
        caller_key = settings.get("sessionKey")
        if not caller_key:
            raise RuntimeError("Splunk did not provide a session key to gethints")

        username = current_username(caller_key)
        users = kv("ctf_users", caller_key, app=APP)
        teams = user_to_team(users)
        myteam = teams.get(username, username)

        privileged_key = privileged_session_key()
        hints = kv("ctf_hints", privileged_key, app=ADMIN_APP)
        entitlements = kv("ctf_hint_entitlements", caller_key, app=APP)

        purchased = {
            (str(row.get("Number", "")), str(row.get("HintNumber", "")))
            for row in entitlements
            if teams.get(str(row.get("user", "")), str(row.get("user", ""))) == myteam
        }

        for record in records:
            number = str(record.get("Number", ""))
            available = []
            received = 0
            for hint in hints:
                if str(hint.get("Number", "")) != number:
                    continue
                cleaned = dict(hint)
                key = (number, str(hint.get("HintNumber", "")))
                if key in purchased:
                    received += 1
                else:
                    cleaned["Hint"] = MASKED
                # Preserve the original app's JSON-in-a-multivalue-field contract;
                # question.xml uses mvexpand + spath on these values.
                available.append(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")))
            record["Hints"] = available
            record["HintsAvailable"] = len(available)
            record["HintsReceived"] = received

        intersplunk.outputResults(records)
    except Exception as exc:
        logger.exception("gethints failed")
        intersplunk.generateErrorResults(str(exc))


if __name__ == "__main__":
    main()
