require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function($, mvc) {
    "use strict";

    var defaultTokens = mvc.Components.get("default");
    var submittedTokens = mvc.Components.get("submitted");
    var endpoint = "/en-US/splunkd/__raw/services/ctf_registration/events";

    function setToken(name, value) {
        defaultTokens.set(name, value);
        if (submittedTokens) {
            submittedTokens.set(name, value);
        }
    }

    function setEventImage(imageUrl) {
        var fallback = "/static/app/SA-ctf_scoreboard/ctflogo.png";
        var requested = String(imageUrl || "").trim();
        var $logo = $("#ctflogo");

        if (!$logo.length) {
            return;
        }

        $logo.off("error.ctfEventImage");
        $logo.on("error.ctfEventImage", function() {
            if ($(this).attr("src") !== fallback) {
                $(this).attr("src", fallback);
            }
        });
        $logo.attr("src", requested || fallback);
    }

    function requestedCtfId() {
        try {
            return new URLSearchParams(window.location.search).get("ctf_id") || "";
        } catch (e) {
            return "";
        }
    }

    function chooseEvent(events) {
        var requested = requestedCtfId();
        var registered = (events || []).filter(function(event) {
            return event.registered === true;
        });

        if (requested) {
            for (var i = 0; i < registered.length; i++) {
                if (registered[i].ctf_id === requested) {
                    return registered[i];
                }
            }
            return null;
        }

        if (registered.length === 1) {
            return registered[0];
        }

        var active = registered.filter(function(event) {
            return event.event_state === "IN_PROGRESS";
        });

        if (active.length === 1) {
            return active[0];
        }

        return registered.length ? registered[0] : null;
    }

    function fail(message) {
        setToken("ctf_context_error", message);
        setToken("ctf_context_ready", "0");
        $("#ctf-context-error").text(message).show();
    }

    $.ajax({
        url: endpoint,
        method: "GET",
        dataType: "json",
        cache: false
    }).done(function(data) {
        var selected = chooseEvent(data.events || []);

        if (!selected) {
            fail("No registered CTF could be selected. Open CTF Registration and register for an event.");
            return;
        }

        var registration = selected.registration || {};

        setToken("ctf_id", selected.ctf_id || "");
        setToken("ctf_event_name", selected.name || selected.ctf_id || "");
        setToken("ctf_event_starts", selected.event_starts || "");
        setToken("ctf_event_ends", selected.event_ends || "");
        setToken("ctf_registration_state", selected.registration_state || "");
        setToken("ctf_event_state", selected.event_state || "");
        setToken("ctf_user", data.username || registration.Username || "");
        setToken("ctf_DisplayUsername", registration.DisplayUsername || data.username || "");
        setToken("ctf_Team", registration.Team || registration.DisplayUsername || data.username || "");
        setToken("ctf_SearchUrl", selected.search_url || "");
        setToken("ctf_image_url", selected.image_url || "");
        setEventImage(selected.image_url || "");
        setToken("ctf_context_ready", "1");
    }).fail(function(xhr) {
        fail("Unable to load your CTF registration context: " + (xhr.responseText || xhr.statusText));
    });
});
