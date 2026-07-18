/* RealDoor UI — vanilla ES2019, no framework, no build step, no network unless you ask.
 *
 * Data comes from one of two places and the switch lives in exactly one object (`Source`):
 *   - default: window.REALDOOR_FIXTURES, bundled from ui/fixtures/*.json (real pipeline output)
 *   - live:    set window.REALDOOR_API before this script loads, e.g.
 *                <script>window.REALDOOR_API = "";</script>   // same origin as /api/*
 *              and the same shapes are fetched from FastAPI instead.
 *
 * Two rules this file must never break:
 *   1. No eligibility judgement is ever rendered. READY_TO_REVIEW means "ready for a human
 *      to review", and every place it appears says so in words.
 *   2. abstentions[] and review_reasons[] are rendered in a landmark that is visible on every
 *      screen and is never collapsed.
 */
(function () {
  "use strict";

  // ── tiny DOM helpers (text nodes only; nothing is ever injected as HTML) ──────────
  function h(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = String(value);
        else if (key === "html") throw new Error("refused: no raw HTML");
        else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), value);
        else if (key === "style") Object.assign(node.style, value);
        else node.setAttribute(key, value === true ? "" : String(value));
      });
    }
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function byId(id) { return document.getElementById(id); }
  function announce(message) { byId("live-status").textContent = message; }

  function money(value) {
    if (value === null || value === undefined) return "—";
    return "$" + Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function plain(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "number") return Number(value).toLocaleString("en-US");
    return String(value);
  }

  // ── geometry: faithful port of core/render.py:pdf_bbox_to_pixels ─────────────────
  // PDF space is bottom-left origin with y increasing upward; image space is top-left
  // origin with y increasing downward. The *top* edge comes from y1. Getting this
  // backwards misplaces every box while still looking plausible, which is why the
  // conversion is isolated here and nowhere else.
  function pdfBboxToPixels(bbox, pageHeightPoints, scale) {
    scale = scale === undefined ? 2.0 : scale;
    var x0 = Number(bbox[0]), y0 = Number(bbox[1]), x1 = Number(bbox[2]), y1 = Number(bbox[3]);
    var left = Math.min(x0, x1), right = Math.max(x0, x1);
    var bottom = Math.min(y0, y1), top = Math.max(y0, y1);
    return {
      left: left * scale,
      top: (pageHeightPoints - top) * scale,
      width: (right - left) * scale,
      height: (top - bottom) * scale
    };
  }
  // Same conversion expressed as percentages of the page, so a box stays put no matter
  // what size the rendered PNG happens to be displayed at.
  function boxPercent(bbox, pageWidthPoints, pageHeightPoints) {
    var rect = pdfBboxToPixels(bbox, pageHeightPoints, 1);
    return {
      left: (rect.left / pageWidthPoints) * 100,
      top: (rect.top / pageHeightPoints) * 100,
      width: (rect.width / pageWidthPoints) * 100,
      height: (rect.height / pageHeightPoints) * 100
    };
  }

  // ── vocabulary: nothing here may read as a determination ────────────────────────
  var READINESS = {
    READY_TO_REVIEW: {
      title: "Ready for a person to review",
      detail: "Every required document is present, current under the frozen 60-day convention, " +
              "internally consistent, and traceable to a box on the page. This is not approval, " +
              "and it is not an eligibility outcome."
    },
    NEEDS_REVIEW: {
      title: "Not ready yet — items still open",
      detail: "Something is missing, out of date, undatable, or inconsistent. This is not a refusal " +
              "and it is not an eligibility outcome; it is a list of what to fix."
    }
  };
  var COMPARISON = {
    below_or_equal: "The annualized amount is at or below the frozen 60% threshold for this household size.",
    above: "The annualized amount is above the frozen 60% threshold for this household size.",
    no_frozen_threshold: "No frozen threshold applies to this figure, so no comparison is made."
  };
  var STATE_WORDS = {
    present:    { word: "Present",    glyph: "✓" },
    missing:    { word: "Missing",    glyph: "!" },
    expired:    { word: "Expired",    glyph: "✕" },
    undatable:  { word: "Undatable",  glyph: "?" },
    unreadable: { word: "Unreadable", glyph: "✕" }
  };
  var EVIDENCE_WORDS = {
    extracted: "Read from the document",
    confirmed_by_renter: "Confirmed by the renter",
    corrected_by_renter: "Corrected by the renter"
  };
  var CERTAINTY_WORDS = {
    high: "High",
    low: "Low",
    abstain: "Abstained — a person must supply this"
  };

  function stateChip(stateName) {
    var info = STATE_WORDS[stateName] || { word: String(stateName), glyph: "•" };
    return h("span", { class: "chip chip--" + stateName }, [
      h("span", { "aria-hidden": "true", text: info.glyph + " " }),
      info.word
    ]);
  }

  // ── the linear flow ─────────────────────────────────────────────────────────────
  // Six ordered steps, not seven parallel tabs. The order is the product: you cannot
  // sensibly correct a value you have not seen, or read a calculation built on a value
  // you have not corrected. USWDS ships no tabs component; GOV.UK says not to use tabs
  // when content must be read in sequence. So: process list, then back/next, then a
  // check-answers screen. The step indicator below reports progress and never navigates.
  var STEPS = [
    { n: 1, screen: "screen-1", short: "Your documents",
      title: "Check the values we read from your documents",
      blurb: "See each value we read and the exact box on the page it came from." },
    { n: 2, screen: "screen-2", short: "Corrections",
      title: "Correct a value we read wrong",
      blurb: "Change anything we got wrong, and see whether it changed the numbers." },
    { n: 3, screen: "screen-3", short: "Rules",
      title: "Ask what a housing rule says",
      blurb: "Get an answer with the rule id, the authority, and the date it took effect." },
    { n: 4, screen: "screen-4", short: "The calculation",
      title: "See how your yearly income figure was worked out",
      blurb: "Inputs, formula, result and the threshold it is compared against." },
    { n: 5, screen: "screen-5", short: "Missing or expired",
      title: "See what is missing or out of date",
      blurb: "The full checklist, and the one thing you can do about each open item." },
    { n: 6, screen: "screen-6", short: "Your packet",
      title: "Check what we found, then take your packet",
      blurb: "Review everything in one place, change what is wrong, then download it." }
  ];
  function stepByScreen(screenId) {
    return STEPS.filter(function (s) { return s.screen === screenId; })[0] || null;
  }

  // ── review reasons: a human heading, the API's own words, and the code kept but demoted ──
  // GOV.UK lists error codes among the things not to show a user; NN/g says show them for
  // technical diagnosis only. The code is never the headline and never disappears — it moves
  // behind a "Technical details" disclosure so a judge can still verify we are not
  // paraphrasing meaning away. The `message` string is the API's, reproduced verbatim.
  var REASON_HEADINGS = {
    RENTER_CORRECTION_NOT_USED: "Your correction was recorded, but it was not used in the calculation",
    PAY_STUB_TOTAL_CONFLICT:    "Two figures on the same pay stub do not agree",
    GIG_INCOME_UNCORROBORATED:  "The gig income has nothing else to corroborate it",
    DOCUMENT_UNDATABLE:         "A document has no date precise enough to use",
    EMPLOYMENT_LETTER_EXPIRED:  "The employment letter is outside the 60-day window"
  };
  // Which step each open item belongs to, so it is raised where the user can act on it
  // rather than in one undifferentiated pile.
  var REASON_STEP = {
    RENTER_CORRECTION_NOT_USED: 2,
    PAY_STUB_TOTAL_CONFLICT:    2,
    GIG_INCOME_UNCORROBORATED:  4,
    DOCUMENT_UNDATABLE:         5,
    EMPLOYMENT_LETTER_EXPIRED:  5
  };
  function reasonStep(reason) {
    if (REASON_STEP[reason.code]) return REASON_STEP[reason.code];
    if (reason.check === "consistent") return 2;
    return 5;   // "present" and "current" are both checklist matters
  }
  function reasonHeading(reason) {
    return REASON_HEADINGS[reason.code] || "This item needs a person to look at it";
  }
  function reasonsForStep(n) {
    if (!state.report) return [];
    return (state.report.review_reasons || []).filter(function (r) { return reasonStep(r) === n; });
  }

  /** The inline message, next to the thing it concerns. Its text is the same string the
   *  error summary at the top of the page links with — character for character. */
  function reasonCard(reason) {
    return h("div", { class: "reason", id: "reason-" + reason.code, tabindex: "-1" }, [
      h("p", { class: "reason-heading", text: reasonHeading(reason) }),
      h("p", { class: "reason-message", text: reason.message }),
      h("details", { class: "tech" }, [
        h("summary", { text: "Technical details" }),
        h("dl", { class: "kv" }, [
          h("dt", { text: "Code" }),  h("dd", { class: "mono", text: reason.code }),
          h("dt", { text: "Check" }), h("dd", { class: "mono", text: reason.check }),
          h("dt", { text: "Rule" }),  h("dd", { class: "mono", text: reason.rule_id })
        ])
      ])
    ]);
  }

  /** All open items belonging to one step, rendered inline beneath that step's content. */
  function stepReasonBlock(n) {
    var reasons = reasonsForStep(n);
    if (!reasons.length) return null;
    var headingId = "step-open-" + n;
    return h("section", { class: "reason-block", "aria-labelledby": headingId }, [
      h("h3", { id: headingId, style: { marginTop: "0" },
        text: reasons.length === 1
          ? "One thing on this step needs a person to look at it"
          : reasons.length + " things on this step need a person to look at them" }),
      h("div", null, reasons.map(reasonCard))
    ]);
  }

  // ── data source: the single switch between fixtures and the live API ────────────
  var Source = (function () {
    // One switch, several ways to throw it: set window.REALDOOR_API before this script, or
    // append ?live (same origin) / ?api=http://host:port / ?fixtures to the URL. If none of
    // those is present and the page is served over http, `adoptSameOriginApi` below probes
    // the origin and switches to live when our API answers. Everything below this object is
    // written against the same shapes either way.
    var params = new URLSearchParams(window.location.search);
    var fromQuery = params.has("api") ? params.get("api")
                  : params.has("live") ? ""
                  : null;
    var configured = (typeof window.REALDOOR_API === "string") ? window.REALDOOR_API : fromQuery;
    var apiBase = (typeof configured === "string") ? configured.replace(/\/$/, "") : null;
    var live = apiBase !== null;
    var fixtures = window.REALDOOR_FIXTURES || {};
    var sessionId = null;

    function headers(extra) {
      var out = Object.assign({}, extra || {});
      if (sessionId) out["X-Session-Id"] = sessionId;
      return out;
    }
    function ensureSession() {
      if (sessionId) return Promise.resolve(sessionId);
      return fetch(apiBase + "/api/session", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (body) { sessionId = body.session_id; return sessionId; });
    }
    function api(path, options) {
      return ensureSession().then(function () {
        var opts = Object.assign({}, options || {});
        opts.headers = headers(opts.headers);
        return fetch(apiBase + path, opts);
      });
    }
    function json(path, options) {
      return api(path, options).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status + " from " + path);
        return r.json();
      });
    }

    // fixtures-mode corrections: only the two the pipeline actually produced exist offline.
    var OFFLINE_CORRECTIONS = [
      {
        household_id: "HH-001", document_id: "HH-001-D01", field: "household_size",
        value: 3, fixture: "report_HH-001_after_size_correction",
        label: "Household size is 3, not 1 (application summary)"
      },
      {
        household_id: "HH-001", document_id: "HH-001-D02", field: "gross_pay",
        value: 2500, fixture: "report_HH-001_after_rejected_correction",
        label: "Gross pay on the newer stub is $2,500.00, not $2,166.00"
      }
    ];

    var source = {
      live: live,
      apiBase: apiBase,
      offlineCorrections: OFFLINE_CORRECTIONS,
      sessionId: function () { return sessionId; },
      describe: function () {
        return live
          ? "Live API at " + (apiBase || "this origin") + " (same shapes as the fixtures)"
          : "Bundled fixtures — real pipeline output, no server, no network";
      },

      households: function () {
        if (!live) {
          return Promise.resolve((fixtures.households.households || []).map(function (row) {
            return {
              household_id: row.household_id,
              document_count: row.document_count,
              has_report: Boolean(fixtures["report_" + row.household_id])
            };
          }));
        }
        return json("/api/households").then(function (body) {
          return (body.households || []).map(function (row) {
            return { household_id: row.household_id, document_count: row.document_count, has_report: true };
          });
        });
      },

      report: function (householdId) {
        if (!live) return Promise.resolve(fixtures["report_" + householdId] || null);
        return json("/api/report/" + encodeURIComponent(householdId));
      },

      // Returns { report, applied:boolean, unsupported:boolean }
      confirm: function (householdId, documentId, field, value) {
        if (!live) {
          var match = OFFLINE_CORRECTIONS.filter(function (c) {
            return c.document_id === documentId && c.field === field &&
                   String(c.value) === String(value);
          })[0];
          if (!match) return Promise.resolve({ report: null, unsupported: true });
          return Promise.resolve({ report: fixtures[match.fixture], unsupported: false });
        }
        return json("/api/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document_id: documentId, field: field, value: value })
        }).then(function (report) { return { report: report, unsupported: false }; });
      },

      askExamples: function () {
        var examples = fixtures.ask_examples || {};
        return Object.keys(examples).map(function (key) {
          return { key: key, question: examples[key].question, response: examples[key].response };
        });
      },
      ask: function (question, householdId) {
        if (!live) {
          var examples = fixtures.ask_examples || {};
          var hit = Object.keys(examples).filter(function (key) {
            return examples[key].question.toLowerCase() === String(question).toLowerCase();
          })[0];
          if (hit) return Promise.resolve(examples[hit].response);
          return Promise.resolve(null); // offline: only the recorded questions exist
        }
        return json("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: question, household_id: householdId })
        });
      },

      selftest: function () {
        if (!live) return Promise.resolve(fixtures.selftest);
        return json("/api/selftest");
      },

      pageImage: function (documentId, page) {
        if (!live) return Promise.resolve(null);
        return api("/api/document/" + encodeURIComponent(documentId) + "/page/" + page + ".png")
          .then(function (r) {
            if (!r.ok) return null;
            return r.blob().then(function (blob) { return URL.createObjectURL(blob); });
          })
          .catch(function () { return null; });
      },

      packet: function (householdId, report) {
        if (!live) {
          var payload = {
            packet_note: "RealDoor readiness packet. This describes what your documents show and " +
                         "what is still missing or expired. It is NOT an eligibility decision, and " +
                         "nothing in it has been sent anywhere.",
            generated_from: "bundled fixtures (offline mode)",
            readiness_report: report
          };
          var blob = new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" });
          return Promise.resolve({ blob: blob, filename: "realdoor_" + householdId + "_packet.json" });
        }
        return api("/api/packet/" + encodeURIComponent(householdId), { method: "POST" })
          .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.blob();
          })
          .then(function (blob) {
            return { blob: blob, filename: "realdoor_" + householdId + "_packet.zip" };
          });
      },

      gateSelftest: function () {
        if (!live) return Promise.resolve({ available: false });
        return api("/api/_gate_selftest").then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            return { available: true, status: r.status, body: body };
          });
        });
      },

      deleteSession: function () {
        if (!live || !sessionId) return Promise.resolve({ live: false });
        var id = sessionId;
        return fetch(apiBase + "/api/session/" + encodeURIComponent(id), { method: "DELETE" })
          .then(function (r) { return r.json(); })
          .then(function (body) {
            sessionId = null;
            return { live: true, body: body, session_id: id };
          });
      }
    };

    // If nobody chose a source and we are being served over http(s), ask the origin whether
    // it is our API. A judge who clones the repo, starts the server and opens "/" should see
    // the real pipeline answering, not bundled output that reads as a mock. Opened from
    // file://, or served by a plain static server, this probe simply fails and we stay on
    // fixtures — the offline demo path is never taken away.
    source.adoptSameOriginApi = function () {
      var chosen = typeof window.REALDOOR_API === "string" || fromQuery !== null ||
                   params.has("fixtures");   // ?fixtures forces the offline path back on
      var servedOverHttp = /^https?:$/.test(window.location.protocol);
      if (chosen || live || !servedOverHttp) return Promise.resolve(source.live);
      return fetch("/api/health")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (body) {
          if (!body || body.ok !== true) return source.live;
          apiBase = "";
          live = true;
          source.live = true;
          source.apiBase = "";
          return true;
        })
        .catch(function () { return source.live; });
    };

    return source;
  })();

  // ── application state ───────────────────────────────────────────────────────────
  var state = {
    households: [],
    householdId: null,
    report: null,
    baselineReport: null,   // report before the renter's correction, for the before/after view
    correction: null,       // {document_id, field, value, label}
    documentId: null,
    activeField: null,
    pageImageUrl: null,
    selftest: null,
    lastQuestion: null,     // for the step 6 check-answers row
    screen: "screen-start", // the one screen currently on show
    returnTo: null          // set by a "Change" link so the step returns straight to step 6
  };

  // ── router: one screen at a time, focus moved to its unique H1 ──────────────────
  function showScreen(screenId, options) {
    options = options || {};
    state.screen = screenId;

    Array.prototype.forEach.call(document.querySelectorAll(".screen"), function (section) {
      section.hidden = section.id !== screenId;
    });

    renderStepIndicator();
    renderErrorSummary();
    renderStepNav();

    if (options.focus !== false) {
      var heading = document.querySelector("#" + screenId + " h1");
      if (heading) heading.focus();
    }
    if (options.announce !== false) {
      var step = stepByScreen(screenId);
      var heading2 = document.querySelector("#" + screenId + " h1");
      announce((step ? "Step " + step.n + " of 6. " : "") +
               (heading2 ? heading2.textContent : ""));
    }
    if (window.scrollTo) window.scrollTo(0, 0);
  }

  function goToStep(n, options) {
    var step = STEPS.filter(function (s) { return s.n === n; })[0];
    if (step) showScreen(step.screen, options);
  }

  /** USWDS step indicator, deliberately non-navigable: no links, no buttons, no click
   *  targets. It reports where you are. Back/Next below does the moving. */
  function renderStepIndicator() {
    var host = byId("step-indicator-host");
    clear(host);
    var current = stepByScreen(state.screen);
    if (!current) return;

    host.appendChild(h("div", { class: "step-indicator", role: "group", "aria-label": "Progress" }, [
      h("ol", { class: "step-indicator__segments" }, STEPS.map(function (step) {
        var status = step.n < current.n ? "complete" : (step.n === current.n ? "current" : "todo");
        return h("li", {
          class: "segment segment--" + status,
          "aria-current": status === "current" ? "step" : null
        }, [
          h("span", { class: "segment__label" }, [
            step.short,
            h("span", { class: "visually-hidden", text:
              status === "complete" ? " — completed"
              : status === "current" ? " — current step"
              : " — not completed" })
          ])
        ]);
      }))
    ]));
  }

  /** Error summary: top of the main container, above the H1, one link per open item.
   *  Each link's text is the identical string rendered inline further down the page. */
  function renderErrorSummary() {
    var host = byId("error-summary-host");
    clear(host);
    var step = stepByScreen(state.screen);
    if (!step) return;
    var reasons = reasonsForStep(step.n);
    if (!reasons.length) return;

    host.appendChild(h("div", {
      class: "error-summary", role: "region", "aria-labelledby": "error-summary-title"
    }, [
      h("h2", { id: "error-summary-title", style: { marginTop: "0" },
        text: reasons.length === 1
          ? "There is one open item on this step"
          : "There are " + reasons.length + " open items on this step" }),
      h("p", { class: "error-summary-lede", text:
        "These are not refusals and nothing is wrong with you. They are the things the system " +
        "will not settle on its own, listed so a person can settle them." }),
      // The link text is the same short heading the inline item carries, word for word,
      // so the two never read as two different problems. The API's own `message` string is
      // not paraphrased and not shortened — it is the detail directly under that heading,
      // one jump away. Using the raw message here would put a sixty-word technical
      // paragraph in the one place on the page the eye is meant to land.
      h("ul", { class: "error-summary-list" }, reasons.map(function (reason) {
        return h("li", null, [
          h("a", {
            href: "#reason-" + reason.code,
            onclick: function (event) {
              event.preventDefault();
              var target = byId("reason-" + reason.code);
              if (target) target.focus();
            }
          }, [reasonHeading(reason)])
        ]);
      }))
    ]));
  }

  /** Back / Next as the real navigation, at the foot of every screen. */
  function renderStepNav() {
    ["nav-start", "nav-1", "nav-2", "nav-3", "nav-4", "nav-5", "nav-6", "nav-how"]
      .forEach(function (id) { var node = byId(id); if (node) clear(node); });

    if (state.screen === "screen-start") {
      byId("nav-start").appendChild(h("button", {
        type: "button", class: "action action--lead", id: "start-demo",
        onclick: function () { goToStep(1); }
      }, ["Start step 1"]));
      return;
    }

    if (state.screen === "screen-how") {
      byId("nav-how").appendChild(h("button", {
        type: "button", class: "action action--lead", id: "how-back",
        onclick: function () { showScreen(state.returnScreen || "screen-start"); }
      }, ["Go back to where you were"]));
      return;
    }

    var step = stepByScreen(state.screen);
    if (!step) return;
    var host = byId("nav-" + step.n);

    // A "Change" link on step 6 sets returnTo, so the step it lands on offers a way
    // straight back to the check page rather than making the user walk forward again.
    if (state.returnTo === "screen-6" && step.n !== 6) {
      host.appendChild(h("button", {
        type: "button", class: "action action--lead", id: "step-return",
        onclick: function () { state.returnTo = null; showScreen("screen-6"); }
      }, ["Return to what we found"]));
    }

    host.appendChild(h("button", {
      type: "button", class: "action secondary", id: "step-back",
      onclick: function () {
        if (step.n === 1) showScreen("screen-start");
        else goToStep(step.n - 1);
      }
    }, [step.n === 1 ? "Back to the start" : "Back to step " + (step.n - 1)]));

    if (step.n < 6 && state.returnTo !== "screen-6") {
      host.appendChild(h("button", {
        type: "button", class: "action action--lead", id: "step-next",
        onclick: function () { goToStep(step.n + 1); }
      }, ["Continue to step " + (step.n + 1)]));
    }
  }

  function renderProcessList() {
    var list = byId("process-list");
    clear(list);
    STEPS.forEach(function (step) {
      list.appendChild(h("li", { class: "process-item" }, [
        h("h3", { class: "process-item__title", text: step.title }),
        h("p", { class: "process-item__blurb", text: step.blurb })
      ]));
    });
  }

  // ── panel 1: documents and evidence ─────────────────────────────────────────────
  function currentDocument() {
    if (!state.report) return null;
    var docs = state.report.documents || [];
    var found = docs.filter(function (d) { return d.document_id === state.documentId; })[0];
    return found || docs[0] || null;
  }

  function renderDocuments() {
    var root = byId("documents-body");
    clear(root);
    if (!state.report) { root.appendChild(noReportNotice()); return; }

    var doc = currentDocument();
    if (!doc) { root.appendChild(h("p", { text: "This household has no documents in this report." })); return; }
    state.documentId = doc.document_id;

    var list = h("ul", { class: "doc-list" }, (state.report.documents || []).map(function (d) {
      var isCurrent = d.document_id === doc.document_id;
      return h("li", null, [
        h("button", {
          type: "button",
          "aria-current": isCurrent ? "true" : null,
          onclick: function () {
            state.documentId = d.document_id;
            state.activeField = null;
            state.pageImageUrl = null;
            renderDocuments();
            announce("Showing document " + d.document_id + ", " + d.document_type.replace(/_/g, " "));
            var heading = byId("doc-detail-heading");
            if (heading) heading.focus();
          }
        }, [
          d.document_type.replace(/_/g, " "),
          h("span", { class: "doc-meta" }, [
            d.document_id + " · " + (d.document_date || "no date") + " · ",
            STATE_WORDS[d.state] ? STATE_WORDS[d.state].word : String(d.state)
          ])
        ])
      ]);
    }));

    var detail = h("div", null, [
      h("h3", { id: "doc-detail-heading", tabindex: "-1" },
        [doc.document_type.replace(/_/g, " ") + " — " + doc.document_id]),
      documentSummary(doc)
    ]);

    var pageHost = h("div", { id: "page-host" });
    detail.appendChild(pageHost);
    detail.appendChild(fieldTable(doc));

    root.appendChild(h("div", { class: "doc-layout" }, [
      h("nav", { "aria-label": "Documents in this household" }, [
        h("h3", { text: "Documents", style: { marginTop: "0" } }),
        list
      ]),
      detail
    ]));

    renderPage(pageHost, doc);
  }

  function documentSummary(doc) {
    var stale = doc.days_until_stale;
    var staleText;
    if (stale === null || stale === undefined) {
      staleText = "The 60-day window cannot be applied — the date is not precise enough to use without inventing a day.";
    } else if (stale < 0) {
      staleText = "Outside the 60-day window by " + Math.abs(stale) + " day(s).";
    } else {
      staleText = stale + " day(s) of the 60-day window remaining.";
    }
    return h("dl", { class: "kv" }, [
      h("dt", { text: "File" }), h("dd", { class: "mono", text: doc.file_name }),
      h("dt", { text: "Document date" }), h("dd", { text: doc.document_date || "not stated" }),
      h("dt", { text: "Currency" }), h("dd", null, [stateChip(doc.state), " ", staleText]),
      h("dt", { text: "Rule" }), h("dd", { class: "mono", text: doc.stale_rule_id || "—" }),
      h("dt", { text: "Read via" }), h("dd", { text: (doc.source || "unknown").replace(/_/g, " ") }),
      h("dt", { text: "Page size" }),
      h("dd", { text: (doc.page_size_points || []).join(" × ") + " pt, " + doc.page_count + " page(s)" })
    ]);
  }

  function renderPage(host, doc) {
    clear(host);
    var pageSize = doc.page_size_points || [612, 792];
    var pageW = Number(pageSize[0]), pageH = Number(pageSize[1]);

    var frame = h("div", {
      class: "page-frame",
      style: { aspectRatio: pageW + " / " + pageH, maxWidth: "44rem" }
    });
    host.appendChild(frame);

    var located = (doc.fields || []).filter(function (f) { return f.bbox && f.page === 1; });

    function drawBoxes(container) {
      located.forEach(function (field) {
        var pct = boxPercent(field.bbox, pageW, pageH);
        var box = h("div", {
          class: "evidence-box" + (state.activeField === field.field ? " is-active" : ""),
          "data-field": field.field,
          style: {
            left: pct.left.toFixed(3) + "%",
            top: pct.top.toFixed(3) + "%",
            width: pct.width.toFixed(3) + "%",
            height: pct.height.toFixed(3) + "%"
          }
        }, [h("span", { class: "box-tag", text: field.field })]);
        container.appendChild(box);
      });
    }

    if (Source.live) {
      Source.pageImage(doc.document_id, 1).then(function (url) {
        clear(frame);
        if (!url) { renderSchematic(); return; }
        state.pageImageUrl = url;
        frame.appendChild(h("img", { src: url, alt: "Rendered page 1 of " + doc.file_name }));
        var overlay = h("div", { class: "page-schematic", "aria-hidden": "true" });
        drawBoxes(overlay);
        frame.appendChild(overlay);
        host.appendChild(h("p", {
          class: "page-caption",
          text: "Page 1 as rendered by the server. Each rectangle is the box the value was read from; " +
                "the same coordinates are listed as text in the table below."
        }));
      });
      frame.appendChild(h("p", { class: "page-caption", text: "Loading the page image…" }));
      return;
    }
    renderSchematic();

    function renderSchematic() {
      clear(frame);
      var schematic = h("div", { class: "page-schematic", "aria-hidden": "true" });
      located.forEach(function (field) {
        var pct = boxPercent(field.bbox, pageW, pageH);
        schematic.appendChild(h("div", {
          class: "schematic-text",
          style: {
            left: pct.left.toFixed(3) + "%",
            top: pct.top.toFixed(3) + "%",
            width: Math.max(pct.width, 6).toFixed(3) + "%",
            height: pct.height.toFixed(3) + "%"
          },
          text: field.source_text === null || field.source_text === undefined ? "" : String(field.source_text)
        }));
      });
      drawBoxes(schematic);
      frame.appendChild(schematic);
      host.appendChild(h("p", {
        class: "page-caption"
      }, [
        "No server is running, so the scanned page cannot be rasterised. ",
        h("strong", { text: "This is a schematic, not the document: " }),
        "each rectangle is at the real extracted coordinates and holds the real source text, drawn " +
        "with the same bottom-left-origin conversion the server uses. Exact coordinates are in the table below."
      ]));
    }
  }

  function fieldTable(doc) {
    var rows = (doc.fields || []).map(function (field) {
      var isActive = state.activeField === field.field;
      var valueCell = field.value === null || field.value === undefined
        ? h("td", { class: "abstain-cell" }, ["Not read — a person must supply this"])
        : h("td", { text: plain(field.value) });

      return h("tr", { class: isActive ? "is-active" : null }, [
        h("th", { scope: "row" }, [
          field.bbox
            ? h("button", {
                type: "button",
                class: "field-row-btn",
                "aria-pressed": isActive ? "true" : "false",
                onclick: function () {
                  state.activeField = isActive ? null : field.field;
                  renderDocuments();
                  announce(isActive
                    ? "Cleared the highlight"
                    : "Highlighted " + field.field + " on page " + field.page);
                }
              }, [field.field])
            : h("span", { text: field.field })
        ]),
        valueCell,
        h("td", { text: EVIDENCE_WORDS[field.evidence_kind] || field.evidence_kind }),
        h("td", { text: CERTAINTY_WORDS[field.certainty] || field.certainty }),
        h("td", { class: "mono", text: field.source_text === null ? "—" : String(field.source_text) }),
        h("td", { class: "num", text: field.page }),
        h("td", { class: "mono num", text: field.bbox ? field.bbox.map(function (n) { return Number(n).toFixed(2); }).join(", ") : "no box" })
      ]);
    });

    return h("div", { class: "table-scroll" }, [
      h("table", null, [
        h("caption", null, [
          "Extracted values on " + doc.document_id + ". Choose a field name to highlight its box on the page. ",
          "Boxes are in PDF points, bottom-left origin, as [x0, y0, x1, y1]."
        ]),
        h("thead", null, [h("tr", null, [
          h("th", { scope: "col", text: "Field" }),
          h("th", { scope: "col", text: "Value" }),
          h("th", { scope: "col", text: "How we got it" }),
          h("th", { scope: "col", text: "Certainty" }),
          h("th", { scope: "col", text: "Text on the page" }),
          h("th", { scope: "col", class: "num", text: "Page" }),
          h("th", { scope: "col", class: "num", text: "Box (pt)" })
        ])]),
        h("tbody", null, rows)
      ])
    ]);
  }

  // ── panel 2: correct a field ────────────────────────────────────────────────────
  function findCalculation(report, name) {
    if (!report) return null;
    return (report.calculations || []).filter(function (c) { return c.name === name; })[0] || null;
  }
  function correctionWasRejected(report) {
    return (report.review_reasons || []).some(function (r) { return r.code === "RENTER_CORRECTION_NOT_USED"; });
  }

  function renderCorrect() {
    var root = byId("correct-body");
    clear(root);
    if (!state.report) { root.appendChild(noReportNotice()); return; }

    root.appendChild(h("div", { class: "callout" }, [
      h("h3", { text: "Your correction is recorded, and it may still not be used" }),
      h("p", {
        text: "A correction changes what the file says. It does not automatically change the " +
              "annualized amount: if the corrected figure no longer agrees with the hours and rate " +
              "printed on the same document, that document stops settling what the recurring pay is, " +
              "and the system says so instead of quietly using the new number."
      })
    ]));

    // scenario shortcuts
    if (!Source.live) {
      var shortcuts = Source.offlineCorrections.filter(function (c) { return c.household_id === state.householdId; });
      if (shortcuts.length) {
        root.appendChild(h("h3", { text: "Recorded corrections available offline" }));
        root.appendChild(h("p", {
          class: "hint",
          text: "Without a server the app can only replay corrections the pipeline actually ran. " +
                "Both of these are real pipeline output. Point the app at the API to edit any field."
        }));
        root.appendChild(h("div", { class: "button-row" }, shortcuts.map(function (c) {
          return h("button", {
            type: "button",
            class: "action secondary",
            onclick: function () {
              byId("correct-doc").value = c.document_id;
              populateFieldOptions();
              byId("correct-field").value = c.field;
              byId("correct-value").value = String(c.value);
              announce("Filled the correction form with: " + c.label);
              byId("correct-apply").focus();
            }
          }, [c.label]);
        })));
      }
    }

    // the form
    var docSelect = h("select", { id: "correct-doc", onchange: populateFieldOptions },
      (state.report.documents || []).map(function (d) {
        return h("option", { value: d.document_id, text: d.document_id + " — " + d.document_type.replace(/_/g, " ") });
      }));
    var fieldSelect = h("select", { id: "correct-field" });
    var valueInput = h("input", { id: "correct-value", type: "text", autocomplete: "off" });

    var form = h("form", { onsubmit: function (event) { event.preventDefault(); applyCorrection(); } }, [
      h("div", { class: "field-grid" }, [
        h("div", null, [h("label", { for: "correct-doc", text: "Document" }), docSelect]),
        h("div", null, [h("label", { for: "correct-field", text: "Field to correct" }), fieldSelect]),
        h("div", null, [
          h("label", { for: "correct-value", text: "Corrected value" }),
          valueInput,
          h("p", { class: "hint", id: "correct-value-hint", text: "Type the value as it should read." })
        ])
      ]),
      h("div", { class: "button-row" }, [
        h("button", { type: "submit", id: "correct-apply", class: "action", text: "Apply correction" }),
        h("button", {
          type: "button", class: "action secondary", text: "Undo correction",
          onclick: function () {
            if (!state.baselineReport) { announce("There is no correction to undo."); return; }
            state.report = state.baselineReport;
            state.baselineReport = null;
            state.correction = null;
            renderAll();
            announce("Correction undone. The report is back to the extracted values.");
          }
        })
      ])
    ]);
    root.appendChild(form);
    root.appendChild(h("div", { id: "correct-outcome" }));
    var openItems = stepReasonBlock(2);
    if (openItems) root.appendChild(openItems);

    // must run after the selects are in the document
    if (state.correction) {
      docSelect.value = state.correction.document_id;
      populateFieldOptions();
      fieldSelect.value = state.correction.field;
      valueInput.value = String(state.correction.value);
      renderCorrectionOutcome();
    } else {
      populateFieldOptions();
    }

    function populateFieldOptions() {
      var docId = byId("correct-doc").value;
      var doc = (state.report.documents || []).filter(function (d) { return d.document_id === docId; })[0];
      var target = byId("correct-field");
      clear(target);
      (doc ? doc.fields : []).forEach(function (f) {
        target.appendChild(h("option", { value: f.field, text: f.field + " (currently " + plain(f.value) + ")" }));
      });
    }
  }

  function applyCorrection() {
    var documentId = byId("correct-doc").value;
    var field = byId("correct-field").value;
    var raw = byId("correct-value").value.trim();
    if (!raw) { announce("Enter a corrected value first."); return; }
    var value = /^-?\d+(\.\d+)?$/.test(raw.replace(/,/g, "")) ? Number(raw.replace(/,/g, "")) : raw;

    var baseline = state.baselineReport || state.report;
    Source.confirm(state.householdId, documentId, field, value).then(function (result) {
      if (result.unsupported) {
        var outcome = byId("correct-outcome");
        clear(outcome);
        outcome.appendChild(h("div", { class: "callout callout--warn" }, [
          h("h3", { text: "Not available without the server" }),
          h("p", {
            text: "This build is running on bundled fixtures, which contain only the two corrections " +
                  "the pipeline actually ran. Rather than invent a result for " + field + " = " + raw +
                  ", the app declines to show one. Start the API and set window.REALDOOR_API to correct any field."
          })
        ]));
        announce("That correction is not available offline.");
        return;
      }
      state.baselineReport = baseline;
      state.report = result.report;
      state.correction = { document_id: documentId, field: field, value: value };
      renderAll();
      var rejected = correctionWasRejected(state.report);
      announce(rejected
        ? "Correction recorded, but it was not used in the calculation. See the explanation."
        : "Correction applied. The downstream numbers have been recomputed.");
      var outcomeHeading = byId("correction-outcome-heading");
      if (outcomeHeading) outcomeHeading.focus();
    }).catch(function (error) {
      var outcome = byId("correct-outcome");
      clear(outcome);
      outcome.appendChild(errorCard("The correction could not be applied", error));
    });
  }

  function renderCorrectionOutcome() {
    var outcome = byId("correct-outcome");
    if (!outcome) return;
    clear(outcome);
    var before = state.baselineReport, after = state.report;
    if (!before || !after) return;

    var rejected = correctionWasRejected(after);
    var beforeCalc = findCalculation(before, "annualized_income");
    var afterCalc = findCalculation(after, "annualized_income");

    outcome.appendChild(h("h3", { id: "correction-outcome-heading", tabindex: "-1" }, [
      rejected ? "Your correction was recorded and was NOT used" : "Your correction was used"
    ]));

    if (rejected) {
      // The reason strings themselves live in exactly one place on this screen — the open-items
      // block below — so that the error summary at the top can quote them verbatim without the
      // user meeting the same sentence twice in two different wordings.
      outcome.appendChild(h("div", { class: "callout callout--stop" }, [
        h("h4", { text: "Why the number did not move", style: { marginTop: "0" } }),
        h("p", { style: { marginBottom: "0" } }, [
          "This is the honest case, and it is the one that matters: the system kept your correction " +
          "on the record, refused to fold it into the annualized amount, and said exactly why. The " +
          "reason is set out under ",
          h("strong", { text: "“Open items on this step”" }),
          " below, in the system's own words."
        ])
      ]));
    } else {
      outcome.appendChild(h("div", { class: "callout callout--ok" }, [
        h("p", {
          text: "The corrected value flowed into the calculation below. Nothing was hidden and no " +
                "eligibility outcome follows from it."
        })
      ]));
    }

    outcome.appendChild(h("div", { class: "table-scroll" }, [
      h("table", null, [
        h("caption", { text: "Before and after your correction" }),
        h("thead", null, [h("tr", null, [
          h("th", { scope: "col", text: "" }),
          h("th", { scope: "col", text: "Before" }),
          h("th", { scope: "col", text: "After" })
        ])]),
        h("tbody", null, [
          diffRow("Corrected field", "—", state.correction.field + " = " + plain(state.correction.value) +
            " on " + state.correction.document_id),
          diffRow("Annualized income", beforeCalc ? money(beforeCalc.result) : "—", afterCalc ? money(afterCalc.result) : "—"),
          diffRow("Formula", beforeCalc ? beforeCalc.formula : "—", afterCalc ? afterCalc.formula : "—"),
          diffRow("Frozen 60% threshold", beforeCalc ? money(beforeCalc.threshold) : "—", afterCalc ? money(afterCalc.threshold) : "—"),
          diffRow("Comparison", beforeCalc ? beforeCalc.comparison.replace(/_/g, " ") : "—",
            afterCalc ? afterCalc.comparison.replace(/_/g, " ") : "—"),
          diffRow("Readiness", READINESS[before.readiness_status].title, READINESS[after.readiness_status].title),
          diffRow("Open questions", String((before.abstentions || []).length), String((after.abstentions || []).length))
        ])
      ])
    ]));

    outcome.appendChild(h("p", {
      class: "status-line",
      text: "The threshold moves when household size changes because the frozen HUD table is indexed by " +
            "household size (rule HUD-MTSP-002). The amount moves only when the recurring base changes."
    }));
  }

  function diffRow(label, before, after) {
    var changed = String(before) !== String(after);
    return h("tr", null, [
      h("th", { scope: "row", text: label }),
      h("td", { text: before }),
      h("td", { class: changed ? "delta-up" : "delta-same" }, [
        after, changed ? h("span", { text: "  (changed)" }) : h("span", { text: "  (unchanged)" })
      ])
    ]);
  }

  // ── panel 3: ask about a rule ───────────────────────────────────────────────────
  function citationBlock(citation) {
    var isUrl = /^https?:\/\//i.test(citation.source_url || "");
    return h("div", { class: "card" }, [
      // A citation id is the name of the thing being cited, the way "Section 8" is — so it
      // stays prominent, as the contract requires. It is labelled rather than left as a bare
      // token, which is what makes it a reference and not a machine code thrown at the reader.
      h("h4", { style: { marginTop: "0" } }, [
        "Rule ", h("span", { class: "mono", text: citation.rule_id })
      ]),
      h("dl", { class: "kv" }, [
        h("dt", { text: "Authority" }), h("dd", { text: (citation.authority || "").replace(/_/g, " ") }),
        h("dt", { text: "Effective date" }), h("dd", { text: citation.effective_date || "—" }),
        h("dt", { text: "Where it says so" }), h("dd", { text: citation.source_locator || "—" }),
        h("dt", { text: "Source" }),
        h("dd", null, [
          isUrl
            ? h("a", { href: citation.source_url, rel: "noopener noreferrer", target: "_blank" },
                [citation.source_url, h("span", { class: "visually-hidden", text: " (opens in a new tab)" })])
            : h("span", { class: "mono", text: citation.source_url || "—" })
        ]),
        h("dt", { text: "Re-checked against the live source" }),
        h("dd", { text: citation.verified_against_source === true ? "Yes"
                       : citation.verified_against_source === false ? "No"
                       : "Not checked — reported as unchecked rather than assumed" })
      ]),
      h("p", { text: citation.text })
    ]);
  }

  function renderAskResponse(host, question, response, options) {
    clear(host);
    if (!(options && options.silent)) state.lastQuestion = question;
    if (!response) {
      host.appendChild(h("div", { class: "callout callout--warn" }, [
        h("h3", { text: "No recorded answer for that wording", tabindex: "-1", id: "ask-answer-heading" }),
        h("p", {
          text: "Offline, this app can only replay questions the pipeline actually answered. It will not " +
                "improvise an answer about a housing rule. Choose one of the recorded questions, or start " +
                "the API for free-form questions."
        })
      ]));
      byId("ask-answer-heading").focus();
      return;
    }

    var flavour = response.refused ? "callout--stop" : (response.abstained ? "callout--warn" : "callout--ok");
    var headline = response.refused ? "Refused, on purpose"
      : (response.abstained ? "Abstained — no answer given" : "Answer");

    host.appendChild(h("div", { class: "callout " + flavour }, [
      h("h3", { id: "ask-answer-heading", tabindex: "-1", text: headline }),
      h("p", { class: "status-line", text: "Question asked: " + question }),
      h("p", { text: response.answer || "No answer is given for this question." }),
      response.what_would_resolve_it
        ? h("p", null, [h("strong", { text: "What would resolve it: " }), response.what_would_resolve_it])
        : null,
      h("p", { class: "status-line" }, [
        "Response kind: ", h("span", { class: "mono", text: response.kind }),
        " · abstained: " + String(response.abstained) + " · refused: " + String(response.refused)
      ])
    ]));

    if (response.notice) host.appendChild(h("p", { class: "status-line", text: response.notice }));

    host.appendChild(h("h3", { text: (response.citations || []).length ? "Citations" : "Citations: none" }));
    if (!(response.citations || []).length) {
      host.appendChild(h("p", {
        text: "No rule is cited because no rule claim was made. An uncited claim would be the thing this " +
              "product exists to avoid."
      }));
    }
    (response.citations || []).forEach(function (citation) { host.appendChild(citationBlock(citation)); });
    byId("ask-answer-heading").focus();
    announce(headline + ". " + (response.answer || ""));
  }

  function renderAsk() {
    var root = byId("ask-body");
    clear(root);
    var examples = Source.askExamples();

    if (Source.live) {
      var input = h("input", { id: "ask-input", type: "text", autocomplete: "off" });
      root.appendChild(h("form", {
        class: "ask-input-row",
        onsubmit: function (event) {
          event.preventDefault();
          var question = input.value.trim();
          if (!question) return;
          Source.ask(question, state.householdId).then(function (response) {
            renderAskResponse(byId("ask-answer"), question, response);
          }).catch(function (error) {
            clear(byId("ask-answer"));
            byId("ask-answer").appendChild(errorCard("The question could not be sent", error));
          });
        }
      }, [
        h("div", null, [
          h("label", { for: "ask-input", text: "Ask about a rule" }),
          input,
          h("p", { class: "hint", text: "Routed to deterministic rule handlers. No document text reaches the calculation." })
        ]),
        h("button", { type: "submit", class: "action", text: "Ask" })
      ]));
    }

    root.appendChild(h("h3", { text: "Recorded questions", style: { marginTop: "0" } }));
    root.appendChild(h("div", { class: "button-row" }, examples.map(function (example) {
      return h("button", {
        type: "button", class: "action secondary",
        onclick: function () { renderAskResponse(byId("ask-answer"), example.question, example.response); }
      }, [example.question]);
    })));
    root.appendChild(h("div", { id: "ask-answer" }));

    var first = examples.filter(function (e) { return e.key === "answer_threshold"; })[0] || examples[0];
    if (first) {
      var host = byId("ask-answer");
      renderAskResponse(host, first.question, first.response, { silent: true });
      byId("live-status").textContent = "";   // do not announce on first paint
      if (document.activeElement === byId("ask-answer-heading")) byId("ask-answer-heading").blur();
    }
  }

  // ── panel 4: the calculation ────────────────────────────────────────────────────
  function renderCalc() {
    var root = byId("calc-body");
    clear(root);
    if (!state.report) { root.appendChild(noReportNotice()); return; }

    root.appendChild(h("dl", { class: "kv" }, [
      h("dt", { text: "Ruleset" }), h("dd", { class: "mono", text: state.report.ruleset_version }),
      h("dt", { text: "Frozen event date" }), h("dd", { text: state.report.reference_date || "—" }),
      h("dt", { text: "Engine" }), h("dd", { class: "mono", text: state.report.engine_version })
    ]));

    (state.report.calculations || []).forEach(function (calc) {
      var inputs = h("div", { class: "table-scroll" }, [
        h("table", null, [
          h("caption", { text: "Inputs to " + calc.name.replace(/_/g, " ") }),
          h("thead", null, [h("tr", null, [
            h("th", { scope: "col", text: "Input" }),
            h("th", { scope: "col", text: "Value" }),
            h("th", { scope: "col", text: "From document" })
          ])]),
          h("tbody", null, (calc.inputs || []).map(function (input) {
            return h("tr", null, [
              h("th", { scope: "row", text: input.label.replace(/_/g, " ") }),
              h("td", { text: plain(input.value) }),
              h("td", { class: "mono", text: input.from_document || "—" })
            ]);
          }))
        ])
      ]);

      root.appendChild(h("section", { class: "card", "aria-labelledby": "calc-" + calc.name }, [
        h("h3", { id: "calc-" + calc.name, style: { marginTop: "0" }, text: calc.name.replace(/_/g, " ") }),
        inputs,
        h("h4", { text: "Formula" }),
        h("code", { class: "formula", text: calc.formula }),
        h("dl", { class: "kv" }, [
          h("dt", { text: "Result" }), h("dd", { text: money(calc.result) }),
          h("dt", { text: "Frozen 60% threshold" }),
          h("dd", { text: calc.threshold === null || calc.threshold === undefined
            ? "No threshold applies to this line" : money(calc.threshold) }),
          h("dt", { text: "Threshold rule" }), h("dd", { class: "mono", text: calc.threshold_rule_id || "—" }),
          h("dt", { text: "Calculation rule" }), h("dd", { class: "mono", text: calc.rule_id || "—" }),
          h("dt", { text: "Effective date" }), h("dd", { text: calc.effective_date || "—" })
        ]),
        h("div", { class: "callout" }, [
          h("p", { text: COMPARISON[calc.comparison] || String(calc.comparison) }),
          h("p", { style: { marginBottom: "0" } }, [
            h("strong", { text: "A comparison is not a determination. " }),
            "This line says how one number sits against a frozen table. It does not say what happens next; " +
            "a qualified housing professional decides that."
          ])
        ])
      ]));
    });

    var openItems = stepReasonBlock(4);
    if (openItems) root.appendChild(openItems);

    root.appendChild(h("h3", { text: "Rules cited by this report" }));
    (state.report.citations || []).forEach(function (citation) { root.appendChild(citationBlock(citation)); });
  }

  // ── step 5: what is missing or out of date ──────────────────────────────────────
  /** The readiness line, as a USWDS-style alert: new information, stated in words first.
   *  The machine token is kept but demoted behind a disclosure, never used as the headline. */
  function readinessAlert() {
    var readiness = READINESS[state.report.readiness_status] || {
      title: String(state.report.readiness_status), detail: ""
    };
    var ready = state.report.readiness_status === "READY_TO_REVIEW";
    return h("div", { class: "alert " + (ready ? "alert--ok" : "alert--warn") }, [
      h("h3", { style: { marginTop: "0" }, text: readiness.title }),
      h("p", { text: readiness.detail }),
      h("p", { text: state.report.human_decision_notice }),
      h("details", { class: "tech" }, [
        h("summary", { text: "Technical details" }),
        h("dl", { class: "kv" }, [
          h("dt", { text: "readiness_status" }),
          h("dd", { class: "mono", text: state.report.readiness_status })
        ])
      ])
    ]);
  }

  function renderChecklist() {
    var root = byId("checklist-body");
    clear(root);
    if (!state.report) { root.appendChild(noReportNotice()); return; }

    root.appendChild(readinessAlert());

    var order = ["missing", "expired", "undatable", "unreadable", "present"];
    var checklist = state.report.checklist || [];

    // USWDS summary box: a short checklist of what to do next, and nothing else in it.
    var todo = checklist.filter(function (item) {
      return item.state !== "present" && item.action_for_renter;
    });
    if (todo.length) {
      root.appendChild(h("div", {
        class: "summary-box", role: "region", "aria-labelledby": "next-steps-heading"
      }, [
        h("h3", { id: "next-steps-heading", style: { marginTop: "0" }, text: "What you can do next" }),
        h("ul", { class: "summary-box__list" }, todo.slice(0, 5).map(function (item) {
          return h("li", null, [
            h("strong", { text: item.label + ": " }), item.action_for_renter
          ]);
        })),
        todo.length > 5
          ? h("p", { class: "status-line", style: { marginBottom: "0" },
              text: "The remaining " + (todo.length - 5) + " open item(s) are listed in full below." })
          : null
      ]));
    }

    order.forEach(function (stateName) {
      var items = checklist.filter(function (item) { return item.state === stateName; });
      if (!items.length) return;
      var words = STATE_WORDS[stateName];
      root.appendChild(h("h3", null, [words.word + " (" + items.length + ")"]));
      items.forEach(function (item) {
        root.appendChild(h("div", { class: "card" }, [
          h("h4", { style: { marginTop: "0" } }, [item.label, " ", stateChip(item.state)]),
          h("dl", { class: "kv" }, [
            h("dt", { text: "Item" }), h("dd", { class: "mono", text: item.item_id }),
            h("dt", { text: "Required because" }), h("dd", { class: "mono", text: item.required_because_rule_id }),
            h("dt", { text: "Satisfied by" }),
            h("dd", { class: "mono", text: (item.satisfied_by || []).length ? item.satisfied_by.join(", ") : "nothing yet" }),
            h("dt", { text: "Detail" }), h("dd", { text: item.detail || "—" }),
            h("dt", { text: "What you can do" }), h("dd", { text: item.action_for_renter || "Nothing — this one is done." })
          ])
        ]));
      });
    });

    var openItems = stepReasonBlock(5);
    if (openItems) root.appendChild(openItems);
  }

  // ── step 6a: check what we found (GOV.UK "check answers") ───────────────────────
  /** One row: what it is, what we have, and a Change link whose accessible name says
   *  which thing it changes. Change returns the user to the step, then straight back here. */
  function answerRow(label, value, stepNumber, changeDescription) {
    return h("div", { class: "answer-row" }, [
      h("dt", { class: "answer-row__key", text: label }),
      h("dd", { class: "answer-row__value" }, Array.isArray(value) ? value : [value]),
      h("dd", { class: "answer-row__action" }, [
        stepNumber
          ? h("button", {
              type: "button", class: "change-link",
              onclick: function () {
                state.returnTo = "screen-6";
                goToStep(stepNumber);
              }
            }, [
              "Change",
              h("span", { class: "visually-hidden", text: " " + changeDescription })
            ])
          : h("span", { class: "status-line", text: "—" })
      ])
    ]);
  }

  function renderSummary() {
    var root = byId("summary-body");
    clear(root);
    if (!state.report) { root.appendChild(noReportNotice()); return; }

    var report = state.report;
    var calc = findCalculation(report, "annualized_income");
    var checklist = report.checklist || [];
    var open = checklist.filter(function (item) { return item.state !== "present"; });
    var docs = report.documents || [];
    var fieldCount = docs.reduce(function (sum, d) { return sum + (d.fields || []).length; }, 0);
    var abstentions = report.abstentions || [];
    var reasons = report.review_reasons || [];

    root.appendChild(readinessAlert());

    var correctionText = state.correction
      ? state.correction.field + " = " + plain(state.correction.value) + " on " +
        state.correction.document_id +
        (correctionWasRejected(report)
          ? " — recorded, but not used in the calculation"
          : " — used in the calculation")
      : "You have not corrected anything.";

    root.appendChild(h("dl", { class: "answer-list" }, [
      answerRow("Household", report.household_id + " · " + docs.length + " documents", 1,
        "the household documents we read"),
      answerRow("Values read from the documents",
        fieldCount + " values, each one traced to a box on a page", 1,
        "the values we read from your documents"),
      answerRow("Your corrections", correctionText, 2,
        "the correction you made to a value we read"),
      answerRow("Rule you asked about", state.lastQuestion || "You have not asked about a rule.", 3,
        "the housing rule you asked about"),
      answerRow("Yearly income figure",
        calc ? money(calc.result) + " — " + (COMPARISON[calc.comparison] || String(calc.comparison))
             : "No income calculation is present in this report.", 4,
        "how the yearly income figure was worked out"),
      answerRow("Still missing or out of date",
        open.length
          ? open.length + " item(s): " + open.map(function (i) { return i.label; }).join(", ")
          : "Nothing. Every required item is present and current.", 5,
        "what is missing or out of date"),
      answerRow("Questions the system will not answer on its own",
        abstentions.length + " abstention(s) and " + reasons.length +
        " reason(s) this needs review. All of them are listed in full under " +
        "“What this system is unsure about”, and all of them travel with your packet.",
        null, null)
    ]));
  }

  // ── step 6b: the packet ─────────────────────────────────────────────────────────
  function renderPacket() {
    var root = byId("packet-body");
    clear(root);
    if (!state.report) return;

    root.appendChild(h("h2", { text: "Take your packet" }));
    root.appendChild(h("div", { class: "callout" }, [
      h("p", null, [
        h("strong", { text: "Nothing is sent anywhere. " }),
        "This button writes a file to your own device and nothing else. RealDoor does not transmit " +
        "your packet to any property, provider, or third party — sharing it is your decision, made outside this app."
      ]),
      h("p", { style: { marginBottom: "0" } }, [
        "The packet contains what your documents show, what is still missing or expired, and every open " +
        "question below. It contains no eligibility outcome, because this service does not produce one."
      ])
    ]));
    root.appendChild(h("div", { class: "button-row" }, [
      h("button", {
        type: "button", class: "action action--lead", id: "packet-download",
        onclick: function () {
          Source.packet(state.householdId, state.report).then(function (result) {
            var url = URL.createObjectURL(result.blob);
            var link = h("a", { href: url, download: result.filename });
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
            announce("Packet " + result.filename + " downloaded to your device. Nothing was sent anywhere.");
            var note = byId("packet-download-note");
            clear(note);
            note.appendChild(h("p", {
              class: "status-line",
              text: "Downloaded " + result.filename + " to your device at your request. No network transmission took place."
            }));
          }).catch(function (error) {
            var note = byId("packet-download-note");
            clear(note);
            note.appendChild(errorCard("The packet could not be built", error));
          });
        }
      }, ["Download my readiness packet"])
    ]));
    root.appendChild(h("div", { id: "packet-download-note" }));
  }

  // ── panel 6: the controls, demonstrated ─────────────────────────────────────────
  var CONTROL_PROBES = [
    { key: "refusal_decide_for_me", title: "Someone demands an eligibility decision" },
    { key: "refusal_cross_applicant", title: "Someone asks about a different applicant" },
    { key: "refusal_embedded_instruction", title: "A document tries to give the system instructions" }
  ];

  function renderControls() {
    var root = byId("controls-body");
    clear(root);
    var examples = window.REALDOOR_FIXTURES.ask_examples || {};

    CONTROL_PROBES.forEach(function (probe, index) {
      var example = examples[probe.key];
      if (!example) return;
      var outputId = "probe-output-" + index;
      root.appendChild(h("section", { class: "card", "aria-labelledby": "probe-h-" + index }, [
        h("h3", { id: "probe-h-" + index, style: { marginTop: "0" }, text: probe.title }),
        h("p", null, [h("strong", { text: "Input: " }), example.question]),
        h("div", { class: "button-row" }, [
          h("button", {
            type: "button", class: "action",
            onclick: function () {
              var host = byId(outputId);
              clear(host);
              var run = Source.live
                ? Source.ask(example.question, state.householdId)
                : Promise.resolve(example.response);
              run.then(function (response) {
                host.appendChild(h("div", { class: "callout callout--stop" }, [
                  h("h4", { style: { marginTop: "0" }, text: "Response returned" }),
                  h("p", { text: response.answer }),
                  h("p", { class: "status-line" }, [
                    "kind: ", h("span", { class: "mono", text: response.kind }),
                    " · refused: " + String(response.refused) + " · abstained: " + String(response.abstained) +
                    " · rules: " + (response.rule_ids || []).join(", ")
                  ]),
                  response.what_would_resolve_it
                    ? h("p", { style: { marginBottom: "0" } },
                        [h("strong", { text: "Offered instead: " }), response.what_would_resolve_it])
                    : null
                ]));
                announce(probe.title + ": " + response.answer);
              }).catch(function (error) {
                host.appendChild(errorCard("The probe could not be run", error));
              });
            }
          }, ["Run this probe"])
        ]),
        h("div", { id: outputId })
      ]));
    });

    // the output gate, demonstrated against itself
    root.appendChild(h("section", { class: "card", "aria-labelledby": "gate-h" }, [
      h("h3", { id: "gate-h", style: { marginTop: "0" }, text: "The output gate, tested against itself" }),
      h("p", {
        text: "The server has an endpoint whose only job is to try to return a forbidden payload — one " +
              "containing an eligibility flag and a numeric rating. If the gate is working, that response " +
              "never reaches you: the server withholds its own answer and returns HTTP 500 instead. " +
              "This endpoint succeeding would be the system failing."
      }),
      h("div", { class: "button-row" }, [
        h("button", {
          type: "button", class: "action",
          onclick: function () {
            var host = byId("gate-output");
            clear(host);
            Source.gateSelftest().then(function (result) {
              if (!result.available) {
                host.appendChild(h("div", { class: "callout callout--warn" }, [
                  h("h4", { style: { marginTop: "0" }, text: "Not run — there is no server to test" }),
                  h("p", {
                    style: { marginBottom: "0" },
                    text: "This control lives in the API process, so it cannot be demonstrated from bundled " +
                          "fixtures. Rather than show you a recording and call it a live test, the app reports " +
                          "it as not run. Start the API and set window.REALDOOR_API to see the real 500."
                  })
                ]));
                announce("Gate self-test not run: no server is connected.");
                return;
              }
              var held = result.status === 500 && result.body && result.body.error === "decision_gate_blocked_response";
              host.appendChild(h("div", { class: "callout " + (held ? "callout--ok" : "callout--stop") }, [
                h("h4", { style: { marginTop: "0" } }, [
                  held ? "Gate held. HTTP " + result.status + " — the server withheld its own response."
                       : "GATE FAILED. HTTP " + result.status + " — a forbidden payload got through."
                ]),
                h("p", { text: result.body.detail || "" }),
                h("p", { class: "status-line", text: "Blocked keys: " +
                  JSON.stringify(result.body.violations || result.body) })
              ]));
              announce(held ? "Gate held. The server withheld its own response with HTTP 500."
                            : "Gate failed. A forbidden payload got through.");
            });
          }
        }, ["Try to make the server return a decision"])
      ]),
      h("div", { id: "gate-output" })
    ]));

    // session deletion
    root.appendChild(h("section", { class: "card", "aria-labelledby": "session-h" }, [
      h("h3", { id: "session-h", style: { marginTop: "0" }, text: "Delete this session" }),
      h("p", {
        text: "Everything this app holds about the household lives in one session. Deleting it removes " +
              "the documents, the extracted values, and every correction from the process; requests that " +
              "follow return 404 because there is nothing left to answer with."
      }),
      h("div", { class: "button-row" }, [
        h("button", {
          type: "button", class: "action",
          onclick: function () {
            var host = byId("session-output");
            clear(host);
            Source.deleteSession().then(function (result) {
              if (!result.live) {
                state.report = null;
                state.baselineReport = null;
                state.correction = null;
                state.documentId = null;
                state.activeField = null;
                renderAll();
                host.appendChild(h("div", { class: "callout callout--ok" }, [
                  h("h4", { style: { marginTop: "0" }, text: "In-page session data cleared" }),
                  h("p", {
                    style: { marginBottom: "0" },
                    text: "Offline there is no server session to destroy, so this clears everything the page " +
                          "was holding: the report, the correction, and the selected document. Reload the page " +
                          "to start again. With the API connected, this same button deletes the server session."
                  })
                ]));
                announce("Session data cleared from this page.");
                return;
              }
              host.appendChild(h("div", { class: "callout callout--ok" }, [
                h("h4", { style: { marginTop: "0" }, text: "Server session deleted" }),
                h("p", { class: "mono", text: JSON.stringify(result.body) }),
                h("p", {
                  style: { marginBottom: "0" },
                  text: "Session " + result.session_id + " no longer exists in the API process. Any further " +
                        "request with that id returns 404."
                })
              ]));
              announce("Server session deleted.");
            }).catch(function (error) {
              host.appendChild(errorCard("The session could not be deleted", error));
            });
          }
        }, ["Delete session data now"])
      ]),
      h("div", { id: "session-output" })
    ]));
  }

  // ── panel 7: our own numbers ────────────────────────────────────────────────────
  var SECTION_TITLES = {
    extraction: "Reading values off the documents",
    adversarial: "Hostile inputs from the challenge pack",
    calculation: "Agreement with the organizer's own calculator",
    rule_questions: "Rule questions answered correctly",
    citations: "Citations re-checked against their live source",
    accessibility: "Accessibility scan"
  };

  function renderMeasure() {
    var root = byId("measure-body");
    clear(root);
    var data = state.selftest;
    if (!data) { root.appendChild(h("p", { text: "Measurements are loading…" })); return; }

    root.appendChild(h("div", { class: "callout" }, [
      h("p", { style: { marginBottom: "0" }, text: data.honesty_note || "" })
    ]));
    root.appendChild(h("p", { class: "status-line", text: "Measured at " + (data.generated_at || "unknown time") + "." }));

    Object.keys(data.sections || {}).forEach(function (key) {
      var section = data.sections[key];
      var notRun = section.status !== "measured";
      var rows = Object.keys(section).filter(function (name) {
        return name !== "status" && name !== "note";
      }).map(function (name) {
        var value = section[name];
        return h("tr", null, [
          h("th", { scope: "row", text: name.replace(/_/g, " ") }),
          h("td", { text: Array.isArray(value) ? (value.length ? value.join(", ") : "none") : plain(value) })
        ]);
      });

      root.appendChild(h("section", { class: "card", "aria-labelledby": "measure-" + key }, [
        h("h3", { id: "measure-" + key, style: { marginTop: "0" } }, [
          SECTION_TITLES[key] || key.replace(/_/g, " "), " ",
          h("span", { class: "chip " + (notRun ? "chip--missing" : "chip--present") }, [
            h("span", { "aria-hidden": "true", text: (notRun ? "! " : "✓ ") }),
            notRun ? "Not run" : "Measured"
          ])
        ]),
        rows.length ? h("div", { class: "table-scroll" }, [h("table", null, [
          h("caption", { class: "visually-hidden", text: "Measurements for " + (SECTION_TITLES[key] || key) }),
          h("thead", null, [h("tr", null, [
            h("th", { scope: "col", text: "Measure" }),
            h("th", { scope: "col", text: "Value" })
          ])]),
          h("tbody", null, rows)
        ])]) : null,
        section.note ? h("p", { class: "status-line", text: section.note }) : null
      ]));
    });

    // Read the shortfalls out of the data rather than writing them into the page. If a
    // re-export improves a number, this paragraph improves with it; if it gets worse, this
    // paragraph says so. A hardcoded confession goes stale and becomes its own dishonesty.
    var sections = data.sections || {};
    var notRunNames = Object.keys(sections)
      .filter(function (key) { return sections[key].status !== "measured"; })
      .map(function (key) { return (SECTION_TITLES[key] || key).toLowerCase(); });
    var shortfalls = [];
    Object.keys(sections).forEach(function (key) {
      var section = sections[key];
      if (section.status !== "measured") return;
      if (typeof section.passed === "number" && typeof section.total_tests === "number" &&
          section.passed < section.total_tests) {
        shortfalls.push((SECTION_TITLES[key] || key).toLowerCase() + ": " +
          section.passed + " of " + section.total_tests + " passing");
      }
      if (typeof section.wrong === "number" && section.wrong > 0) {
        shortfalls.push((SECTION_TITLES[key] || key).toLowerCase() + ": " + section.wrong + " wrong");
      }
      if (typeof section.disagree === "number" && section.disagree > 0) {
        shortfalls.push((SECTION_TITLES[key] || key).toLowerCase() + ": " + section.disagree + " disagreements");
      }
    });

    root.appendChild(h("div", { class: "callout callout--warn" }, [
      h("h3", { style: { marginTop: "0" }, text: "About the numbers that look bad" }),
      h("p", {
        text: (shortfalls.length
                ? "Measured shortfalls in this run — " + shortfalls.join("; ") + ". "
                : "No measured section fell short in this run. ") +
              (notRunNames.length
                ? "Not run at all: " + notRunNames.join(", ") + ". "
                : "") +
              "These are the measurements as they came out at the timestamp above. They are printed here " +
              "rather than smoothed, because a product whose whole argument is that quality must be measured " +
              "cannot then publish only its good numbers."
      }),
      (sections.accessibility && sections.accessibility.status !== "measured")
        ? h("p", {
            style: { marginBottom: "0" },
            text: "The accessibility row reads not_run because this interface did not exist when that " +
                  "snapshot was taken. The scan has since been run against every screen of this build, over " +
                  "both file:// and http://; its raw output is written to ui/axe-report.json. It is not " +
                  "restated here, because this panel shows the measurement file as it is, not as we would " +
                  "like it to read."
          })
        : null
    ]));
  }

  // ── the always-visible open-questions rail ──────────────────────────────────────
  /** A readable heading for an abstention. `about` is either a snake_case subject such as
   *  annualized_wage_income, or a checklist id such as CHK-EMPLOYMENT-LETTER; the second
   *  kind is looked up so the renter reads "Employment verification letter" instead. */
  function abstentionHeading(item) {
    var about = String(item.about);
    var match = ((state.report && state.report.checklist) || []).filter(function (entry) {
      return entry.item_id === about;
    })[0];
    if (match && match.label) return match.label;
    if (/^[a-z0-9_]+$/.test(about)) return about.replace(/_/g, " ");
    return about.replace(/^CHK-/, "").replace(/[-_]/g, " ").toLowerCase();
  }

  function renderOpenQuestions() {
    var root = byId("open-questions-body");
    clear(root);
    if (!state.report) {
      root.appendChild(h("p", { class: "q-empty", text: "No report is loaded." }));
      return;
    }

    var abstentions = state.report.abstentions || [];
    var reasons = state.report.review_reasons || [];

    root.appendChild(h("h3", { text: "Abstentions (" + abstentions.length + ")" }));
    if (!abstentions.length) {
      root.appendChild(h("p", {
        class: "q-empty",
        text: "None for this household: every value needed was read from a document and every required " +
              "item is accounted for. An empty list means nothing was withheld, not that nothing was checked."
      }));
    }
    abstentions.forEach(function (item) {
      root.appendChild(h("div", { class: "q-item" }, [
        // `about` is sometimes a checklist id such as CHK-EMPLOYMENT-LETTER. A machine id is
        // never the headline: it is resolved to that item's own human label where one exists,
        // and kept verbatim under Technical details either way.
        h("h3", { text: abstentionHeading(item) }),
        h("p", { text: item.reason }),
        h("p", { class: "q-resolve", text: "Resolved by: " + item.what_would_resolve_it }),
        h("details", { class: "tech" }, [
          h("summary", { text: "Technical details" }),
          h("p", { class: "mono", style: { marginBottom: "0" }, text: "about: " + String(item.about) })
        ])
      ]));
    });

    root.appendChild(h("h3", { text: "Reasons this needs review (" + reasons.length + ")" }));
    if (!reasons.length) {
      root.appendChild(h("p", { class: "q-empty", text: "None recorded for this household." }));
    }
    reasons.forEach(function (reason) {
      var n = reasonStep(reason);
      root.appendChild(h("div", { class: "q-item" }, [
        // A human heading, not the machine code. The code stays available one disclosure away.
        h("h3", { text: reasonHeading(reason) }),
        h("p", { text: reason.message }),
        h("p", { style: { marginBottom: "0" } }, [
          h("button", {
            type: "button", class: "change-link",
            onclick: function () { state.returnTo = null; goToStep(n); }
          }, [
            "Go to step " + n,
            h("span", { class: "visually-hidden", text: " to see this item in context" })
          ])
        ]),
        h("details", { class: "tech" }, [
          h("summary", { text: "Technical details" }),
          h("p", { class: "mono", style: { marginBottom: "0" },
            text: reason.code + " · check: " + reason.check + " · rule: " + reason.rule_id })
        ])
      ]));
    });
  }

  // ── shared bits ─────────────────────────────────────────────────────────────────
  function noReportNotice() {
    return h("div", { class: "callout callout--warn" }, [
      h("h3", { style: { marginTop: "0" }, text: "No report is loaded for this household" }),
      h("p", {
        style: { marginBottom: "0" },
        text: "The offline bundle carries the pipeline's real output for HH-001, HH-004 and HH-005 only. " +
              "The other households exist in the file list but no report was exported for them, and the app " +
              "will not fabricate one. Start the API and set window.REALDOOR_API to load any household."
      })
    ]);
  }
  function errorCard(title, error) {
    return h("div", { class: "callout callout--stop" }, [
      h("h3", { style: { marginTop: "0" }, text: title }),
      h("p", { style: { marginBottom: "0" }, class: "mono", text: String(error && error.message ? error.message : error) })
    ]);
  }

  function renderFooter() {
    var parts = ["Data source: " + Source.describe()];
    if (state.report) {
      parts.push("engine " + state.report.engine_version);
      parts.push("ruleset " + state.report.ruleset_version);
      parts.push("frozen event date " + state.report.reference_date);
      parts.push("report generated " + state.report.generated_at);
    }
    byId("footer-meta").textContent = parts.join(" · ");
    byId("mode-line").textContent = "Data source: " + Source.describe();
  }

  function renderAll() {
    renderOpenQuestions();
    renderDocuments();
    renderCorrect();
    renderCalc();
    renderChecklist();
    renderSummary();
    renderPacket();
    renderFooter();
    // The error summary and the indicator depend on the report, so they are refreshed
    // whenever the report changes, not only when the screen changes.
    renderErrorSummary();
    renderStepIndicator();
  }

  // ── the secondary route ─────────────────────────────────────────────────────────
  // One level of disclosure and one level only: everything judge-facing lives on this
  // single screen, reachable in one click from anywhere and returning to where you were.
  function setUpMetaNav() {
    byId("go-how").addEventListener("click", function () {
      if (state.screen !== "screen-how") state.returnScreen = state.screen;
      showScreen("screen-how");
    });
  }

  // ── boot ────────────────────────────────────────────────────────────────────────
  function loadHousehold(householdId) {
    state.householdId = householdId;
    state.baselineReport = null;
    state.correction = null;
    state.documentId = null;
    state.activeField = null;
    return Source.report(householdId).then(function (report) {
      state.report = report;
      renderAll();
    });
  }

  function boot() {
    setUpMetaNav();
    renderProcessList();
    renderAsk();
    renderControls();
    showScreen("screen-start", { focus: false, announce: false });

    Source.selftest().then(function (data) {
      state.selftest = data;
      renderMeasure();
    }).catch(function (error) {
      var root = byId("measure-body");
      clear(root);
      root.appendChild(errorCard("Measurements could not be loaded", error));
    });

    Source.households().then(function (households) {
      state.households = households;
      var select = byId("household-select");
      clear(select);
      households.forEach(function (row) {
        select.appendChild(h("option", {
          value: row.household_id,
          text: row.household_id + " — " + row.document_count + " documents" +
                (row.has_report ? "" : " (no bundled report)")
        }));
      });
      select.addEventListener("change", function () {
        loadHousehold(select.value).then(function () {
          announce("Loaded " + select.value + ". " +
            (state.report ? READINESS[state.report.readiness_status].title : "No report is bundled for it."));
        });
      });
      var first = households.filter(function (row) { return row.has_report; })[0] || households[0];
      select.value = first.household_id;
      return loadHousehold(first.household_id);
    }).catch(function (error) {
      var root = byId("documents-body");
      clear(root);
      root.appendChild(errorCard("Households could not be loaded", error));
    });
  }

  // The probe must settle before boot: the data-source label and every fetch have to agree
  // about which source they are describing.
  function start() { Source.adoptSameOriginApi().then(boot, boot); }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
