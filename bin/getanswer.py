#!/usr/bin/env python3
from __future__ import annotations

import splunk.Intersplunk as intersplunk

from _ctf_common import APP, current_username, export_search, kv, privileged_session_key, setup_logger, user_to_team


def main() -> None:
    logger = setup_logger("sa_ctf_scoreboard.getanswer")
    try:
        records, _dummy, settings = intersplunk.getOrganizedResults()
        caller_key = settings.get("sessionKey")
        if not caller_key:
            raise RuntimeError("Splunk did not provide a session key to getanswer")

        username = current_username(caller_key)
        users = kv("ctf_users", caller_key, app=APP)
        teams = user_to_team(users)
        myteam = teams.get(username, username)

        privileged_key = privileged_session_key()
        submissions = export_search(
            'search earliest=0 latest=now index=scoreboard_admin Result=* Answer=* '
            '| table _time user Number Answer',
            privileged_key,
        )

        # Competitors can see submitted answers only for members of their own team.
        allowed = [row for row in submissions if teams.get(str(row.get("user", "")), str(row.get("user", ""))) == myteam]

        for record in records:
            answer = None
            for submission in allowed:
                try:
                    same_time = int(float(record.get("_time", 0))) == int(float(submission.get("_time", 0)))
                except (TypeError, ValueError):
                    same_time = False
                if (
                    same_time
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
