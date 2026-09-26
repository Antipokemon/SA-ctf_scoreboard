# SA-ctf_scoreboard — Splunk Enterprise 10.4 compatibility fork

This repository is a compatibility-maintenance fork of Splunk's deprecated
`SA-ctf_scoreboard` app. It targets **Splunk Enterprise 10.4** while preserving
the original app name, dashboard routes, KV Store names, indexes, scoring event
fields, and compatibility with the companion `SA-ctf_scoreboard_admin` app.

The original project was last updated for Splunk 8.2.x in January 2022. This
fork fixes the participant/scoreboard app for the Python and Simple XML changes
that matter on Splunk Enterprise 10.4.

## What changed

- Rewrote the custom controller for Python 3.9/3.13.
- Removed runtime dependence on the old bundled `splunklib`, `httplib2`, and
  other stale vendored packages for the active participant/scoring paths.
- Rewrote `getanswer`, `gethints`, and `validateevents` using Splunk's built-in
  legacy `Intersplunk` command protocol (`chunked = false`).
- Added `python.required = 3.9,3.13` to custom command definitions.
- Fixed the Python 3 HMAC/bytes conversion in `validatectf.py`.
- Fixed `decodeTCode()` and added constant-time validation support.
- Fixed Python 3 URL encoding; values are encoded as text rather than passing
  bytes to `urllib.parse.quote()`.
- Added safe log-directory creation and duplicate-handler protection.
- Fixed the historical uninitialized `found_question` path in score adjustment.
- Restored actual `validateevents` verification instead of the old macro that
  unconditionally set `Validated="1"`.
- During build, every Simple XML `<dashboard>` / `<form>` is certified with
  `version="1.1"` for jQuery 3.5+.
- Pins the upstream source commit so builds are reproducible.

## Important scope note

This repository fixes **SA-ctf_scoreboard**. The original solution also
requires the companion **SA-ctf_scoreboard_admin** application because answers
and hints are intentionally kept there. That admin app is a separate project
and should receive its own Splunk 10.4 compatibility pass before production
use.

The upstream participant app also contained an old generated Python dependency
tree under `bin/sa_ctf_scoreboard/`, primarily associated with obsolete add-on
builder scaffolding/e-badge automation. The default 10.4 build removes that
stale dependency tree. Core gameplay — users/teams, questions, answers, hints,
scoring, bonus submissions, score adjustments, and dashboards — does not rely
on it. Use `--keep-vendored-libs` only if you are deliberately testing legacy
functionality that needs those files.

## Repository layout

The GitHub repository contains the maintained compatibility files plus a
reproducible builder. The builder downloads the pinned final upstream source,
applies these files, patches all Simple XML dashboards, removes obsolete Python
vendor trees, and creates an installable Splunk app tarball.

```text
SA-ctf_scoreboard-10.4/
├── appserver/controllers/
│   ├── scoreboard_controller.py
│   └── scoreboard_controller.config.example
├── bin/
│   ├── _ctf_common.py
│   ├── getanswer.py
│   ├── gethints.py
│   ├── validatectf.py
│   └── validateevents.py
├── default/
│   ├── app.conf
│   ├── commands.conf
│   └── macros.conf
├── tools/build_from_upstream.py
├── tests/
├── .github/workflows/validate.yml
├── Makefile
├── VERSION
└── LICENSE
```

## Build the complete installable app

Requires Python 3.9+ and Internet access to GitHub.

```bash
make package
```

The result is:

```text
dist/SA-ctf_scoreboard-10.4.1.tar.gz
```

The tarball contains the **complete app**, including all original dashboards,
CSS, JavaScript, lookup definitions, metadata, icons, and static resources,
with the 10.4 compatibility overlay applied.

To retain the old upstream vendored Python libraries for troubleshooting:

```bash
python3 tools/build_from_upstream.py --keep-vendored-libs
```

That is not recommended for Splunk 10.4.

## Test before packaging

```bash
make test
```

The local test suite checks Python syntax, HMAC/tcode behavior, command config,
forbidden legacy dependencies in the maintained files, and Simple XML patching.
The GitHub Actions workflow performs the same checks and then builds the full
artifact.

## Install on Splunk Enterprise 10.4

Copy the generated tarball to your Splunk server, then install it from Splunk
Web or extract it under `$SPLUNK_HOME/etc/apps`:

```bash
cd $SPLUNK_HOME/etc/apps
tar -xzf /path/to/SA-ctf_scoreboard-10.4.1.tar.gz
```

Create the log directory if it does not already exist. The rewritten controller
also creates it automatically when loaded.

```bash
mkdir -p $SPLUNK_HOME/var/log/scoreboard
chown -R splunk:splunk $SPLUNK_HOME/var/log/scoreboard
```

Create the service account used to retrieve protected answers/hints. Keep the
permissions from the original scoreboard design; do not give competitors read
access to the answer collection.

```bash
$SPLUNK_HOME/bin/splunk add user svcaccount \
  -password '<STRONG_PASSWORD>' \
  -role ctf_answers_service \
  -auth admin:'<ADMIN_PASSWORD>'
```

Configure the controller:

```bash
cd $SPLUNK_HOME/etc/apps/SA-ctf_scoreboard/appserver/controllers
cp scoreboard_controller.config.example scoreboard_controller.config
openssl rand -hex 32
```

Edit `scoreboard_controller.config`:

```ini
[ScoreboardController]
USER = svcaccount
PASS = <STRONG_PASSWORD>
VKEY = <OUTPUT_FROM_OPENSSL_RAND>
```

Protect the file:

```bash
chmod 600 scoreboard_controller.config
chown splunk:splunk scoreboard_controller.config
```

Restart Splunk:

```bash
$SPLUNK_HOME/bin/splunk restart
```

## 10.4 checks after install

Verify the controller loaded:

```bash
ls -l $SPLUNK_HOME/var/log/scoreboard/
tail -50 $SPLUNK_HOME/var/log/scoreboard/scoreboard.log
tail -50 $SPLUNK_HOME/var/log/scoreboard/scoreboard_admin.log
```

Verify the custom commands are registered:

```spl
| makeresults
| eval tcode="3130", user="test", Number="1", Result="Correct", BasePointsAwarded="0", SpeedBonusAwarded="0", AdditionalBonusAwarded="0", Penalty="0", vcode="invalid"
| validateevents
```

`Validated` should be `0` for the deliberately invalid signature.

Then test the actual workflow with a non-admin competitor account:

1. Open **Capture the Flag**.
2. Accept the user agreement if your event uses it.
3. Open a question.
4. Submit an incorrect answer and confirm the result/penalty is recorded.
5. Submit a correct answer and confirm base/speed points are recorded.
6. Purchase a hint and confirm it becomes visible only to that team.
7. Expand submission history and confirm protected submitted answers are visible
   only to members of that team.
8. Confirm the public scoreboard updates.

## Splunk 10.4 CherryPy setting

Splunk Enterprise 10.4 still enables custom CherryPy controllers by default,
but Splunk has deprecated them for a future release. This app still uses a
controller because that is how the original scoreboard securely separates
competitor requests from the protected answers/hints store.

If your instance has proactively disabled custom controllers, this app's
submission endpoints will return 404. Check the appserver security setting in
`web-features.conf` and ensure custom CherryPy controllers are not disabled for
the host running this CTF.

This fork is therefore a **Splunk 10.4 compatibility target**, not a guarantee
for a future Splunk release that removes CherryPy controllers entirely.

## Push this repository to GitHub

```bash
git init
git add .
git commit -m "feat: Splunk 10.4 compatibility fork"
git branch -M main
git remote add origin git@github.com:<YOUR_USER>/<YOUR_REPO>.git
git push -u origin main
```

The included GitHub Actions workflow validates every push. You can create a
release from the generated `dist/SA-ctf_scoreboard-10.4.1.tar.gz` artifact.

## Upstream

Original project: https://github.com/splunk/SA-ctf_scoreboard

Pinned source commit used by this build:
`bef2d5cb254b0d6d4699f4f445e6fc914a35ceed`

The original app and this compatibility work retain the upstream CC0 license.
