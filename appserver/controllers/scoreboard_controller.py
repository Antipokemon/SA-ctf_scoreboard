# -*- coding: utf-8 -*-
"""Splunk Enterprise 10.4 compatible CTF scoreboard controller.

This is a Python 3.9/3.13 rewrite of the original controller.  Route names and
logged field names are intentionally preserved so the historical dashboards,
indexes, macros, and admin companion app continue to work.
"""
from __future__ import annotations

import collections
import configparser
import json
import logging
import logging.handlers
import os
import sys
import time
import urllib.parse
import uuid
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

import cherrypy
import splunk.auth
import splunk.rest
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

APP = "SA-ctf_scoreboard"
ADMIN_APP = "SA-ctf_scoreboard_admin"
REGISTRATION_APP = "SA-ctf_registration"
ERROR_VIEW = f"/en-US/app/{APP}/scoreboard_error"
ADMIN_ERROR_VIEW = f"/en-US/app/{ADMIN_APP}/scoreboard_admin_error"

BIN_DIR = make_splunkhome_path(["etc", "apps", APP, "bin"])
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

import validatectf  # noqa: E402


def _setup_logger(name: str, filename: str) -> logging.Logger:
    logdir = make_splunkhome_path(["var", "log", "scoreboard"])
    os.makedirs(logdir, exist_ok=True)
    path = os.path.join(logdir, filename)
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    if not any(
        isinstance(handler, logging.handlers.RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == os.path.abspath(path)
        for handler in logger.handlers
    ):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=25_000_000, backupCount=5)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


logger = _setup_logger(
    "splunk.appserver.SA-ctf_scoreboard.controllers.scoreboard_controller",
    "scoreboard.log",
)
logger_admin = _setup_logger(
    "splunk.appserver.SA-ctf_scoreboard.controllers.scoreboard_controller.admin",
    "scoreboard_admin.log",
)
logger.info("scoreboard_controller loaded. Unique ID=%s", uuid.uuid4())
logger_admin.info("scoreboard_controller loaded. Unique ID=%s", uuid.uuid4())

CONF_FILE = make_splunkhome_path(
    ["etc", "apps", APP, "appserver", "controllers", "scoreboard_controller.config"]
)
_config = configparser.ConfigParser()
if not _config.read(CONF_FILE):
    raise RuntimeError(f"Could not read required config file: {CONF_FILE}")

USER = _config.get("ScoreboardController", "USER")
PASSWORD = _config.get("ScoreboardController", "PASS")
VKEY = _config.get("ScoreboardController", "VKEY")


def _decode(content: Any) -> str:
    return content.decode("utf-8") if isinstance(content, bytes) else str(content)


def _service_session_key() -> str:
    """Authenticate the configured service account using Splunk's local API."""
    key = splunk.auth.getSessionKey(USER, PASSWORD)
    if not key:
        raise RuntimeError("splunkd authentication did not return a sessionKey")
    return str(key)


def _kv(
    collection: str,
    session_key: str,
    app: str = APP,
    owner: str = "nobody",
) -> List[Dict[str, Any]]:
    _, content = splunk.rest.simpleRequest(
        f"/servicesNS/{owner}/{app}/storage/collections/data/{collection}",
        sessionKey=session_key,
        getargs={"output_mode": "json"},
    )
    data = json.loads(_decode(content))
    if not isinstance(data, list):
        raise RuntimeError(f"KV Store collection {collection} did not return a list")
    return data


def _post_kv(collection: str, payload: Mapping[str, Any], session_key: str) -> None:
    uri = f"/servicesNS/nobody/{APP}/storage/collections/data/{collection}"
    splunk.rest.simpleRequest(
        uri,
        method="POST",
        jsonargs=json.dumps(dict(payload)),
        sessionKey=session_key,
    )


def _team_for(username: str, users: Iterable[Mapping[str, Any]]) -> str:
    for row in users:
        if str(row.get("Username", "")) == username:
            return str(row.get("Team") or row.get("DisplayUsername") or username)
    return username



def _ctf_rows(rows: Iterable[Mapping[str, Any]], ctf_id: str) -> List[Dict[str, Any]]:
    wanted = str(ctf_id)
    return [dict(row) for row in rows if str(row.get("ctf_id", "")) == wanted]


def _registration_for(
    username: str,
    ctf_id: str,
    session_key: str,
) -> Dict[str, Any]:
    registrations = _kv(
        "ctf_registrations",
        session_key,
        app=REGISTRATION_APP,
    )
    for row in registrations:
        if (
            str(row.get("ctf_id", "")) == str(ctf_id)
            and str(row.get("Username", "")) == str(username)
            and str(row.get("status", "registered")) == "registered"
        ):
            return row
    raise PermissionError(f"{username} is not registered for CTF {ctf_id}")


def _team_from_registration(registration: Mapping[str, Any], username: str) -> str:
    return str(
        registration.get("Team")
        or registration.get("DisplayUsername")
        or username
    )


def _eula_fields(username: str, accepted: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    for row in accepted:
        if str(row.get("EulaUsername", "")) == username:
            return {
                "EulaDateAccepted": str(row.get("EulaDateAccepted", "0")),
                "EulaId": str(row.get("EulaId", "0")),
                "EulaName": str(row.get("EulaName", "")),
                "EulaUsername": str(row.get("EulaUsername", username)),
            }
    raise PermissionError("user agreement has not been accepted")


def _event_lists(data: Mapping[str, Any]) -> List[str]:
    values: List[str] = []
    for key, value in data.items():
        # Preserve the historical comma-delimited key=value event format while
        # preventing a value from injecting an extra field into the event.
        clean = str(value).replace("\r", " ").replace("\n", " ").replace(",", " ")
        values.append(f"{key}={clean}")
    return values


def _log_event(participant: Mapping[str, Any], admin: Mapping[str, Any]) -> None:
    logger.info(",".join(_event_lists(participant)))
    logger_admin.info(",".join(_event_lists(admin)))


def _redirect(path: str, params: Optional[Mapping[str, Any]] = None) -> None:
    if params:
        path = f"{path}?{urllib.parse.urlencode({k: str(v) for k, v in params.items()})}"
    raise cherrypy.HTTPRedirect(path, 302)


def _wants_json(kwargs: Mapping[str, Any]) -> bool:
    return str(kwargs.get("ajax", "")).strip().lower() in {"1", "true", "yes", "json"}


def _json_response(payload: Mapping[str, Any], status: int = 200) -> str:
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = "application/json; charset=utf-8"
    return json.dumps(dict(payload), ensure_ascii=False)


def _signed_fields(data: MutableMapping[str, Any]) -> None:
    data["tcode"] = validatectf.makeTCode(int(time.time()))
    data["vcode"] = validatectf.makeVCode(
        VKEY,
        str(data["tcode"]),
        str(data["user"]),
        str(data["Number"]),
        str(data["Result"]),
        str(data["BasePointsAwarded"]),
        str(data["SpeedBonusAwarded"]),
        str(data["AdditionalBonusAwarded"]),
        str(data["Penalty"]),
    )


def _copy_signature(source: Mapping[str, Any], target: MutableMapping[str, Any]) -> None:
    target["tcode"] = source["tcode"]
    target["vcode"] = source["vcode"]


class ScoreBoardController(controllers.BaseController):
    """CTF Scoreboard controller, preserving original public endpoints."""

    @staticmethod
    def represents_int(value: Any) -> bool:
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            return False

    def get_kv_lookup(self, lookup_file: str, namespace: str = APP, owner: str = "nobody") -> str:
        session_key = cherrypy.session.get("sessionKey")
        if not session_key:
            raise RuntimeError("No Splunk session key is available")
        return json.dumps(_kv(lookup_file, session_key, app=namespace, owner=owner))

    def _caller(self) -> tuple[str, str]:
        return cherrypy.session["user"]["name"], cherrypy.session.get("sessionKey")

    @expose_page(must_login=True, methods=["GET"])
    def purchase_hint(self, **kwargs: Any) -> Any:
        cherrypy.response.headers["Content-Type"] = "text/plain; charset=utf-8"
        user, caller_key = self._caller()
        ctf_id = str(kwargs.get("ctf_id", "")).strip()
        number = kwargs.get("Number")
        hint_number = kwargs.get("HintNumber")
        wants_json = _wants_json(kwargs)

        if not ctf_id or not self.represents_int(number) or not self.represents_int(hint_number):
            logger_admin.error(
                "Invalid hint request ctf_id=%r Number=%r HintNumber=%r",
                ctf_id,
                number,
                hint_number,
            )
            _redirect(ERROR_VIEW)

        try:
            privileged = _service_session_key()
            registration = _registration_for(user, ctf_id, privileged)
            team = _team_from_registration(registration, user)
            questions = _ctf_rows(_kv("ctf_questions", caller_key, app=ADMIN_APP), ctf_id)
            accepted = _kv("ctf_eulas_accepted", caller_key)
            eula = _eula_fields(user, accepted)
            hints = _ctf_rows(_kv("ctf_hints", privileged, app=ADMIN_APP), ctf_id)
            entitlements = _ctf_rows(_kv("ctf_hint_entitlements", caller_key), ctf_id)
            registrations = _kv("ctf_registrations", privileged, app=REGISTRATION_APP)
        except PermissionError:
            logger_admin.error(
                "User %s attempted to play CTF %s without registration/EULA",
                user,
                ctf_id,
            )
            _redirect(f"/en-US/app/{APP}/user_agreement_required")
        except Exception:
            logger_admin.exception("Unable to load data required to purchase a hint")
            _redirect(ERROR_VIEW)

        question = next(
            (q for q in questions if str(q.get("Number", "")) == str(number)),
            None,
        )
        hint = next(
            (
                h
                for h in hints
                if str(h.get("Number", "")) == str(number)
                and str(h.get("HintNumber", "")) == str(hint_number)
            ),
            None,
        )
        if not question or not hint:
            logger_admin.error(
                "Unknown question/hint combination ctf_id=%s %s/%s",
                ctf_id,
                number,
                hint_number,
            )
            _redirect(ERROR_VIEW)

        def registered_team(username: str) -> str:
            for row in registrations:
                if (
                    str(row.get("ctf_id", "")) == ctf_id
                    and str(row.get("Username", "")) == username
                ):
                    return _team_from_registration(row, username)
            return username

        already_purchased = False
        for entitlement in entitlements:
            entitlement_user = str(entitlement.get("user", ""))
            if (
                registered_team(entitlement_user) == team
                and str(entitlement.get("Number", "")) == str(number)
                and str(entitlement.get("HintNumber", "")) == str(hint_number)
            ):
                already_purchased = True
                break

        if not already_purchased:
            try:
                _post_kv(
                    "ctf_hint_entitlements",
                    {
                        "ctf_id": ctf_id,
                        "Number": str(number),
                        "HintNumber": str(hint_number),
                        "user": user,
                    },
                    privileged,
                )
            except Exception:
                logger_admin.exception("Unable to write hint entitlement")
                _redirect(ERROR_VIEW)

        participant: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        admin: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        shared = {
            "ctf_id": ctf_id,
            "user": user,
            "Team": team,
            "Result": "Hint",
            "Number": str(number),
            "HintNumber": str(hint_number),
            "Penalty": "0" if already_purchased else str(hint.get("HintCost", "0")),
            "Question": f'"{str(question.get("Question", "")).replace(chr(34), chr(39))}"',
            "BasePointsAwarded": "0",
            "SpeedBonusAwarded": "0",
            "AdditionalBonusAwarded": "0",
            **eula,
        }
        participant.update(shared)
        admin.update(shared)
        admin["Hint"] = f'"{str(hint.get("Hint", ""))}"'
        if already_purchased:
            participant["HintAlreadyPurchased"] = "1"
            admin["HintAlreadyPurchased"] = "1"

        _signed_fields(participant)
        _copy_signature(participant, admin)
        _log_event(participant, admin)
        if wants_json:
            return _json_response({
                "ok": True,
                "ctf_id": ctf_id,
                "number": str(number),
                "hint_number": str(hint_number),
                "hint": str(hint.get("Hint", "")),
                "hint_cost": str(hint.get("HintCost", "0")),
                "already_purchased": already_purchased,
            })
        _redirect(f"/en-US/app/{APP}/question", participant)

    @expose_page(must_login=True, methods=["GET"])
    def submit_question(self, **kwargs: Any) -> Any:
        cherrypy.response.headers["Content-Type"] = "text/plain; charset=utf-8"
        user, caller_key = self._caller()
        ctf_id = str(kwargs.get("ctf_id", "")).strip()
        submitted_answer = str(kwargs.get("Answer", ""))
        number = kwargs.get("Number")
        wants_json = _wants_json(kwargs)

        if not ctf_id or not self.represents_int(number):
            logger_admin.error("Invalid question ctf_id=%r Number=%r", ctf_id, number)
            _redirect(ERROR_VIEW)

        try:
            privileged = _service_session_key()
            registration = _registration_for(user, ctf_id, privileged)
            team = _team_from_registration(registration, user)
            answers = _ctf_rows(_kv("ctf_answers", privileged, app=ADMIN_APP), ctf_id)
            questions = _ctf_rows(_kv("ctf_questions", caller_key, app=ADMIN_APP), ctf_id)
            eula = _eula_fields(user, _kv("ctf_eulas_accepted", caller_key))
        except PermissionError:
            logger_admin.error(
                "User %s attempted to play CTF %s without registration/EULA",
                user,
                ctf_id,
            )
            _redirect(f"/en-US/app/{APP}/user_agreement_required")
        except Exception:
            logger_admin.exception("Unable to load question/answer data")
            _redirect(ERROR_VIEW)

        question = next(
            (q for q in questions if str(q.get("Number", "")) == str(number)),
            None,
        )
        answer = next(
            (a for a in answers if str(a.get("Number", "")) == str(number)),
            None,
        )
        if not question or not answer:
            logger_admin.error(
                "Question or answer not found for ctf_id=%s Number=%s",
                ctf_id,
                number,
            )
            _redirect(ERROR_VIEW)

        participant: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        admin: "collections.OrderedDict[str, str]" = collections.OrderedDict()
        participant["ctf_id"] = admin["ctf_id"] = ctf_id
        participant["user"] = admin["user"] = user
        participant["Team"] = admin["Team"] = team

        for key, value in kwargs.items():
            if key in ("ctf_id", "ajax"):
                continue
            value_text = str(value)
            if key in ("Answer", "Question"):
                admin[key] = f'"{value_text.replace(chr(34), chr(39))}"'
            else:
                admin[key] = value_text
            if key != "Answer":
                participant[key] = value_text

        participant["Number"] = admin["Number"] = str(number)
        official_question = str(question.get("Question", "")).replace('"', "'")
        participant["QuestionOfficial"] = admin["QuestionOfficial"] = f'"{official_question}"'
        participant["BasePointsAvailable"] = admin["BasePointsAvailable"] = str(
            question.get("BasePoints", "0")
        )
        participant["StartTime"] = admin["StartTime"] = str(question.get("StartTime", "0"))
        participant["EndTime"] = admin["EndTime"] = str(question.get("EndTime", "0"))
        admin["AnswerOfficial"] = f'"{str(answer.get("Answer", "")).replace(chr(34), chr(39))}"'

        now = int(time.time())
        correct = submitted_answer.lower().strip() == str(
            answer.get("Answer", "")
        ).lower().strip()

        if correct:
            participant["Result"] = admin["Result"] = "Correct"
            participant["Penalty"] = admin["Penalty"] = "0"
            start = int(question.get("StartTime", 0))
            end = int(question.get("EndTime", 0))
            if start <= now <= end and end > start:
                base = int(question.get("BasePoints", 0))
                participant["BasePointsAwarded"] = admin["BasePointsAwarded"] = str(base)
                bonus = int(round(base * ((end - now) / float(end - start))))
                participant["SpeedBonusAwarded"] = admin["SpeedBonusAwarded"] = str(bonus)
                additional = str(question.get("AdditionalBonusPoints") or "0")
                if additional != "0":
                    participant["SolicitBonusInfo"] = admin["SolicitBonusInfo"] = "1"
                    instructions = str(
                        question.get("AdditionalBonusInstructions", "")
                    ).replace('"', "'")
                    participant["SolicitBonusInstructions"] = admin[
                        "SolicitBonusInstructions"
                    ] = f'"{instructions}"'
            else:
                participant["BasePointsAwarded"] = admin["BasePointsAwarded"] = "0"
                participant["SpeedBonusAwarded"] = admin["SpeedBonusAwarded"] = "0"
                logger_admin.warning(
                    "Question ctf_id=%s Number=%s submitted outside scoring window",
                    ctf_id,
                    number,
                )
        else:
            participant["Result"] = admin["Result"] = "Incorrect"
            participant["BasePointsAwarded"] = admin["BasePointsAwarded"] = "0"
            participant["SpeedBonusAwarded"] = admin["SpeedBonusAwarded"] = "0"
            participant["Penalty"] = admin["Penalty"] = "10"

        participant["AdditionalBonusAwarded"] = admin["AdditionalBonusAwarded"] = "0"
        for key, value in eula.items():
            participant[key] = admin[key] = value

        _signed_fields(participant)
        _copy_signature(participant, admin)
        _log_event(participant, admin)
        if wants_json:
            return _json_response({
                "ok": True,
                "ctf_id": ctf_id,
                "number": str(number),
                "result": str(participant.get("Result", "")),
                "base_points_awarded": str(participant.get("BasePointsAwarded", "0")),
                "speed_bonus_awarded": str(participant.get("SpeedBonusAwarded", "0")),
                "additional_bonus_awarded": str(participant.get("AdditionalBonusAwarded", "0")),
                "penalty": str(participant.get("Penalty", "0")),
                "solicit_bonus_info": str(participant.get("SolicitBonusInfo", "0")),
            })
        _redirect(f"/en-US/app/{APP}/result", participant)

    @expose_page(must_login=True, methods=["GET"])
    def submit_bonus_info(self, **kwargs: Any) -> None:
        cherrypy.response.headers["Content-Type"] = "text/plain; charset=utf-8"
        user, caller_key = self._caller()
        ctf_id = str(kwargs.get("ctf_id", "")).strip()
        number = kwargs.get("Number")
        bonus_info = str(kwargs.get("BonusInfo", ""))

        if (
            not ctf_id
            or not self.represents_int(number)
            or not (1 <= int(number) <= 1024)
            or not (1 <= len(bonus_info) <= 2048)
        ):
            logger_admin.error(
                "Invalid bonus submission ctf_id=%r Number=%r length=%d",
                ctf_id,
                number,
                len(bonus_info),
            )
            _redirect(ERROR_VIEW)

        try:
            privileged = _service_session_key()
            registration = _registration_for(user, ctf_id, privileged)
            team = _team_from_registration(registration, user)
            questions = _ctf_rows(_kv("ctf_questions", caller_key, app=ADMIN_APP), ctf_id)
            eula = _eula_fields(user, _kv("ctf_eulas_accepted", caller_key))
        except PermissionError:
            _redirect(f"/en-US/app/{APP}/user_agreement_required")
        except Exception:
            logger_admin.exception("Unable to load data for bonus submission")
            _redirect(ERROR_VIEW)

        question = next(
            (q for q in questions if str(q.get("Number", "")) == str(number)),
            None,
        )
        if not question:
            _redirect(ERROR_VIEW)

        participant: Dict[str, str] = {
            "ctf_id": ctf_id,
            "user": user,
            "Team": team,
        }
        admin: Dict[str, str] = {
            "ctf_id": ctf_id,
            "user": user,
            "Team": team,
        }

        for key, value in kwargs.items():
            if key in ("ctf_id", "ajax"):
                continue
            value_text = str(value)
            admin[key] = (
                f'"{value_text.replace(chr(34), chr(39))}"'
                if key in ("Answer", "Question")
                else value_text
            )
            if key not in ("Answer", "BonusInfo"):
                participant[key] = value_text

        participant["Number"] = admin["Number"] = str(number)
        participant["QuestionOfficial"] = admin["QuestionOfficial"] = (
            f'"{str(question.get("Question", "")).replace(chr(34), chr(39))}"'
        )
        participant["BasePointsAvailable"] = admin["BasePointsAvailable"] = str(
            question.get("BasePoints", "0")
        )
        participant["StartTime"] = admin["StartTime"] = str(question.get("StartTime", "0"))
        participant["EndTime"] = admin["EndTime"] = str(question.get("EndTime", "0"))
        participant["Result"] = admin["Result"] = "Bonus"

        now = int(time.time())
        in_window = (
            int(question.get("StartTime", 0))
            <= now
            <= int(question.get("EndTime", 0))
        )
        participant["AdditionalBonusAwarded"] = admin[
            "AdditionalBonusAwarded"
        ] = (
            str(question.get("AdditionalBonusPoints") or "0")
            if in_window
            else "0"
        )
        participant["BasePointsAwarded"] = admin["BasePointsAwarded"] = "0"
        participant["SpeedBonusAwarded"] = admin["SpeedBonusAwarded"] = "0"
        participant["Penalty"] = admin["Penalty"] = "0"

        for key, value in eula.items():
            participant[key] = admin[key] = value

        _signed_fields(participant)
        _copy_signature(participant, admin)
        _log_event(participant, admin)
        _redirect(f"/en-US/app/{APP}/result", participant)

    @expose_page(must_login=True, methods=["GET"])
    def adjust_score(self, **kwargs: Any) -> None:
        """Preserve the historical admin-app score-adjustment endpoint."""
        cherrypy.response.headers["Content-Type"] = "text/plain; charset=utf-8"
        user, session_key = self._caller()
        try:
            _, content = splunk.rest.simpleRequest(
                f"/services/authentication/users/{urllib.parse.quote(user, safe='')}",
                sessionKey=session_key,
                getargs={"output_mode": "json"},
            )
            details = json.loads(_decode(content))
            roles = details["entry"][0]["content"]["roles"]
        except Exception:
            logger_admin.exception("Unable to verify admin role for %s", user)
            _redirect(ADMIN_ERROR_VIEW)

        if "ctf_admin" not in roles or kwargs.get("Adjust") != "True":
            logger_admin.error("Unauthorized score adjustment attempt by %s", user)
            _redirect(ADMIN_ERROR_VIEW)

        ctf_id = str(kwargs.get("ctf_id", "")).strip()
        teams = str(kwargs.get("Teams", "")).split()
        base = str(kwargs.get("Base") or "0")
        bonus = str(kwargs.get("Bonus") or "0")
        penalty = str(kwargs.get("Penalty") or "0")
        note = str(kwargs.get("Note") or "")
        number = str(kwargs.get("Number") or "")

        if (
            not ctf_id
            or not teams
            or not note
            or not self.represents_int(number)
            or not all(self.represents_int(v) for v in (base, bonus, penalty))
        ):
            _redirect(ADMIN_ERROR_VIEW)

        try:
            privileged = _service_session_key()
            questions = _ctf_rows(_kv("ctf_questions", session_key, app=ADMIN_APP), ctf_id)
            registrations = _kv(
                "ctf_registrations",
                privileged,
                app=REGISTRATION_APP,
            )
        except Exception:
            logger_admin.exception("Unable to read questions/registrations for adjustment")
            _redirect(ADMIN_ERROR_VIEW)

        question = next(
            (q for q in questions if str(q.get("Number", "")) == number),
            None,
        )
        if not question:
            _redirect(ADMIN_ERROR_VIEW)

        def team_for_user(username: str) -> str:
            for row in registrations:
                if (
                    str(row.get("ctf_id", "")) == ctf_id
                    and str(row.get("Username", "")) == username
                ):
                    return _team_from_registration(row, username)
            return username

        last_redirect: Dict[str, str] = {}
        for team_user in teams:
            participant: Dict[str, str] = {
                "ctf_id": ctf_id,
                "admin_user": user,
                "Adjustment": "True",
                "Note": f'"{note.replace(chr(34), chr(39))}"',
                "QuestionOfficial": f'"{str(question.get("Question", "")).replace(chr(34), chr(39))}"',
                "BasePointsAvailable": str(question.get("BasePoints", "0")),
                "StartTime": str(question.get("StartTime", "0")),
                "EndTime": str(question.get("EndTime", "0")),
                "user": team_user,
                "Team": team_for_user(team_user),
                "Number": number,
                "BasePointsAwarded": base,
                "SpeedBonusAwarded": bonus,
                "AdditionalBonusAwarded": "0",
                "Penalty": penalty,
                "Result": "Incorrect" if int(penalty) else "Correct",
            }
            admin = dict(participant)
            _signed_fields(participant)
            _copy_signature(participant, admin)
            _log_event(participant, admin)
            last_redirect = participant

        _redirect(f"/en-US/app/{ADMIN_APP}/adjust_score_result", last_redirect)
