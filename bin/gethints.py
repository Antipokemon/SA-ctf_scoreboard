#!/usr/bin/env python3
from __future__ import annotations

import json

import splunk.Intersplunk as intersplunk

from _ctf_common import (
    ADMIN_APP,
    APP,
    REGISTRATION_APP,
    current_username,
    kv,
    privileged_session_key,
    registrations_to_team,
    setup_logger,
)

MASKED = "Your team has not purchased this hint yet!"


def main() -> None:
    logger = setup_logger("sa_ctf_scoreboard.gethints")
    try:
        records, _dummy, settings = intersplunk.getOrganizedResults()
        caller_key = settings.get("sessionKey")
        if not caller_key:
            raise RuntimeError("Splunk did not provide a session key to gethints")

        username = current_username(caller_key)
        privileged_key = privileged_session_key()

        ctf_ids = {
            str(record.get("ctf_id", ""))
            for record in records
            if str(record.get("ctf_id", ""))
        }
        if len(ctf_ids) != 1:
            raise RuntimeError("gethints requires exactly one ctf_id in the input records")

        ctf_id = next(iter(ctf_ids))

        registrations = kv(
            "ctf_registrations",
            privileged_key,
            app=REGISTRATION_APP,
        )
        teams = registrations_to_team(registrations, ctf_id)
        myteam = teams.get(username)
        if not myteam:
            raise RuntimeError(f"User {username} is not registered for CTF {ctf_id}")

        hints = [
            row
            for row in kv("ctf_hints", privileged_key, app=ADMIN_APP)
            if str(row.get("ctf_id", "")) == ctf_id
        ]
        entitlements = [
            row
            for row in kv("ctf_hint_entitlements", caller_key, app=APP)
            if str(row.get("ctf_id", "")) == ctf_id
        ]

        purchased = {
            (
                str(row.get("ctf_id", "")),
                str(row.get("Number", "")),
                str(row.get("HintNumber", "")),
            )
            for row in entitlements
            if teams.get(str(row.get("user", ""))) == myteam
        }

        for record in records:
            number = str(record.get("Number", ""))
            available = []
            received = 0

            for hint in hints:
                if str(hint.get("Number", "")) != number:
                    continue

                cleaned = dict(hint)
                key = (
                    ctf_id,
                    number,
                    str(hint.get("HintNumber", "")),
                )

                if key in purchased:
                    received += 1
                else:
                    cleaned["Hint"] = MASKED

                available.append(
                    json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
                )

            record["Hints"] = available
            record["HintsAvailable"] = len(available)
            record["HintsReceived"] = received

        intersplunk.outputResults(records)
    except Exception as exc:
        logger.exception("gethints failed")
        intersplunk.generateErrorResults(str(exc))


if __name__ == "__main__":
    main()
