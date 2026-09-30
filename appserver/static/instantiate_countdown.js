require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function($, mvc) {
    "use strict";

    var tokens = mvc.Components.get("default");
    var deadline = null;
    var eventState = "";
    var timer = null;

    function parseTimestamp(value) {
        var text = String(value || "").trim();
        if (!text) {
            return null;
        }
        var parsed = Date.parse(text);
        return isNaN(parsed) ? null : parsed;
    }

    function formatRemaining(milliseconds) {
        var totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
        var days = Math.floor(totalSeconds / 86400);
        var hours = Math.floor((totalSeconds % 86400) / 3600);
        var minutes = Math.floor((totalSeconds % 3600) / 60);
        var seconds = totalSeconds % 60;

        function pad(value) {
            return String(value).padStart(2, "0");
        }

        return pad(days) + ":" + pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
    }

    function render() {
        var $clock = $("#clock");
        var $label = $("#clock-text");
        if (!$clock.length) {
            return;
        }

        if (eventState === "COMPLETED") {
            $clock.text("00:00:00:00");
            $label.text("Event has ended");
            return;
        }

        if (!deadline) {
            $clock.text("--:--:--:--");
            $label.text("Waiting for event timing");
            return;
        }

        var remaining = deadline - Date.now();
        if (remaining <= 0) {
            $clock.text("00:00:00:00");
            $label.text("Event has ended");
            return;
        }

        $clock.text(formatRemaining(remaining));
        $label.text("Days : Hours : Minutes : Seconds");
    }

    function refreshFromTokens() {
        deadline = parseTimestamp(tokens.get("ctf_event_ends"));
        eventState = String(tokens.get("ctf_event_state") || "").toUpperCase();
        render();
    }

    function startTimer() {
        if (timer) {
            window.clearInterval(timer);
        }
        refreshFromTokens();
        timer = window.setInterval(render, 1000);
    }

    if (tokens && tokens.on) {
        tokens.on("change:ctf_event_ends", refreshFromTokens);
        tokens.on("change:ctf_event_state", refreshFromTokens);
    }

    $(document).on("ctf:event-context-ready", function() {
        refreshFromTokens();
    });
    $(document).on("ctf:event-context-failed", function() {
        eventState = "";
        deadline = null;
        render();
    });

    startTimer();
});
