require([
    "underscore",
    "jquery",
    "splunkjs/mvc",
    "splunkjs/mvc/utils",
    "splunkjs/mvc/searchmanager",
    "splunkjs/mvc/simplexml/ready!"
], function(_, $, mvc, utils, SearchManager) {
    "use strict";

    var tokens = mvc.Components.get("default");
    var submittedTokens = mvc.Components.get("submitted");
    var envTokens = mvc.Components.get("env");
    var user = envTokens.get("user");

    var sm = null;
    var sm2 = null;
    var sm3 = null;
    var sm4 = null;
    var sm5 = null;
    var initialized = false;

    function setToken(name, value) {
        tokens.set(name, value);
        if (submittedTokens) {
            submittedTokens.set(name, value);
        }
    }

    function splEscape(value) {
        return String(value || "")
            .replace(/\\/g, "\\\\")
            .replace(/"/g, '\\"');
    }

    function contextValue(name) {
        return tokens.get(name) || "";
    }

    function refreshStealthSearch() {
        var ctfId = splEscape(contextValue("ctf_id"));
        var team = splEscape(contextValue("ctf_Team"));

        return '| makeresults'
            + ' | eval ctf_id="' + ctfId + '", Team="' + team + '"'
            + ' | lookup ctf_stealth ctf_id Team OUTPUT StealthModeTeam'
            + ' | eval StealthMode=if(isnotnull(StealthModeTeam) AND StealthModeTeam!="",'
            + '"Enabled (".StealthModeTeam.")","Disabled")'
            + ' | table StealthMode';
    }

    function enableStealthSearch() {
        var ctfId = splEscape(contextValue("ctf_id"));
        var team = splEscape(contextValue("ctf_Team"));

        return '| makeresults'
            + ' | eval ctf_id="' + ctfId + '", Team="' + team + '",'
            + ' StealthModeTeam="stealth-".upper(substr(sha1(tostring(random(),"HEX")),-6))'
            + ' | table ctf_id Team StealthModeTeam'
            + ' | inputlookup ctf_stealth append=true'
            + ' | dedup ctf_id Team'
            + ' | outputlookup ctf_stealth';
    }

    function disableStealthSearch() {
        var ctfId = splEscape(contextValue("ctf_id"));
        var team = splEscape(contextValue("ctf_Team"));

        return '| inputlookup ctf_stealth'
            + ' | where NOT (ctf_id="' + ctfId + '" AND Team="' + team + '")'
            + ' | outputlookup ctf_stealth';
    }

    function acceptUserAgreementSearch() {
        return '| inputlookup ctf_eulas'
            + ' | search EulaDefault=1'
            + ' | head 1'
            + ' | eval EulaUsername="' + splEscape(user) + '"'
            + ' | eval EulaDateAccepted=now()'
            + ' | fields EulaId EulaName EulaUsername EulaDateAccepted'
            + ' | outputlookup append=true ctf_eulas_accepted';
    }

    function refreshUserAgreementSearch() {
        return '| inputlookup ctf_eulas_accepted'
            + ' | search EulaUsername="' + splEscape(user) + '"'
            + ' | stats latest(EulaDateAccepted) as EulaDateAccepted'
            + ' | eval EulaAccepted=if(isnotnull(EulaDateAccepted),"Accepted","Not Accepted")'
            + ' | table EulaAccepted';
    }

    function initializeSearchManagers() {
        if (initialized) {
            return;
        }

        if (!contextValue("ctf_id") || !contextValue("ctf_Team")) {
            return;
        }

        initialized = true;

        sm = new SearchManager({
            id: "readStealthStatus",
            cancelOnUnload: true,
            earliest_time: "0",
            latest_time: "",
            search: refreshStealthSearch(),
            app: utils.getCurrentApp(),
            preview: false,
            autostart: true
        }, {tokens: true, tokenNamespace: "submitted"});

        sm.on("search:done", function(properties) {
            if (!properties.content || properties.content.resultCount === 0) {
                setToken("ctf_stealth_mode", "Disabled");
                return;
            }

            var results = sm.data("results", {
                output_mode: "json",
                count: 0
            });

            results.on("data", function() {
                var data = results.data().results || [];
                setToken(
                    "ctf_stealth_mode",
                    data.length && data[0].StealthMode ? data[0].StealthMode : "Disabled"
                );
            });
        });

        sm2 = new SearchManager({
            id: "writeStealthStatus",
            cancelOnUnload: true,
            earliest_time: "0",
            latest_time: "",
            search: "| makeresults | fields - _time",
            app: utils.getCurrentApp(),
            preview: false,
            autostart: false
        }, {tokens: true, tokenNamespace: "submitted"});

        sm2.on("search:done", function() {
            sm.settings.set("search", refreshStealthSearch());
            sm.startSearch();
        });

        sm3 = new SearchManager({
            id: "refreshAgreement",
            cancelOnUnload: true,
            earliest_time: "0",
            latest_time: "",
            search: refreshUserAgreementSearch(),
            app: utils.getCurrentApp(),
            preview: false,
            autostart: true
        }, {tokens: true, tokenNamespace: "submitted"});

        sm3.on("search:done", function(properties) {
            if (!properties.content || properties.content.resultCount === 0) {
                setToken("ctf_agreement_accepted", "Not Accepted");
                return;
            }

            var results = sm3.data("results", {
                output_mode: "json",
                count: 0
            });

            results.on("data", function() {
                var data = results.data().results || [];
                setToken(
                    "ctf_agreement_accepted",
                    data.length && data[0].EulaAccepted ? data[0].EulaAccepted : "Not Accepted"
                );
            });
        });

        sm4 = new SearchManager({
            id: "acceptUserAgreement",
            cancelOnUnload: true,
            earliest_time: "0",
            latest_time: "",
            search: "| makeresults | fields - _time",
            app: utils.getCurrentApp(),
            preview: false,
            autostart: false
        }, {tokens: true, tokenNamespace: "submitted"});

        sm4.on("search:done", function() {
            sm3.settings.set("search", refreshUserAgreementSearch());
            sm3.startSearch();
        });

        sm5 = new SearchManager({
            id: "retrieveUserAgreement",
            cancelOnUnload: true,
            earliest_time: "0",
            latest_time: "",
            search: "| inputlookup ctf_eulas | search EulaDefault=1 | head 1",
            app: utils.getCurrentApp(),
            preview: false,
            autostart: true
        }, {tokens: true, tokenNamespace: "submitted"});

        sm5.on("search:done", function(properties) {
            if (!properties.content || properties.content.resultCount === 0) {
                setToken("ctf_eula_content", "No user agreement is currently configured.");
                return;
            }

            var results = sm5.data("results", {
                output_mode: "json",
                count: 0
            });

            results.on("data", function() {
                var data = results.data().results || [];
                if (data.length && data[0].EulaContent) {
                    setToken("ctf_eula_content", data[0].EulaContent);
                } else {
                    setToken("ctf_eula_content", "No user agreement is currently configured.");
                }
            });
        });
    }

    function showAgreementModal() {
        $("#userAgreementModal").remove();

        var overlay = $("<div>")
            .attr("id", "userAgreementModal")
            .css({
                position: "fixed",
                top: "0",
                left: "0",
                right: "0",
                bottom: "0",
                background: "rgba(0,0,0,.70)",
                "z-index": "9999",
                display: "flex",
                "align-items": "center",
                "justify-content": "center"
            });

        var dialog = $("<div>").css({
            width: "min(760px,90vw)",
            "max-height": "80vh",
            overflow: "auto",
            background: "#1e1e1e",
            border: "1px solid rgba(255,255,255,.25)",
            "border-radius": "8px",
            padding: "20px"
        });

        $("<h2>").text("User Agreement").appendTo(dialog);

        $("<pre>")
            .css({
                "white-space": "pre-wrap",
                "word-break": "break-word",
                "max-height": "50vh",
                overflow: "auto"
            })
            .text(contextValue("ctf_eula_content") || "No user agreement is currently configured.")
            .appendTo(dialog);

        var buttons = $("<div>").css({
            display: "flex",
            gap: "10px",
            "justify-content": "flex-end",
            "margin-top": "16px"
        });

        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Cancel")
            .on("click", function() {
                overlay.remove();
            })
            .appendTo(buttons);

        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-primary")
            .text("Accept Agreement")
            .on("click", function() {
                if (!sm4) {
                    initializeSearchManagers();
                }

                if (sm4) {
                    sm4.cancel();
                    sm4.settings.set("search", acceptUserAgreementSearch());
                    sm4.startSearch();
                }

                overlay.remove();
            })
            .appendTo(buttons);

        buttons.appendTo(dialog);
        dialog.appendTo(overlay);
        overlay.appendTo("body");
    }

    $("#enable_stealth_button").on("click", function() {
        initializeSearchManagers();

        if (!sm2) {
            return;
        }

        sm2.cancel();
        sm2.settings.set("search", enableStealthSearch());
        sm2.startSearch();
    });

    $("#disable_stealth_button").on("click", function() {
        initializeSearchManagers();

        if (!sm2) {
            return;
        }

        sm2.cancel();
        sm2.settings.set("search", disableStealthSearch());
        sm2.startSearch();
    });

    $("#agreement_modal_button").on("click", function() {
        initializeSearchManagers();
        showAgreementModal();
    });

    tokens.on("change:ctf_id", initializeSearchManagers);
    tokens.on("change:ctf_Team", initializeSearchManagers);

    initializeSearchManagers();
});
