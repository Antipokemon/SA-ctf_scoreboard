# Capture the Flag

`SA-ctf_scoreboard` is the participant-facing Capture the Flag application. This repository modernizes the original Splunk CTF scoreboard for Splunk Enterprise 10.4 and adds event scoping required for multiple CTFs to run concurrently.

The app handles:

- participant welcome and event context
- questions
- answer submission
- hint display and purchase
- participant/team score events
- participant scoring dashboards
- CTF-specific question selection

## Requirements

- Splunk Enterprise 10.4
- `SA-ctf_scoreboard_admin`
- `SA-ctf_registration`
- A configured scoreboard service account
- Splunk roles:
  - `ctf_competitor` for participants
  - `ctf_admin` for CTF administrators
  - `ctf_answers_service` for the privileged answer/service account
- Python 3 as provided by Splunk 10.4
- The `scoreboard` and `scoreboard_admin` indexes
- CTF content containing a valid `ctf_id`

The modernized app does not depend on the historical bundled Python 2 SDK.

## App identity

App ID:

```text
SA-ctf_scoreboard
```

Display name:

```text
Capture the Flag
```

## Service account configuration

Create:

```text
appserver/controllers/scoreboard_controller.config
```

from:

```text
appserver/controllers/scoreboard_controller.config.example
```

Example:

```ini
[ScoreboardController]
USER = svcaccount
PASS = REPLACE_WITH_PASSWORD
VKEY = REPLACE_WITH_RANDOM_VALIDATION_KEY
```

Do not commit the real password or validation key.

The service account requires access to the protected answer data and the CTF registration data used to resolve participant/team membership.

## Multi-CTF model

All event-specific content and scoring must be associated with a stable:

```text
ctf_id
```

Examples:

```text
asteron-easy-2026
asteron-medium-2026
holiday-hunt-2026
```

Question identity is:

```text
ctf_id + Number
```

not simply:

```text
Number
```

This means two CTFs can both have Question 1 without colliding.

### Event-scoped data

The following data must carry `ctf_id` where applicable:

```text
ctf_questions
ctf_answers
ctf_hints
ctf_hint_entitlements
scoreboard events
scoreboard_admin events
ctf_registrations
```

## Relationship to registration

`SA-ctf_registration` is the source of participant-to-event registration.

A registration is uniquely identified by:

```text
ctf_id + Username
```

The participant app loads the selected CTF context and obtains values including:

```text
ctf_id
ctf_event_name
ctf_event_starts
ctf_event_ends
ctf_user
ctf_DisplayUsername
ctf_Team
ctf_SearchUrl
```

If the user belongs to multiple CTFs, a CTF can be selected with:

```text
/en-US/app/SA-ctf_scoreboard/questions?ctf_id=asteron-easy-2026
```

## Preparing a CTF for the scoreboard

Creating an event in `SA-ctf_registration` does not create questions, answers, or hints automatically.

For each CTF:

1. create the CTF in `SA-ctf_registration`
2. note the exact `ctf_id`
3. prepare questions using that same `ctf_id`
4. prepare answers using that same `ctf_id`
5. prepare hints using that same `ctf_id`
6. load the content into the appropriate KV Store collections
7. verify participants can register
8. verify the questions page returns only the selected CTF's questions

## Questions

Questions live in:

```text
ctf_questions
```

Required event-scoped fields include:

```text
ctf_id
Number
Question
StartTime
EndTime
BasePoints
AdditionalBonusPoints
AdditionalBonusInstructions
```

Example:

```csv
ctf_id,Number,Question,StartTime,EndTime,BasePoints,AdditionalBonusPoints,AdditionalBonusInstructions
asteron-easy-2026,1,"What host was initially compromised?",1791806400,1791982800,100,0,""
```

`Number` only needs to be unique inside a single `ctf_id`.

## Question scoring times

`StartTime` and `EndTime` are question-scoring times and are distinct from the CTF registration/event times managed by `SA-ctf_registration`.

Use them to control when a question can award normal time-based points.

The CTF itself is bounded by:

```text
event_starts
event_ends
```

in the registration app.

A question is bounded by:

```text
StartTime
EndTime
```

in `ctf_questions`.

These should normally fit inside the parent event window.

## Answer submission

The question form submits:

```text
ctf_id
Number
Question
Answer
```

The controller validates the answer against the answer record having the same:

```text
ctf_id + Number
```

Score events written to the scoreboard indexes also include `ctf_id`.

This prevents answer or score data from one event being used by another event with the same question number.

## Hints

Hints are scoped by:

```text
ctf_id + Number + HintNumber
```

Hint entitlements also include `ctf_id`.

A hint purchased for one CTF does not grant the same numbered hint in another CTF.

## Participant workflow

1. Register for the CTF in **Capture the Flag Registration**.
2. Receive the required `ctf_competitor` role.
3. Open **Capture the Flag**.
4. Select/open the intended `ctf_id`.
5. View questions for only that event.
6. Submit answers and purchase hints.
7. Score events are written with the selected `ctf_id`.

## Starting a CTF

Before event start:

1. verify the registration event is enabled
2. verify participants are registered
3. verify the `ctf_id` in registration exactly matches the content
4. verify questions exist for the event
5. verify answers exist for the event
6. verify hints, if used, exist for the event
7. verify question StartTime/EndTime values
8. verify the event starts/ends values in `SA-ctf_registration`
9. verify the participant can open the questions page with the correct event

Recommended validation search:

```spl
| inputlookup ctf_questions
| stats count min(StartTime) as earliest_question max(EndTime) as latest_question by ctf_id
```

## Running concurrent CTFs

Concurrent events are supported by scoping all data and searches to `ctf_id`.

Example:

```text
asteron-easy-2026 / Question 1
asteron-hard-2026 / Question 1
```

are separate questions.

Do not load event-specific records without `ctf_id`; unscoped rows can cause incomplete or ambiguous behavior.

## Closing a CTF

At the end of a CTF:

1. allow the registration event's `event_ends` time to pass
2. close registration if it has not already closed
3. confirm no new participant workflow should use that `ctf_id`
4. retain the historical question and score data for investigations/reporting
5. archive/export data if required by your event process
6. disable the event in `SA-ctf_registration` when it should no longer appear to users

Do not reuse the old `ctf_id` for another event.

## Indexes

Participant score events:

```text
index=scoreboard
```

Protected/admin score events:

```text
index=scoreboard_admin
```

Example event-scoped search:

```spl
index=scoreboard ctf_id="asteron-easy-2026"
| stats sum(BasePointsAwarded) as BasePoints
        max(SpeedBonusAwarded) as SpeedBonus
        sum(Penalty) as Penalty
  by Team Number
```

## KV Store collections

Participant app collections include:

```text
ctf_questions
ctf_hint_entitlements
ctf_badges
ctf_badge_entitlements
ctf_stealth
ctf_eulas
ctf_eulas_accepted
```

`ctf_questions` and `ctf_hint_entitlements` are event-scoped.

Registration data is owned by:

```text
SA-ctf_registration
```

and should not be replaced with a single global `ctf_users` row when running multiple concurrent events.

## Important multi-CTF files

```text
bin/_ctf_common.py
bin/getanswer.py
bin/gethints.py
appserver/controllers/scoreboard_controller.py
appserver/static/ctf_event_context.js
default/collections.conf
default/transforms.conf
default/data/ui/views/questions.xml
default/data/ui/views/question.xml
```

## Splunk 10.4 compatibility

The compatibility branch includes Python 3-safe custom search commands and controller code.

Custom commands should remain configured with:

```ini
chunked = false
enableheader = true
passauth = true
python.required = 3.9,3.13
```

where session-key access is required by the command.

## Logs

Scoreboard logs:

```text
$SPLUNK_HOME/var/log/scoreboard/scoreboard.log
$SPLUNK_HOME/var/log/scoreboard/scoreboard_admin.log
```

Rootless Podman example:

```bash
podman exec -u splunk splunk \
  tail -f /opt/splunk/var/log/scoreboard/scoreboard.log
```

## Troubleshooting

### No questions appear

Verify:

```spl
| inputlookup ctf_questions
| search ctf_id="YOUR-CTF-ID"
```

Then verify the browser URL/event context is using the same `ctf_id`.

### User is not recognized as registered

Verify the registration exists in `SA-ctf_registration` for:

```text
ctf_id + Username
```

and that its status is registered.

### Answer is never correct

Verify the answer collection in `SA-ctf_scoreboard_admin` contains the same:

```text
ctf_id
Number
```

as the question.

### Hints do not appear

Verify both:

```text
ctf_id
Number
```

match between the question and hint data.

### Old JavaScript is still loaded

Splunk Web and the browser may cache static assets. Restart Splunk after deployment and use a private browser window when validating static changes.

## Related apps

- `SA-ctf_registration` — CTF definitions, time windows, participant registration, and role assignment
- `SA-ctf_scoreboard_admin` — answers, hints, content administration, and CTF administration

## Question collection ownership

`SA-ctf_scoreboard` does not own the `ctf_questions` KV Store. The authoritative `ctf_questions`, `ctf_answers`, and `ctf_hints` collections live in `SA-ctf_scoreboard_admin`.

Participant dashboards continue to use `| inputlookup ctf_questions`; the admin app exports that lookup system-wide with participant read access. Controller code reads `ctf_questions` explicitly from the `SA-ctf_scoreboard_admin` namespace. This avoids duplicate same-named collections whose resolution changes depending on app context or upgrade order.

## Participant-app KV Store ownership

This app owns participant/runtime collections such as:

```text
ctf_hint_entitlements
ctf_badges
ctf_badge_entitlements
ctf_stealth
ctf_eulas
ctf_eulas_accepted
```

It does **not** own `ctf_questions`, `ctf_answers`, or `ctf_hints`; those are owned by `SA-ctf_scoreboard_admin`. It also does not own `ctf_events` or `ctf_registrations`; those are owned by `SA-ctf_registration`. The compatibility overlay keeps the participant-owned collection definitions explicitly so rebuilding this app cannot accidentally drop them.

## Participant question experience

The questions view is intentionally compact for large CTFs. It shows 20 questions per page, a completed/remaining/progress summary, and only the fields a participant needs while choosing the next challenge. Selecting a row opens the question detail page for answer submission and hints.

The legacy expandable table row was removed. It depended on the retired `ctf_users` lookup and produced errors after participant identity moved to `SA-ctf_registration`. The `get_user_info` compatibility macros now use the `Team`, `DisplayUsername`, `Username`, and `user` fields already present in scoreboard events instead of requiring `ctf_users`.

## Card-based challenge view and live team state

The participant **Challenges** view uses a card grid instead of a long question table. Selecting a card opens an in-page modal where the participant can submit an answer and purchase hints without navigating away from the challenge list.

The challenge state search refreshes every five seconds using the current `ctf_id` and team. As a result, when another team member submits a correct answer, all open team sessions update automatically: the challenge card moves to the solved state, the completed/remaining totals change, and an open modal for that challenge is updated without a page reload.

The view provides client-side filters for all/open/solved/attempted challenges and a challenge search box. Solved cards use a distinct border so progress is visible at a glance.

Answer and hint actions support an AJAX response mode used by the modal UI. Existing direct controller links continue to use the historical redirect workflow for compatibility.

## Challenge modal runtime behavior

The card-based Challenges view binds the event image from `SA-ctf_registration.ctf_events.image_url` after the event context is loaded. If the configured image cannot be loaded, the built-in scoreboard shield is used as a fallback.

Challenge-modal hints are retrieved from the scoreboard controller as JSON. The controller reads protected hint text from `SA-ctf_scoreboard_admin`, applies team-scoped hint entitlements, and returns either an unlock action or the previously purchased hint text. The legacy `gethints` search command remains available and receives the caller session key through `passauth = true`.

Answer submission and hint purchase use JSON responses when called from the modal. Validation and permission failures are returned to the modal instead of redirecting an AJAX request to an HTML error page. If no default CTF EULA is configured, answer and hint actions do not require an acceptance record. If a default EULA is configured, acceptance is still required.

## Event artwork on the Challenges page

The Challenges page uses the selected registration event's `image_url`. The client normalizes legacy `/static/apps/...` URLs to Splunk's `/static/app/...` route, verifies the image can load, and retries a source-controlled `/images/<filename>` path when an older event points to `/images/uploads/<filename>`. The built-in shield is used only after the event image candidates fail.

To troubleshoot a missing image, first verify the event record's `image_url`, then verify the corresponding file exists under `SA-ctf_registration/appserver/static/images` (or its `uploads` subdirectory).
