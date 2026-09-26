#!/usr/bin/env python3
"""Shared helpers for legacy-protocol Splunk search commands."""
from __future__ import annotations

import configparser
import json
import logging
import logging.handlers
import os
import urllib.parse
from typing import Any, Dict, Iterable, List

import splunk.auth
import splunk.rest
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

APP = "SA-ctf_scoreboard"
ADMIN_APP = "SA-ctf_scoreboard_admin"
REGISTRATION_APP = "SA-ctf_registration"


def setup_logger(name: str, filename: str = "scoreboard_admin.log") -> logging.Logger:
    logdir = make_splunkhome_path(["var", "log", "scoreboard"])
    os.makedirs(logdir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    path = os.path.join(logdir, filename)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "baseFilename", None) == path for h in logger.handlers):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=25_000_000, backupCount=5)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def config() -> configparser.ConfigParser:
    path = make_splunkhome_path(["etc", "apps", APP, "appserver", "controllers", "scoreboard_controller.config"])
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise RuntimeError(f"Unable to read {path}")
    return parser


def privileged_session_key() -> str:
    cfg = config()
    return str(splunk.auth.getSessionKey(
        cfg.get("ScoreboardController", "USER"),
        cfg.get("ScoreboardController", "PASS"),
    ))


def _decode(content: Any) -> str:
    return content.decode("utf-8") if isinstance(content, bytes) else str(content)


def kv(collection: str, session_key: str, app: str = APP, owner: str = "nobody") -> List[Dict[str, Any]]:
    _, content = splunk.rest.simpleRequest(
        f"/servicesNS/{owner}/{app}/storage/collections/data/{collection}",
        sessionKey=session_key,
        getargs={"output_mode": "json"},
    )
    return json.loads(_decode(content))



def registrations_to_team(registrations: Iterable[Dict[str, Any]], ctf_id: str) -> Dict[str, str]:
    """Return Username -> Team/DisplayUsername for one CTF registration."""
    result: Dict[str, str] = {}
    wanted = str(ctf_id)
    for row in registrations:
        if str(row.get("ctf_id", "")) != wanted:
            continue
        username = str(row.get("Username", ""))
        if not username:
            continue
        result[username] = str(row.get("Team") or row.get("DisplayUsername") or username)
    return result


def registration_for(
    registrations: Iterable[Dict[str, Any]],
    ctf_id: str,
    username: str,
) -> Dict[str, Any] | None:
    wanted_ctf = str(ctf_id)
    wanted_user = str(username)
    for row in registrations:
        if (
            str(row.get("ctf_id", "")) == wanted_ctf
            and str(row.get("Username", "")) == wanted_user
            and str(row.get("status", "registered")) == "registered"
        ):
            return row
    return None


def current_username(session_key: str) -> str:
    _, content = splunk.rest.simpleRequest(
        "/services/authentication/current-context",
        sessionKey=session_key,
        getargs={"output_mode": "json"},
    )
    data = json.loads(_decode(content))
    return data["entry"][0]["content"]["username"]


def user_to_team(users: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for row in users:
        username = str(row.get("Username", ""))
        if not username:
            continue
        result[username] = str(row.get("Team") or row.get("DisplayUsername") or username)
    return result


def export_search(search: str, session_key: str) -> List[Dict[str, Any]]:
    _, content = splunk.rest.simpleRequest(
        "/services/search/jobs/export",
        method="POST",
        sessionKey=session_key,
        postargs={"search": search, "output_mode": "json"},
    )
    rows: List[Dict[str, Any]] = []
    for line in _decode(content).splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and isinstance(obj.get("result"), dict):
            rows.append(obj["result"])
    return rows
