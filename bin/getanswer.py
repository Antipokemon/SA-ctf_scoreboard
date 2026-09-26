#!/usr/bin/env python3
from __future__ import annotations

import splunk.Intersplunk as intersplunk

from _ctf_common import (
    REGISTRATION_APP,
    current_username,
    export_search,
    kv,
    privileged_session_key,
    registrations_to_team,
    setup_logger,
)


def main() -> None:
    logger = setup_logger("sa_ctf_scoreboard.getanswer")
    try:
        records, _dummy, settings = intersplunk.getOrganizedResults()
        caller_key = settings.get("sessionKey")
        if not caller_key:
            raise RuntimeError("Splunk did not provide a session key to getanswer")

        username = current_username(caller_key)
        privileged_key = privileged_session_key()

        registrations = kv(
            "ctf_registrations",
            privileged_key,
            app=REGISTRATION_APP,
        )

        ctf_ids = {
            str(record.get("ctf_id", ""))
            for record in records
            if str(record.get("ctf_id", ""))
        }
        if len(ctf_ids) != 1:
            raise RuntimeError("getanswer requires exactly one ctf_id in the input records")

        ctf_id = next(iter(ctf_ids))
        teams = registrations_to_team(registrations, ctf_id)
        myteam = teams.get(username)
        if not myteam:
            raise RuntimeError(f"User {username} is not registered for CTF {ctf_id}")

        submissions = export_search(
            'search earliest=0 latest=now index=scoreboard_admin Result=* Answer=* '
            f'ctf_id="{ctf_id}" '
            '| table _time user ctf_id Number Answer',
            privileged_key,
        )

        allowed = [
            row
            for row in submissions
            if teams.get(str(row.get("user", ""))) == myteam
        ]

        for record in records:
            answer = None
            for submission in allowed:
                try:
                    same_time = int(float(record.get("_time", 0))) == int(
                        float(submission.get("_time", 0))
                    )
                except (TypeError, ValueError):
                    same_time = False

                if (
                    same_time
                    and str(record.get("ctf_id", "")) == str(submission.get("ctf_id", ""))
                    and str(record.get("Number", "")) == str(submission.get("Number", ""))
                    and str(record.get("user", "")) == str(submission.get("user", ""))
                ):
                    answer = submission.get("Answer")
                    break
            record["Answer"] = answer

        intersplunk.outputResults(records)
    except Exception as exc:
        logger.exception("getanswer failed")
        intersplunk.generateErrorResults(str(exc))


if __name__ == "__main__":
    main()
