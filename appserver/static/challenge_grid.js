require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function($, mvc) {
    "use strict";

    var challengeManager = mvc.Components.get("challengeData");
    var challengeResults = challengeManager ? challengeManager.data("results", {count: 0}) : null;
    var defaultTokens = mvc.Components.get("default");
    var submittedTokens = mvc.Components.get("submitted");
    var challengeRows = [];
    var rowByNumber = {};
    var lastServerStatus = {};
    var pendingLocal = {};
    var ownSolveUntil = {};
    var activeNumber = null;
    var activeFilter = "all";
    var searchText = "";
    var initialized = false;

    function token(name) {
        return String(
            (submittedTokens && submittedTokens.get(name)) ||
            (defaultTokens && defaultTokens.get(name)) ||
            ""
        );
    }

    function numberValue(value) {
        var parsed = parseInt(value, 10);
        return isNaN(parsed) ? 0 : parsed;
    }

    function eventState() {
        return token("ctf_event_state").toUpperCase();
    }

    function eventPlayable() {
        if (token("ctf_context_ready") !== "1" || eventState() !== "IN_PROGRESS") {
            return false;
        }
        var starts = Date.parse(token("ctf_event_starts"));
        var ends = Date.parse(token("ctf_event_ends"));
        var now = Date.now();
        if (!isNaN(starts) && now < starts) {
            return false;
        }
        if (!isNaN(ends) && now > ends) {
            return false;
        }
        return true;
    }

    function eventLockMessage() {
        var state = eventState();
        if (state === "COMPLETED") {
            return "This CTF event has ended. Challenges are read-only; answers and new hint purchases are locked.";
        }
        if (state === "UPCOMING") {
            return "This CTF event has not started yet. Challenges are read-only until the event begins.";
        }
        if (state === "DISABLED") {
            return "This CTF event is disabled. Challenges are read-only.";
        }
        if (token("ctf_context_ready") !== "1") {
            return "Waiting for the CTF event context. Challenge actions are temporarily locked.";
        }
        return "Challenge actions are currently locked.";
    }

    function updateEventGate() {
        var playable = eventPlayable();
        var $gate = $("#ctf_event_gate");
        $gate.toggle(!playable).text(playable ? "" : eventLockMessage());
        if (activeNumber !== null && rowByNumber[activeNumber]) {
            updateModalFromRow(rowByNumber[activeNumber]);
        }
        $(".ctf-unlock-hint").prop("disabled", !playable);
    }

    function statusClass(status) {
        if (status === "Correct") {
            return "is-solved";
        }
        if (status === "Incorrect") {
            return "is-incorrect";
        }
        return "is-unanswered";
    }

    function statusLabel(status) {
        if (status === "Correct") {
            return "Solved";
        }
        if (status === "Incorrect") {
            return "Attempted";
        }
        return "Open";
    }

    function humanizeSubject(value) {
        var text = String(value || "Challenges").replace(/[_-]+/g, " ").trim();
        if (!text) {
            return "Challenges";
        }
        return text.replace(/\b\w/g, function(ch) { return ch.toUpperCase(); });
    }

    function normalizedChallenge(raw) {
        var number = numberValue(raw.Number);
        return {
            Number: number,
            ChallengeID: String(raw.ChallengeID || ("Q" + String(number).padStart(3, "0"))),
            Subject: (function() {
                var subject = String(raw.Subject || raw.Category || "").trim();
                return subject || "Challenges";
            }()),
            Question: String(raw.Question || "Question " + number),
            Status: String(raw.Status || "Unanswered"),
            BasePoints: numberValue(raw.BasePoints),
            Attempts: numberValue(raw.Attempts),
            IncorrectAttempts: numberValue(raw.IncorrectAttempts),
            CorrectAttempts: numberValue(raw.CorrectAttempts),
            QuestionScore: numberValue(raw.QuestionScore)
        };
    }

    function mergePending(row) {
        var pending = pendingLocal[row.Number];
        if (!pending) {
            return row;
        }
        if (Date.now() > pending.until) {
            delete pendingLocal[row.Number];
            return row;
        }
        if (row.Status === "Correct" || row.Attempts >= pending.minimumAttempts) {
            delete pendingLocal[row.Number];
            return row;
        }
        row.Status = pending.status;
        row.Attempts = Math.max(row.Attempts, pending.minimumAttempts);
        if (pending.status === "Correct") {
            row.CorrectAttempts = Math.max(row.CorrectAttempts, 1);
        } else if (pending.status === "Incorrect") {
            row.IncorrectAttempts = Math.max(row.IncorrectAttempts, 1);
        }
        return row;
    }

    function resultsToObjects(data) {
        if (!data || !data.fields || !data.rows) {
            return [];
        }
        var names = data.fields.map(function(field) {
            return typeof field === "string" ? field : field.name;
        });
        return data.rows.map(function(values) {
            var row = {};
            names.forEach(function(name, index) {
                row[name] = values[index];
            });
            return row;
        });
    }

    function parseResults(data) {
        return resultsToObjects(data).map(function(row) {
            return mergePending(normalizedChallenge(row));
        });
    }

    function toast(message) {
        var $toast = $("#ctf_team_toast");
        $toast.stop(true, true).text(message).addClass("is-visible");
        window.setTimeout(function() {
            $toast.removeClass("is-visible");
        }, 4500);
    }

    function observeTeamChanges(rows) {
        rows.forEach(function(row) {
            var key = String(row.Number);
            var previous = lastServerStatus[key];
            var local = pendingLocal[row.Number];
            var ownSolve = ownSolveUntil[row.Number] && ownSolveUntil[row.Number] > Date.now();
            if (initialized && previous && previous !== "Correct" && row.Status === "Correct") {
                if (!ownSolve && (!local || local.status !== "Correct")) {
                    toast("A teammate solved " + row.ChallengeID + ".");
                }
            }
            if (row.Status === "Correct" && ownSolveUntil[row.Number] && !ownSolve) {
                delete ownSolveUntil[row.Number];
            }
            lastServerStatus[key] = row.Status;
        });
        initialized = true;
    }

    function updateProgress() {
        var total = challengeRows.length;
        var completed = challengeRows.filter(function(row) { return row.Status === "Correct"; }).length;
        var remaining = Math.max(total - completed, 0);
        var teamScore = challengeRows.reduce(function(totalScore, row) {
            return totalScore + numberValue(row.QuestionScore);
        }, 0);
        $("#ctf_progress_completed_value").text(completed);
        $("#ctf_progress_remaining_value").text(remaining);
        $("#ctf_team_score_value").text(teamScore.toLocaleString());
    }

    function matchesFilter(row) {
        if (activeFilter === "solved" && row.Status !== "Correct") {
            return false;
        }
        if (activeFilter === "incorrect" && row.Status !== "Incorrect") {
            return false;
        }
        if (activeFilter === "open" && row.Status === "Correct") {
            return false;
        }
        if (searchText) {
            var haystack = (row.ChallengeID + " " + row.Question + " " + row.Subject).toLowerCase();
            if (haystack.indexOf(searchText) === -1) {
                return false;
            }
        }
        return true;
    }

    function challengeCard(row) {
        var $card = $("<button/>", {
            type: "button",
            class: "ctf-challenge-card " + statusClass(row.Status),
            "data-number": row.Number,
            "aria-label": row.ChallengeID + ": " + row.Question
        });
        var $top = $("<div/>", {class: "ctf-challenge-card-top"});
        $top.append($("<span/>", {class: "ctf-challenge-code", text: row.ChallengeID}));
        $top.append($("<span/>", {class: "ctf-card-status", text: statusLabel(row.Status)}));
        $card.append($top);
        $card.append($("<div/>", {class: "ctf-challenge-question", text: row.Question}));
        var $bottom = $("<div/>", {class: "ctf-challenge-card-bottom"});
        $bottom.append($("<span/>", {text: row.BasePoints + " pts"}));
        if (row.Attempts > 0) {
            $bottom.append($("<span/>", {text: row.Attempts + (row.Attempts === 1 ? " attempt" : " attempts")}));
        }
        $card.append($bottom);
        return $card;
    }

    function renderChallenges() {
        var $root = $("#ctf_challenge_sections").empty();
        var groups = {};
        var subjectOrder = [];
        var visibleCount = 0;

        challengeRows.forEach(function(row) {
            if (!matchesFilter(row)) {
                return;
            }
            visibleCount += 1;
            var key = row.Subject || "Challenges";
            if (!groups[key]) {
                groups[key] = [];
                subjectOrder.push(key);
            }
            groups[key].push(row);
        });

        // Keep subjects in challenge-number order instead of alphabetizing them.
        // This preserves the authored learning/attack progression in the CSV.
        subjectOrder.forEach(function(subject) {
            var rows = groups[subject];
            var $section = $("<section/>", {class: "ctf-challenge-section", "data-subject": subject});
            var solved = rows.filter(function(row) { return row.Status === "Correct"; }).length;
            var $heading = $("<div/>", {class: "ctf-challenge-section-heading"});
            $heading.append($("<h2/>", {text: humanizeSubject(subject)}));
            $heading.append($("<span/>", {text: solved + " / " + rows.length + " solved"}));
            $section.append($heading);

            var $grid = $("<div/>", {class: "ctf-challenge-grid"});
            rows.sort(function(a, b) { return a.Number - b.Number; }).forEach(function(row) {
                $grid.append(challengeCard(row));
            });
            $section.append($grid);
            $root.append($section);
        });

        $("#ctf_challenge_empty").toggle(visibleCount === 0);
    }

    function updateModalFromRow(row) {
        if (!row) {
            return;
        }
        $("#ctf_modal_challenge_id").text(row.ChallengeID);
        $("#ctf_modal_title").text(row.Question);
        $("#ctf_modal_points").text(row.BasePoints);
        $("#ctf_modal_attempts").text(row.Attempts);
        $("#ctf_modal_status")
            .removeClass("is-solved is-incorrect is-unanswered")
            .addClass(statusClass(row.Status))
            .text(statusLabel(row.Status));

        var solved = row.Status === "Correct";
        var playable = eventPlayable();
        var disabled = solved || !playable;
        var buttonText = solved ? "Solved" : (playable ? "Submit" : (eventState() === "COMPLETED" ? "Event ended" : "Locked"));
        $("#ctf_answer_input").prop("disabled", disabled);
        $("#ctf_answer_submit").prop("disabled", disabled).text(buttonText);
    }

    function updateRows(rows) {
        observeTeamChanges(rows);
        challengeRows = rows;
        rowByNumber = {};
        challengeRows.forEach(function(row) { rowByNumber[row.Number] = row; });
        updateProgress();
        renderChallenges();
        if (activeNumber !== null && rowByNumber[activeNumber]) {
            updateModalFromRow(rowByNumber[activeNumber]);
        }
        $("#ctf_live_status").text("Team status updated " + new Date().toLocaleTimeString());
    }

    function closeModal() {
        activeNumber = null;
        $("#ctf_challenge_modal").removeClass("is-open").attr("aria-hidden", "true");
        $("body").removeClass("ctf-modal-open");
        $("#ctf_modal_message").hide().removeClass("is-success is-error").text("");
        $("#ctf_modal_hints").empty();
    }

    function splQuote(value) {
        return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    }

    function renderHints(rows) {
        var $root = $("#ctf_modal_hints").empty();
        $("#ctf_modal_hints_loading").hide();
        rows = rows || [];
        if (!rows.length) {
            $root.append($("<div/>", {class: "ctf-no-hints", text: "No hints are available for this challenge."}));
            return;
        }
        rows.forEach(function(row) {
            var purchased = row.purchased === true || String(row.purchased) === "true";
            var $hint = $("<div/>", {class: "ctf-hint-item"});
            var $header = $("<div/>", {class: "ctf-hint-header"});
            $header.append($("<strong/>", {text: "Hint " + row.hint_number}));
            $header.append($("<span/>", {text: row.hint_cost + " pts"}));
            $hint.append($header);
            if (purchased) {
                $hint.append($("<div/>", {class: "ctf-hint-text", text: row.hint || ""}));
            } else {
                var playable = eventPlayable();
                $hint.append($("<button/>", {
                    type: "button",
                    class: "ctf-unlock-hint btn",
                    "data-hint-number": row.hint_number,
                    disabled: !playable,
                    text: playable ? ("Unlock hint for " + row.hint_cost + " points") : "Hint locked - event not active"
                }));
            }
            $root.append($hint);
        });
    }

    function ajaxErrorMessage(xhr, fallback) {
        if (xhr && xhr.responseJSON && xhr.responseJSON.error) {
            return String(xhr.responseJSON.error);
        }
        if (xhr && xhr.responseText) {
            try {
                var parsed = JSON.parse(xhr.responseText);
                if (parsed && parsed.error) {
                    return String(parsed.error);
                }
            } catch (e) { /* response was not JSON */ }
        }
        return fallback;
    }

    function loadHints(number) {
        $("#ctf_modal_hints_loading").show().text("Loading hints…");
        $("#ctf_modal_hints").empty();

        $.ajax({
            url: "/en-US/custom/SA-ctf_scoreboard/scoreboard_controller/challenge_hints",
            method: "GET",
            dataType: "json",
            cache: false,
            data: {
                ctf_id: token("ctf_id"),
                Number: number,
                ajax: "1"
            }
        }).done(function(data) {
            renderHints(data.hints || []);
        }).fail(function(xhr) {
            $("#ctf_modal_hints_loading").hide();
            $("#ctf_modal_hints").empty().append($("<div/>", {
                class: "ctf-no-hints is-error",
                text: ajaxErrorMessage(xhr, "Unable to load hints.")
            }));
        });
    }

    function openModal(number) {
        var row = rowByNumber[number];
        if (!row) {
            return;
        }
        activeNumber = number;
        updateModalFromRow(row);
        $("#ctf_modal_message").hide().removeClass("is-success is-error").text("");
        $("#ctf_answer_input").val("");
        $("#ctf_challenge_modal").addClass("is-open").attr("aria-hidden", "false");
        $("body").addClass("ctf-modal-open");
        loadHints(number);
        window.setTimeout(function() { $("#ctf_answer_input").trigger("focus"); }, 50);
    }

    function showModalMessage(message, success) {
        $("#ctf_modal_message")
            .removeClass("is-success is-error")
            .addClass(success ? "is-success" : "is-error")
            .text(message)
            .show();
    }

    function submitAnswer() {
        var row = rowByNumber[activeNumber];
        var answer = String($("#ctf_answer_input").val() || "");
        if (!eventPlayable()) {
            showModalMessage(eventLockMessage(), false);
            updateEventGate();
            return;
        }
        if (!row || !answer.trim()) {
            showModalMessage("Enter an answer before submitting.", false);
            return;
        }

        var $button = $("#ctf_answer_submit").prop("disabled", true).text("Submitting…");
        $.ajax({
            url: "/en-US/custom/SA-ctf_scoreboard/scoreboard_controller/submit_question",
            method: "GET",
            dataType: "json",
            cache: false,
            data: {
                ctf_id: token("ctf_id"),
                Number: row.Number,
                Question: row.Question,
                Answer: answer,
                ajax: "1"
            }
        }).done(function(data) {
            var result = String(data.result || "");
            var correct = result === "Correct";
            pendingLocal[row.Number] = {
                status: correct ? "Correct" : "Incorrect",
                minimumAttempts: row.Attempts + 1,
                until: Date.now() + 12000
            };
            row.Status = correct ? "Correct" : "Incorrect";
            row.Attempts += 1;
            if (correct) {
                ownSolveUntil[row.Number] = Date.now() + 15000;
                row.CorrectAttempts = Math.max(row.CorrectAttempts, 1);
                showModalMessage("Correct! Your team solved this challenge.", true);
                $("#ctf_answer_input").val("");
            } else {
                row.IncorrectAttempts += 1;
                showModalMessage("Incorrect answer. Try again.", false);
                $("#ctf_answer_input").trigger("select");
            }
            updateProgress();
            renderChallenges();
            updateModalFromRow(row);
        }).fail(function(xhr) {
            showModalMessage(ajaxErrorMessage(xhr, "Unable to submit the answer."), false);
        }).always(function() {
            var current = rowByNumber[activeNumber];
            var solved = current && current.Status === "Correct";
            var playable = eventPlayable();
            $button.prop("disabled", solved || !playable)
                .text(solved ? "Solved" : (playable ? "Submit" : (eventState() === "COMPLETED" ? "Event ended" : "Locked")));
        });
    }

    function purchaseHint(hintNumber) {
        var row = rowByNumber[activeNumber];
        if (!row) {
            return;
        }
        if (!eventPlayable()) {
            showModalMessage(eventLockMessage(), false);
            updateEventGate();
            return;
        }
        $.ajax({
            url: "/en-US/custom/SA-ctf_scoreboard/scoreboard_controller/purchase_hint",
            method: "GET",
            dataType: "json",
            cache: false,
            data: {
                ctf_id: token("ctf_id"),
                Number: row.Number,
                HintNumber: hintNumber,
                ajax: "1"
            }
        }).done(function(data) {
            var prefix = data.already_purchased ? "Hint already unlocked: " : "Hint unlocked: ";
            showModalMessage(prefix + String(data.hint || ""), true);
            loadHints(row.Number);
        }).fail(function(xhr) {
            showModalMessage(ajaxErrorMessage(xhr, "Unable to unlock the hint."), false);
        });
    }

    if (challengeResults) {
        challengeResults.on("data", function() {
            updateRows(parseResults(challengeResults.data()));
        });
    } else {
        $("#ctf_challenge_empty").text("Challenge search is unavailable.").show();
    }

    $(document).on("click", ".ctf-challenge-card", function() {
        openModal(numberValue($(this).attr("data-number")));
    });

    $(document).on("click", ".ctf-filter", function() {
        activeFilter = String($(this).attr("data-filter") || "all");
        $(".ctf-filter").removeClass("is-active");
        $(this).addClass("is-active");
        renderChallenges();
    });

    $(document).on("input", "#ctf_challenge_search", function() {
        searchText = String($(this).val() || "").trim().toLowerCase();
        renderChallenges();
    });

    $(document).on("click", "[data-modal-close]", function() {
        closeModal();
    });

    $(document).on("keydown", function(event) {
        if (event.key === "Escape" && $("#ctf_challenge_modal").hasClass("is-open")) {
            closeModal();
        }
    });

    $(document).on("submit", "#ctf_answer_form", function(event) {
        event.preventDefault();
        submitAnswer();
    });

    $(document).on("click", ".ctf-unlock-hint", function() {
        purchaseHint(numberValue($(this).attr("data-hint-number")));
    });

    $(document).on("ctf:event-context-ready", function() {
        updateEventGate();
        if (activeNumber !== null && rowByNumber[activeNumber]) {
            loadHints(activeNumber);
        }
    });

    $(document).on("ctf:event-context-failed", function() {
        updateEventGate();
    });

    updateEventGate();
    window.setInterval(updateEventGate, 1000);
});
