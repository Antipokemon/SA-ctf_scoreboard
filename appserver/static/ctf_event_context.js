require([
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/simplexml/ready!"
], function($, mvc) {
    "use strict";

    var defaultTokens = mvc.Components.get("default");
    var submittedTokens = mvc.Components.get("submitted");
    var endpoint = "/en-US/splunkd/__raw/services/ctf_registration/events";
    var refreshMillis = 5000;
    var lastImageRequest = null;

    function setToken(name, value) {
        defaultTokens.set(name, value);
        if (submittedTokens) {
            submittedTokens.set(name, value);
        }
    }

    function normalizeEventImageUrl(imageUrl) {
        var requested = String(imageUrl || "").trim();
        if (!requested) {
            return "";
        }

        requested = requested.replace(/^\/static\/apps\//, "/static/app/");
        requested = requested.replace(/^static\/apps\//, "/static/app/");
        if (/^static\/app\//.test(requested)) {
            requested = "/" + requested;
        }
        return requested;
    }

    function eventImageCandidates(imageUrl) {
        var requested = normalizeEventImageUrl(imageUrl);
        var candidates = [];

        function add(value) {
            if (value && candidates.indexOf(value) === -1) {
                candidates.push(value);
            }
        }

        add(requested);

        if (requested.indexOf("/images/uploads/") !== -1) {
            add(requested.replace("/images/uploads/", "/images/"));
        }

        return candidates;
    }

    function writeEventImage(url, attempt) {
        var $logo = $("#ctflogo");
        if ($logo.length) {
            $logo.attr("src", url);
            $logo.attr("data-ctf-image", url);
            return;
        }

        if ((attempt || 0) < 12) {
            window.setTimeout(function() {
                writeEventImage(url, (attempt || 0) + 1);
            }, 100);
        }
    }

    function setEventImage(imageUrl, force) {
        var fallback = "/static/app/SA-ctf_scoreboard/ctflogo.png";
        var normalized = normalizeEventImageUrl(imageUrl);
        if (!force && lastImageRequest === normalized) {
            return;
        }
        lastImageRequest = normalized;

        var candidates = eventImageCandidates(normalized);
        var index = 0;

        function tryNext() {
            if (index >= candidates.length) {
                writeEventImage(fallback, 0);
                return;
            }

            var candidate = candidates[index++];
            var probe = new window.Image();
            probe.onload = function() {
                writeEventImage(candidate, 0);
            };
            probe.onerror = tryNext;
            probe.src = candidate;
        }

        tryNext();
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
        $(document).trigger("ctf:event-context-failed", [message]);
    }

    function applyContext(data, selected) {
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
        setEventImage(selected.image_url || "", false);
        $("#ctf-context-error").hide().text("");
        setToken("ctf_context_error", "");
        setToken("ctf_context_ready", "1");
        $(document).trigger("ctf:event-context-ready", [selected]);
    }

    function fetchContext() {
        $.ajax({
            url: endpoint,
            method: "GET",
            dataType: "json",
            cache: false,
            data: {include_completed: "1"}
        }).done(function(data) {
            var selected = chooseEvent(data.events || []);

            if (!selected) {
                fail("No registered CTF could be selected. Open CTF Registration and register for an event.");
                return;
            }

            applyContext(data, selected);
        }).fail(function(xhr) {
            fail("Unable to load your CTF registration context: " + (xhr.responseText || xhr.statusText));
        });
    }

    fetchContext();
    window.setInterval(fetchContext, refreshMillis);

    // If the dashboard body renders after the first context request, re-apply
    // the selected event image from the token rather than leaving the fallback.
    window.setTimeout(function() {
        setEventImage(defaultTokens.get("ctf_image_url") || "", true);
    }, 750);
});
