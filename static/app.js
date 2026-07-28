(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Backend config
  // ---------------------------------------------------------------------
  // Requires CORS enabled on the FastAPI side. Since this page is opened via
  // file://, the browser sends Origin: null, so the backend's
  // CORSMiddleware needs allow_origins=["*"] (a specific origin won't match).
  //
  // Locally, `uvicorn app.main:app` serves routes unprefixed
  // (e.g. /water_transfer/recommend), so file:// / localhost keep hitting
  // that directly. On Vercel, vercel.json routes "/api/(.*)" to
  // api/index.py, which mounts the same app under /api - so any other host
  // uses the relative "/api" prefix instead.
  var API_BASE_URL =
    window.location.protocol === "file:" ||
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname === "localhost"
      ? "http://127.0.0.1:8000"
      : "/api";

  function prettifyKey(key) {
    return key
      .replace(/_/g, " ")
      .replace(/\b\w/g, function (c) {
        return c.toUpperCase();
      });
  }

  function formatDetailValue(value) {
    if (typeof value === "number" && !Number.isInteger(value)) {
      return String(Math.round(value * 100) / 100);``
    }
    return String(value);
  }

  // next_question's "unit" field (e.g. borewell_size -> "inch") is display-only,
  // it's never asked as its own question, but /recommend still requires a
  // companion "<field>_unit" answer. The naming doesn't follow one consistent
  // rule (borewell_size -> borewell_unit, well_depth -> well_depth_unit), so
  // known cases are mapped explicitly; anything new falls back to "<key>_unit"
  // and is harmless to send even when unused, since the backend ignores
  // extra fields it doesn't recognize.
  var UNIT_FIELD_OVERRIDES = {
    borewell_size: "borewell_unit",
    well_depth: "well_depth_unit",
  };
  function unitFieldNameFor(key) {
    return UNIT_FIELD_OVERRIDES[key] || key + "_unit";
  }

  // tank_filling's inside_or_outside and horizontal_or_vertical are the only
  // fixed-choice questions the backend currently has; they go through
  // /answer_category (ParsedCategory) instead of /answer (ParsedAnswer).
  var CATEGORY_QUESTION_KEYS = ["inside_or_outside", "horizontal_or_vertical"];

  // ---------------------------------------------------------------------
  // Conversation flow. The application question and lead-capture are fixed;
  // everything about sizing the pump (which questions to ask, in what order)
  // is driven live by the backend's /{slug}/next_question endpoint.
  // ---------------------------------------------------------------------
  var contactValidate = function (value) {
    var trimmed = value.trim();
    if (/^\d{10}$/.test(trimmed) || /^\S+@\S+\.\S+$/.test(trimmed)) return null;
    return "Please enter a valid email address or 10-digit phone number.";
  };
  var pincodeValidate = function (value) {
    return /^\d{6}$/.test(value.trim()) ? null : "Please enter a valid 6-digit pincode.";
  };

  var FLOW = [
    {
      id: "application",
      kind: "options",
      bot: function () {
        return "Hi there! I can help you pick the right Wilo pump. What's your application?";
      },
      options: [
        {
          label: "Water extraction from a borewell/well",
          value: "water-transfer",
          icon: "⛽",
          subtitle: "Borewell to overhead tank",
        },
        {
          label: "Transfer of water from a ground-level reservoir to an elevated tank",
          value: "tank-filling",
          icon: "💧",
          subtitle: "Ground tank to upper tank",
        },
        // {
        //   label: "Pressure Boosting",
        //   value: "pressure-boosting",
        //   icon: "🌀",
        //   subtitle: "Steady water pressure",
        // },
        // {
        //   label: "Dewatering",
        //   value: "dewatering",
        //   icon: "🌊",
        //   subtitle: "Remove unwanted water",
        // },
        // {
        //   label: "Hot Water Circulation",
        //   value: "hot-water-circulation",
        //   icon: "♨️",
        //   subtitle: "Hot water recirculation",
        // },
      ],
      next: function (value) {
        if (value === "water-transfer") return "__dynamic__water_transfer";
        if (value === "tank-filling") return "__dynamic__tank_filling";
        return "coming-soon";
      },
    },
    {
      id: "coming-soon",
      kind: "options",
      bot: function () {
        return "That application isn't available yet, we're still adding support for it. For now you can try Water Transfer, or pick another application below.";
      },
      options: [
        { label: "Back to applications", value: "back", icon: "↩️", subtitle: "Choose a different one" },
      ],
      next: function () {
        return "application";
      },
    },
    {
      id: "lead-contact",
      kind: "input",
      bot: function () {
        return "Please provide your Email address or Contact number. So we can send detailed pump specifications";
      },
      placeholder: "Email or 10-digit phone number",
      validate: contactValidate,
      next: function () {
        return "lead-pincode";
      },
    },
    {
      id: "lead-pincode",
      kind: "input",
      bot: function () {
        return "What is your area pin code so we can locate the nearest dealer to you.";
      },
      placeholder: "6-digit pincode",
      validate: pincodeValidate,
      next: function () {
        return "thank-you";
      },
    },
    {
      id: "thank-you",
      kind: "final",
      bot: function () {
        var msg = "✅ Thank you! Our dealer will reach out to you shortly, and your details have been shared with dealer.";
        if (state.selectedPump) {
          var pump = state.selectedPump.recommendation;
          var details = pump.details || {};
          msg += "\n\nSelected Pump:\n" + (pump.model_name || "Unknown model");
          DETAIL_DISPLAY_RULES.forEach(function (rule) {
            var matchedKey = Object.keys(details).find(rule.test);
            if (matchedKey != null && details[matchedKey] != null && details[matchedKey] !== "") {
              msg += "\n" + rule.label + ": " + rule.format(details[matchedKey]);
            }
          });
          if (pump.art_no != null) {
            msg += "\nArticle No.: " + String(pump.art_no);
          }
        }
        return msg;
      },
      followUp: function () {
        return [
          {
            kind: "text",
            text:
              "🙏 Thank you for visiting Wilo!\n\n" +
              "We appreciate your interest in our products and services. If you need any further assistance, our support team is ready to help. 😊",
          },
          {
            kind: "html",
            html:
              "Contact Support:<br>" +
              '📧 <a href="mailto:sales@wilo.com">sales@wilo.com</a><br>' +
              '🌐 <a href="https://wilo.com/in/en/Dealers/" target="_blank" rel="noopener noreferrer">https://wilo.com/in/en/Dealers/</a>',
          },
        ];
      },
      next: function () {
        return "explore-more";
      },
    },
    {
      id: "explore-more",
      kind: "input",
      bot: function () {
        return "Do you want to explore more pumps for your application? (yes/no)";
      },
      placeholder: "Type yes or no",
      validate: function (value) {
        var trimmed = value.toLowerCase().trim();
        if (trimmed === "yes" || trimmed === "no") return null;
        return "Please answer with 'yes' or 'no'.";
      },
      next: function () {
        var answer = state.answers["explore-more"];
        return answer && answer.toLowerCase().trim() === "yes" ? "application" : "final-goodbye";
      },
    },
    {
      id: "final-goodbye",
      kind: "final",
      bot: function () {
        return "Have a nice day! 👋";
      },
      followUp: function () {
        return [
          {
            kind: "text",
            text: "Pumps we are providing for your application:",
          },
          {
            kind: "text",
            text: "⛽ Water extraction from a borewell/well",
          },
          {
            kind: "text",
            text: "💧 Transfer of water from a ground-level reservoir to an elevated tank",
          },
        ];
      },
      next: null,
    },
  ];

  function getStep(id) {
    for (var i = 0; i < FLOW.length; i++) {
      if (FLOW[i].id === id) return FLOW[i];
    }
    throw new Error("Unknown conversation step: " + id);
  }

  // ---------------------------------------------------------------------
  // Conversation state (mutated in place, then re-rendered)
  // ---------------------------------------------------------------------
  var messageCounter = 0;
  function nextMessageId() {
    messageCounter += 1;
    return "msg-" + messageCounter;
  }

  function timestamp() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  var state = {
    messages: [],
    answers: {},
    currentStepId: null,
    awaitingKind: null,
    inputError: null,
    virtualOptions: null, // [{ label, onSelect }] - used for backend-driven branches
    useCaseSlug: null, // "water_transfer" | "tank_filling" while the dynamic loop is active
    dynamicAnswers: {}, // accumulated answers fed to next_question, then to recommend as-is
    clarificationAttempts: {}, // question_key -> retry count, sent back to /answer as clarification_attempts
    clarificationUserInput: {}, // question_key -> original user input that triggered clarification
    currentQuestion: null, // last { key, prompt, unit, optional } from next_question
    lastRecommendation: null, // the ok recommendation, kept around for /explain_model follow-ups
    selectedPump: null, // { recommendation, tierLabel } when user selects a pump
  };

  function addBotMessage(text) {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), text: text, kind: "text" });
  }
  function addBotHtmlMessage(html) {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), html: html, kind: "html" });
  }
  /** Adds a step's main bot message, then any followUp messages (text or
   * html) it defines, e.g. the multi-message sign-off on "thank-you". */
  function addStepMessages(step, answers) {
    addBotMessage(step.bot(answers));
    if (!step.followUp) return;
    step.followUp(answers).forEach(function (msg) {
      if (msg.kind === "html") addBotHtmlMessage(msg.html);
      else addBotMessage(msg.text);
    });
  }
  function addUserMessage(text) {
    state.messages.push({ id: nextMessageId(), role: "user", timestamp: timestamp(), text: text, kind: "text" });
  }
  function addRecommendationMessage(recommendation, tiedAlternatives) {
    state.messages.push({
      id: nextMessageId(),
      role: "bot",
      timestamp: timestamp(),
      kind: "recommendation",
      recommendation: recommendation,
      tiedAlternatives: tiedAlternatives || [],
    });
  }

  function initConversation() {
    state.messages.push({ id: nextMessageId(), role: "bot", timestamp: timestamp(), kind: "welcome" });
    var first = FLOW[0];
    addBotMessage(first.bot({}));
    state.currentStepId = first.id;
    state.awaitingKind = first.kind;
  }

  function restartConversation() {
    state.messages = [];
    state.answers = {};
    state.currentStepId = null;
    state.awaitingKind = null;
    state.inputError = null;
    state.virtualOptions = null;
    state.useCaseSlug = null;
    state.dynamicAnswers = {};
    state.clarificationAttempts = {};
    state.clarificationUserInput = {};
    state.currentQuestion = null;
    state.lastRecommendation = null;
    state.selectedPump = null;
    initConversation();
    render();
  }

  function jumpToStep(stepId) {
    var step = getStep(stepId);
    state.virtualOptions = null;
    state.inputError = null;
    addStepMessages(step, state.answers);
    state.currentStepId = step.id;
    state.awaitingKind = step.kind;
  }

  function showUnreachableBackendError(retryFn) {
    addBotMessage(
      "I couldn't reach the recommendation service. Make sure the backend is running at " +
        API_BASE_URL +
        " and try again."
    );
    state.awaitingKind = "options";
    state.virtualOptions = [
      {
        label: "Retry",
        icon: "🔁",
        subtitle: "Try connecting again",
        onSelect: function () {
          addUserMessage("Retry");
          return retryFn();
        },
      },
    ];
    render();
  }


  /** Calls the recommendation backend for the active use case and handles
   * ok / confirmation_required / rejected / network-error. */
  async function runRecommendation(confirmOversize) {
    state.awaitingKind = "loading";
    state.virtualOptions = null;
    addBotMessage("Let me find the best pump for you...");
    render();

    var payload = Object.assign({}, state.dynamicAnswers);
    if (typeof confirmOversize === "boolean") payload.confirm_oversize = confirmOversize;

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      showUnreachableBackendError(function () {
        return runRecommendation(confirmOversize);
      });
      return;
    }

    if (data.status === "ok") {
      addBotMessage("Based on what you shared, here's a pump that matches your requirement:");
      addRecommendationMessage(data.recommendation, data.recommendation && data.recommendation.tied_alternatives);
      state.lastRecommendation = data.recommendation;
      render();
      return;
    }

    if (data.status === "confirmation_required") {
      addBotMessage(data.message || "This selection looks oversized for your setup. Do you want to proceed anyway?");
      state.awaitingKind = "options";
      state.virtualOptions = [
        {
          label: "Yes, use it anyway",
          icon: "✅",
          subtitle: "Proceed with this setup",
          onSelect: function () {
            addUserMessage("Yes, use it anyway");
            return runRecommendation(true);
          },
        },
        {
          label: "No, don't use it",
          icon: "✋",
          subtitle: "Decline the oversized pump",
          onSelect: function () {
            addUserMessage("No, don't use it");
            return runRecommendation(false);
          },
        },
      ];
      render();
      return;
    }

    // status === "rejected" (or anything unrecognized)
    addBotMessage(data.message || "Sorry, we couldn't find a suitable pump for these inputs.");
    jumpToStep("explore-more");
    render();
  }

  /** Asks the backend what to ask next for the active use case; once it
   * returns question: null, moves on to /recommend. */
  async function fetchNextQuestion(confirmationMessage) {
    state.awaitingKind = "loading";
    state.virtualOptions = null;

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/next_question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: state.dynamicAnswers }),
      });
      data = await res.json();
    } catch (err) {
      render();
      showUnreachableBackendError(function () { return fetchNextQuestion(confirmationMessage); });
      return;
    }

    console.log("[fetchNextQuestion] response:", data, "confirmationMessage:", confirmationMessage);

    if (data.question) {
      console.log("[fetchNextQuestion] advancing to question:", data.question.key);
      state.currentQuestion = data.question;
      state.awaitingKind = "dynamic-input";
      var messageText = data.question.prompt;
      if (confirmationMessage) {
        messageText = confirmationMessage + "\n" + data.question.prompt;
      }
      addBotMessage(messageText);
      render();
      return;
    }

    if (confirmationMessage) {
      addBotMessage(confirmationMessage);
    }

    render();
    return runRecommendation();
  }

  /** A required question that comes back "skipped" (or given-up-on) re-prompts
   * the user; an optional one is recorded as null and the loop moves on. */
  async function handleUnansweredQuestion(question) {
    if (!question.optional) {
      addBotMessage("I'm sorry, I can't recommend a pump based on the information provided so far.");

      state.virtualOptions = [
        {
          label: "Explore other pumps",
          icon: "🔍",
          subtitle: "Try a different approach",
          onSelect: function () {
            addUserMessage("Explore other pumps");
            addBotMessage("Let me help you explore other pump options. Would you like to try a different application?");
            state.useCaseSlug = null;
            state.dynamicAnswers = {};
            state.clarificationAttempts = {};
            state.currentQuestion = null;
            jumpToStep("application");
            render();
          }
        },
        {
          label: "No, that's okay",
          icon: "👋",
          subtitle: "End this conversation",
          onSelect: function () {
            addUserMessage("No, that's okay");
            jumpToStep("thank-you");
            render();
          }
        }
      ];

      state.awaitingKind = "options";
      render();
      return;
    }
    state.dynamicAnswers[question.key] = null;
    state.currentQuestion = null;
    await fetchNextQuestion();
  }

  /** Sends the user's free-text reply to the backend's fixed-choice parser
   * (ParsedCategory) for questions like inside_or_outside / horizontal_or_vertical. */
  async function submitCategoryAnswer(question, trimmed) {
    var payload = { question_key: question.key, user_text: trimmed };

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/answer_category", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      showUnreachableBackendError(function () {
        return submitCategoryAnswer(question, trimmed);
      });
      return;
    }

    if (data.needs_clarification) {
      addBotMessage(data.clarification_question || "Could you clarify that?");
      state.awaitingKind = "dynamic-input";
      render();
      return;
    }

    if (data.skipped) {
      handleUnansweredQuestion(question);
      return;
    }

    state.dynamicAnswers[question.key] = data.category;
    state.currentQuestion = null;
    await fetchNextQuestion(data.confirmation_message);
  }

  /** Sends the user's free-text reply to the backend's LLM parser (ParsedAnswer)
   * for the current question; loops back on needs_clarification without
   * advancing (tracking retries via clarification_attempts), reroutes the value to
   * redirect_key if the user answered a different question, treats gave_up as
   * an unanswered/optional-skip, otherwise records the parsed value (+ unit)
   * and moves to the next question. */
  async function submitFreeTextAnswer(question, trimmed) {
    var userText = trimmed;
    // If we're in a clarification turn, combine the original input with the clarification
    if (state.clarificationUserInput[question.key]) {
      userText = state.clarificationUserInput[question.key] + " " + trimmed;
    }
    var payload = { question_key: question.key, user_text: userText };
    var previousValue = state.dynamicAnswers[question.key];
    if (previousValue !== undefined && previousValue !== null) {
      payload.previous_value = previousValue;
      var previousUnit = state.dynamicAnswers[unitFieldNameFor(question.key)];
      if (previousUnit !== undefined) payload.previous_unit = previousUnit;
    }
    if (state.clarificationAttempts[question.key]) {
      payload.clarification_attempts = state.clarificationAttempts[question.key];
    }

    var data;
    try {
      var res = await fetch(API_BASE_URL + "/" + state.useCaseSlug + "/answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      data = await res.json();
    } catch (err) {
      showUnreachableBackendError(function () {
        return submitFreeTextAnswer(question, trimmed);
      });
      return;
    }

    console.log("[submitFreeTextAnswer] response for", question.key, ":", data);

    if (data.needs_clarification) {
      state.clarificationAttempts[question.key] = (state.clarificationAttempts[question.key] || 0) + 1;
      // Store the user's original input so we can combine it with their clarification on next attempt
      if (!state.clarificationUserInput[question.key]) {
        state.clarificationUserInput[question.key] = trimmed;
      }
      if (data.previous_value !== undefined) {
        state.dynamicAnswers[question.key] = data.previous_value;
        if (data.previous_unit !== undefined) {
          state.dynamicAnswers[unitFieldNameFor(question.key)] = data.previous_unit;
        }
      }
      addBotMessage(data.clarification_question || "Could you clarify that?");
      state.awaitingKind = "dynamic-input";
      render();
      return;
    }
    delete state.clarificationAttempts[question.key];

    if (data.gave_up) {
      handleUnansweredQuestion(question);
      return;
    }

    if (data.redirect_key) {
      state.dynamicAnswers[data.redirect_key] = data.value;
      if (data.unit) state.dynamicAnswers[unitFieldNameFor(data.redirect_key)] = data.unit;
      state.currentQuestion = null;
      await fetchNextQuestion();
      return;
    }

    if (data.skipped) {
      handleUnansweredQuestion(question);
      return;
    }

    state.dynamicAnswers[question.key] = data.value;
    var unit = data.unit || question.unit;
    if (unit) state.dynamicAnswers[unitFieldNameFor(question.key)] = unit;

    console.log("[submitFreeTextAnswer] accepted:", question.key, "=", data.value, unit ? "(unit: " + unit + ")" : "");
    console.log("[submitFreeTextAnswer] state.dynamicAnswers:", state.dynamicAnswers);

    // Clear clarification tracking now that this question is resolved
    delete state.clarificationUserInput[question.key];
    delete state.clarificationAttempts[question.key];

    state.currentQuestion = null;
    await fetchNextQuestion(data.confirmation_message);
  }

  function submitDynamicAnswer(rawValue) {
    var question = state.currentQuestion;
    if (!question) return;
    var trimmed = rawValue.trim();
    if (!trimmed) return;

    addUserMessage(trimmed);
    state.inputError = null;
    state.awaitingKind = "loading";
    render();

    if (CATEGORY_QUESTION_KEYS.indexOf(question.key) !== -1) {
      return submitCategoryAnswer(question, trimmed);
    }
    return submitFreeTextAnswer(question, trimmed);
  }

  /** Advances through fixed steps, stopping at the next question, a dynamic
   * question-flow kickoff, or the end. */
  function advance(fromStep, answerValue) {
    var nextId = fromStep.next ? fromStep.next(answerValue, state.answers) : null;
    if (!nextId) {
      state.awaitingKind = "final";
      return null;
    }
    if (nextId.indexOf("__dynamic__") === 0) {
      state.useCaseSlug = nextId.slice("__dynamic__".length);
      state.dynamicAnswers = {};
      state.clarificationAttempts = {};
      state.clarificationUserInput = {};
      state.currentQuestion = null;
      return fetchNextQuestion(); // returns a Promise
    }
    var nextStep = getStep(nextId);
    addStepMessages(nextStep, state.answers);
    state.currentStepId = nextStep.id;
    state.awaitingKind = nextStep.kind;
    state.inputError = null;

    // If this step is final but has a next function, continue to the next step
    if (nextStep.kind === "final" && nextStep.next) {
      var followUpId = nextStep.next(answerValue, state.answers);
      if (followUpId) {
        var followUpStep = getStep(followUpId);
        addStepMessages(followUpStep, state.answers);
        state.currentStepId = followUpStep.id;
        state.awaitingKind = followUpStep.kind;
      }
    }
    return null;
  }

  function submitOption(value, label) {
    if (state.virtualOptions) return; // handled via chip's own onSelect
    var step = getStep(state.currentStepId);
    if (step.kind !== "options") return;
    state.answers[step.id] = value;
    addUserMessage(label);
    advance(step, value);
    render();
  }

  function submitText(rawValue) {
    var step = getStep(state.currentStepId);
    if (step.kind !== "input") return;
    var trimmed = rawValue.trim();
    if (!trimmed) return;
    var error = step.validate ? step.validate(trimmed) : null;
    if (error) {
      addUserMessage(trimmed);
      addBotMessage(error);
      render();
      return;
    }
    state.answers[step.id] = trimmed;
    addUserMessage(trimmed);
    advance(step, trimmed);
    render();
  }

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------
  var el = {};

  function mascotImage() {
    var img = document.createElement("img");
    img.className = "mascot";
    img.src = "./logo.png";
    img.alt = "Wilo Pumps Selection Chatbot logo";
    return img;
  }

  function buildWelcomeCard() {
    var card = document.createElement("div");
    card.className = "welcome-card";

    var textWrap = document.createElement("div");
    textWrap.className = "welcome-text";

    var greet = document.createElement("p");
    greet.className = "greet";
    greet.textContent = "👋 Hi! I'm your";

    var brand = document.createElement("p");
    brand.className = "brand-name";
    brand.textContent = "Wilo Pumps Selection Chatbot";

    var line1 = document.createElement("p");
    line1.textContent = "I'll help you find the right pump for your application.";

    var line2 = document.createElement("p");
    line2.textContent = "Let's get started.";

    var time = document.createElement("div");
    time.className = "time";
    time.textContent = timestamp();

    textWrap.appendChild(greet);
    textWrap.appendChild(brand);
    textWrap.appendChild(line1);
    textWrap.appendChild(line2);
    textWrap.appendChild(time);

    card.appendChild(textWrap);
    card.appendChild(mascotImage());
    return card;
  }

  var PUMP_ICON_SVG =
    '<svg viewBox="0 0 64 64" width="40" height="40" aria-hidden="true">' +
    '<rect x="4" y="24" width="28" height="18" rx="4" fill="#3f8f7f" />' +
    '<rect x="10" y="30" width="6" height="6" fill="#e3f3ef" />' +
    '<rect x="20" y="30" width="6" height="6" fill="#e3f3ef" />' +
    '<circle cx="44" cy="30" r="13" fill="#2f6f62" />' +
    '<circle cx="44" cy="30" r="7" fill="#e3f3ef" />' +
    '<rect x="42" y="10" width="4" height="14" fill="#2f6f62" />' +
    '<rect x="2" y="42" width="60" height="4" rx="2" fill="#2f6f62" />' +
    "</svg>";

  var LIST_ICON_SVG =
    '<svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" style="vertical-align:-2px;margin-right:6px;">' +
    '<circle cx="2.5" cy="4" r="1.5" fill="#fff" />' +
    '<circle cx="2.5" cy="10" r="1.5" fill="#fff" />' +
    '<circle cx="2.5" cy="16" r="1.5" fill="#fff" />' +
    '<rect x="6" y="3" width="13" height="2" rx="1" fill="#fff" />' +
    '<rect x="6" y="9" width="13" height="2" rx="1" fill="#fff" />' +
    '<rect x="6" y="15" width="13" height="2" rx="1" fill="#fff" />' +
    "</svg>";

  function formatPhaseValue(raw) {
    var match = String(raw).match(/(\d+)/);
    return match ? match[1] + " Phase" : prettifyKey(String(raw));
  }

  function appendUnitIfPlainNumber(value, unit) {
    var text = formatDetailValue(value);
    return /^-?[\d.,]+$/.test(String(value)) ? text + " " + unit : text;
  }

  // Backend "details" fields are internal/engineering data (spec sheet names,
  // matching-target values, etc). Only these customer-relevant fields are
  // shown on the recommendation card; anything else is left out on purpose.
  var DETAIL_DISPLAY_RULES = [
    {
      test: function (key) {
        return /flow/i.test(key);
      },
      label: "Flow",
      format: formatDetailValue,
    },
    {
      test: function (key) {
        return /head/i.test(key) && !/target/i.test(key);
      },
      label: "Head",
      format: function (value) {
        return appendUnitIfPlainNumber(value, "m");
      },
    },
    {
      test: function (key) {
        return /^hp$/i.test(key) || /motor/i.test(key) || /power/i.test(key);
      },
      label: "Motor Power",
      format: function (value) {
        return appendUnitIfPlainNumber(value, "HP");
      },
    },
    {
      test: function (key) {
        return /phase/i.test(key);
      },
      label: "Phase",
      format: formatPhaseValue,
    },
    {
      test: function (key) {
        return /fill/i.test(key) && /time/i.test(key);
      },
      label: "Fill Time",
      format: function (value) {
        return appendUnitIfPlainNumber(value, "min");
      },
    },
  ];

  // The "View Pump Details" modal shows more than the summary card: every
  // detail field the backend returns except internal ones (spec sheet name,
  // the raw curve array, which gets its own chart instead of a text row).
  var TECHNICAL_DETAIL_BLACKLIST = ["sheet", "performance_curve"];
  var TECHNICAL_DETAIL_RULES = DETAIL_DISPLAY_RULES.concat([
    {
      test: function (key) {
        return /target/i.test(key) && /head/i.test(key);
      },
      label: "Target Head",
      format: function (value) {
        return appendUnitIfPlainNumber(value, "m");
      },
    },
  ]);

  function buildTechnicalPointsRows(recommendation) {
    var details = recommendation.details || {};
    var rows = [];
    if (recommendation.art_no != null) {
      rows.push({ label: "Article No.", value: String(recommendation.art_no) });
    }
    Object.keys(details).forEach(function (key) {
      if (TECHNICAL_DETAIL_BLACKLIST.indexOf(key) !== -1) return;
      var value = details[key];
      if (value == null || value === "") return;
      var rule = TECHNICAL_DETAIL_RULES.find(function (r) {
        return r.test(key);
      });
      rows.push({
        label: rule ? rule.label : prettifyKey(key),
        value: rule ? rule.format(value) : formatDetailValue(value),
      });
    });
    return rows;
  }

  /** Renders the backend's real {flow, head} performance curve as an SVG line
   * chart, with the pump's actual matched duty point marked on the curve. */
  function buildPerformanceCurveSVG(curvePoints, matchedHead, flowAtMatch) {
    var width = 300;
    var height = 190;
    var padding = 32;

    var points = curvePoints
      .filter(function (p) {
        return typeof p.flow === "number" && typeof p.head === "number";
      })
      .slice()
      .sort(function (a, b) {
        return a.flow - b.flow;
      });
    if (!points.length) return null;

    var maxFlow = Math.max.apply(
      null,
      points.map(function (p) {
        return p.flow;
      })
    );
    var maxHead = Math.max.apply(
      null,
      points.map(function (p) {
        return p.head;
      })
    );
    if (!maxFlow || !maxHead) return null;

    function xFor(flow) {
      return padding + (flow / maxFlow) * (width - padding * 2);
    }
    function yFor(head) {
      return height - padding - (head / maxHead) * (height - padding * 2);
    }

    var pathD = points
      .map(function (p, i) {
        return (i === 0 ? "M" : "L") + xFor(p.flow).toFixed(1) + "," + yFor(p.head).toFixed(1);
      })
      .join(" ");

    var markup =
      '<svg viewBox="0 0 ' +
      width +
      " " +
      height +
      '" width="100%" height="190" role="img" aria-label="Pump performance curve">' +
      '<line x1="' +
      padding +
      '" y1="' +
      padding / 2 +
      '" x2="' +
      padding +
      '" y2="' +
      (height - padding) +
      '" stroke="#e4e7e6" stroke-width="1" />' +
      '<line x1="' +
      padding +
      '" y1="' +
      (height - padding) +
      '" x2="' +
      (width - padding / 2) +
      '" y2="' +
      (height - padding) +
      '" stroke="#e4e7e6" stroke-width="1" />' +
      '<path d="' +
      pathD +
      '" fill="none" stroke="#3f8f7f" stroke-width="2.5" stroke-linejoin="round" />';

    if (typeof flowAtMatch === "number" && typeof matchedHead === "number") {
      var dotX = xFor(flowAtMatch);
      var dotY = yFor(matchedHead);
      markup += '<circle cx="' + dotX.toFixed(1) + '" cy="' + dotY.toFixed(1) + '" r="5" fill="#2f6f62" stroke="#fff" stroke-width="2" />';

      var tipLines = [formatDetailValue(flowAtMatch), formatDetailValue(matchedHead) + " m"];
      var tipW = 56;
      var tipH = 34;
      var tipX = Math.min(Math.max(dotX - tipW / 2, padding), width - padding / 2 - tipW);
      var tipY = Math.max(dotY - tipH - 10, 2);
      markup +=
        '<rect x="' +
        tipX.toFixed(1) +
        '" y="' +
        tipY.toFixed(1) +
        '" width="' +
        tipW +
        '" height="' +
        tipH +
        '" rx="6" fill="#fff" stroke="#e4e7e6" stroke-width="1" />' +
        '<text x="' +
        (tipX + tipW / 2).toFixed(1) +
        '" y="' +
        (tipY + 14).toFixed(1) +
        '" text-anchor="middle" font-size="10" font-weight="700" fill="#1c2a28">' +
        tipLines[0] +
        "</text>" +
        '<text x="' +
        (tipX + tipW / 2).toFixed(1) +
        '" y="' +
        (tipY + 26).toFixed(1) +
        '" text-anchor="middle" font-size="10" font-weight="700" fill="#1c2a28">' +
        tipLines[1] +
        "</text>";
    }

    markup +=
      '<text x="' +
      width / 2 +
      '" y="' +
      (height - 6) +
      '" text-anchor="middle" font-size="10" fill="#6b7a78">Flow</text>' +
      '<text x="10" y="' +
      height / 2 +
      '" text-anchor="middle" font-size="10" fill="#6b7a78" transform="rotate(-90 10 ' +
      height / 2 +
      ')">Head</text>' +
      "</svg>";

    return markup;
  }

  // A details field naming the pump's category (e.g. "End-Suction Centrifugal
  // Pump") is shown as a subtitle under the model name when the backend
  // provides one; nothing is fabricated when it doesn't.
  function findPumpSubtitle(details) {
    var key = Object.keys(details).find(function (k) {
      return /type|category|series/i.test(k);
    });
    return key ? details[key] : null;
  }

  var PD_TABS = ["Overview", "Performance", "Dimensions", "Docs"];

  function openPumpDetailsModal(recommendation) {
    el.detailsBody.innerHTML = "";
    el.detailsFav.setAttribute("aria-pressed", "false");

    var details = recommendation.details || {};
    var subtitle = findPumpSubtitle(details);

    var modelRow = document.createElement("div");
    modelRow.className = "pd-model-row";
    var modelName = document.createElement("div");
    modelName.className = "pd-model-name";
    modelName.textContent = recommendation.model_name || "Unknown model";
    modelRow.appendChild(modelName);
    el.detailsBody.appendChild(modelRow);

    if (subtitle) {
      var subtitleEl = document.createElement("div");
      subtitleEl.className = "pd-subtitle";
      subtitleEl.textContent = subtitle;
      el.detailsBody.appendChild(subtitleEl);
    }

    var tabs = document.createElement("div");
    tabs.className = "pd-tabs";
    PD_TABS.forEach(function (label, i) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pd-tab" + (i === 0 ? " active" : "");
      btn.textContent = label;
      if (i !== 0) btn.disabled = true;
      tabs.appendChild(btn);
    });
    el.detailsBody.appendChild(tabs);

    var panel = document.createElement("div");
    panel.className = "pd-panel";

    var curveMarkup =
      details.performance_curve && details.performance_curve.length
        ? buildPerformanceCurveSVG(details.performance_curve, details.matched_head, details.flow)
        : null;

    if (curveMarkup) {
      var panelTitle = document.createElement("div");
      panelTitle.className = "pd-panel-title";
      panelTitle.textContent = "Performance Curve";
      panel.appendChild(panelTitle);

      var chartWrap = document.createElement("div");
      chartWrap.innerHTML = curveMarkup;
      panel.appendChild(chartWrap);

      var legend = document.createElement("div");
      legend.className = "chart-legend";
      legend.innerHTML = '<span class="dot"></span> Your matched operating point';
      panel.appendChild(legend);
    }
    el.detailsBody.appendChild(panel);

    var techTitle = document.createElement("div");
    techTitle.className = "tech-points-title";
    techTitle.textContent = "Technical Data";
    el.detailsBody.appendChild(techTitle);

    var table = document.createElement("div");
    table.className = "specs-table";
    buildTechnicalPointsRows(recommendation).forEach(function (row) {
      var line = document.createElement("div");
      line.className = "spec-line";
      var k = document.createElement("span");
      k.textContent = row.label;
      var v = document.createElement("span");
      v.textContent = row.value;
      line.appendChild(k);
      line.appendChild(v);
      table.appendChild(line);
    });
    el.detailsBody.appendChild(table);

    el.detailsBackdrop.hidden = false;
  }

  function closePumpDetailsModal() {
    el.detailsBackdrop.hidden = true;
  }

  function buildRecommendationCard(recommendation, tierLabel) {
    var card = document.createElement("div");
    card.className = "card";

    var details = recommendation.details || {};

    var banner = document.createElement("div");
    banner.className = "card-banner";
    banner.appendChild(document.createTextNode(tierLabel));

    var body = document.createElement("div");
    body.className = "card-body";

    var catLabel = document.createElement("div");
    catLabel.className = "cat-label";
    catLabel.textContent = "Model";

    var modelName = document.createElement("div");
    modelName.className = "model-name";
    modelName.textContent = recommendation.model_name || "Unknown model";

    var specs = document.createElement("div");
    specs.className = "specs";

    var icon = document.createElement("div");
    icon.className = "pump-icon";
    icon.innerHTML = PUMP_ICON_SVG;

    var table = document.createElement("div");
    table.className = "specs-table";
    DETAIL_DISPLAY_RULES.forEach(function (rule) {
      var matchedKey = Object.keys(details).find(rule.test);
      if (matchedKey == null || details[matchedKey] == null || details[matchedKey] === "") return;
      var line = document.createElement("div");
      line.className = "spec-line";
      var k = document.createElement("span");
      k.textContent = rule.label;
      var v = document.createElement("span");
      v.textContent = rule.format(details[matchedKey]);
      line.appendChild(k);
      line.appendChild(v);
      table.appendChild(line);
    });
    if (recommendation.art_no != null) {
      var artLine = document.createElement("div");
      artLine.className = "spec-line";
      var artKey = document.createElement("span");
      artKey.textContent = "Article No.";
      var artVal = document.createElement("span");
      artVal.textContent = String(recommendation.art_no);
      artLine.appendChild(artKey);
      artLine.appendChild(artVal);
      table.appendChild(artLine);
    }

    specs.appendChild(icon);
    specs.appendChild(table);

    var viewBtn = document.createElement("button");
    viewBtn.type = "button";
    viewBtn.className = "view-btn";
    viewBtn.innerHTML = LIST_ICON_SVG + "View Pump Details";
    viewBtn.addEventListener("click", function () {
      openPumpDetailsModal(recommendation);
    });

    var selectBtn = document.createElement("button");
    selectBtn.type = "button";
    selectBtn.className = "view-btn select-btn";
    var isSelected = state.selectedPump && state.selectedPump.recommendation.model_name === recommendation.model_name;
    selectBtn.textContent = isSelected ? "✓ Selected" : "Select";
    if (isSelected) selectBtn.classList.add("selected");
    selectBtn.addEventListener("click", function () {
      state.selectedPump = { recommendation: recommendation, tierLabel: tierLabel };
      addUserMessage("Select");
      addBotMessage("Great! You've selected " + recommendation.model_name + ". Now, let me collect your details to connect you with a dealer.");
      jumpToStep("lead-contact");
      render();
    });

    body.appendChild(catLabel);
    body.appendChild(modelName);
    body.appendChild(specs);
    body.appendChild(viewBtn);
    body.appendChild(selectBtn);

    card.appendChild(banner);
    card.appendChild(body);
    return card;
  }

  function buildRecommendationRow(message) {
    var row = document.createElement("div");
    row.className = "row bot";
    row.style.maxWidth = "100%";
    row.style.gap = "10px";
    row.appendChild(buildRecommendationCard(message.recommendation, "Best Fit"));

    var alternatives = message.tiedAlternatives || [];
    if (alternatives.length) {
      var tag = document.createElement("div");
      tag.className = "section-tag";
      tag.textContent = "Other similar options";
      row.appendChild(tag);
      alternatives.forEach(function (alt) {
        if (alt && typeof alt === "object" && alt.model_name) {
          row.appendChild(buildRecommendationCard(alt, "Alternative"));
        }
      });
    }
    return row;
  }

  function buildOptionCard(option, onClick) {
    var card = document.createElement("button");
    card.type = "button";
    card.className = "option-card";

    var icon = document.createElement("span");
    icon.className = "option-icon";
    icon.textContent = option.icon || "•";

    var text = document.createElement("span");
    text.className = "option-text";

    var title = document.createElement("span");
    title.className = "option-title";
    title.textContent = option.label;
    text.appendChild(title);

    if (option.subtitle) {
      var subtitle = document.createElement("span");
      subtitle.className = "option-subtitle";
      subtitle.textContent = option.subtitle;
      text.appendChild(subtitle);
    }

    card.appendChild(icon);
    card.appendChild(text);
    card.addEventListener("click", onClick);
    return card;
  }

  function buildMessageRow(message) {
    var row = document.createElement("div");
    row.className = "row " + message.role;

    var bubble = document.createElement("div");
    bubble.className = "bubble";
    if (message.kind === "html") {
      bubble.innerHTML = message.html;
    } else {
      bubble.textContent = message.text;
    }

    var time = document.createElement("div");
    time.className = "time";
    time.textContent = message.timestamp;

    row.appendChild(bubble);
    row.appendChild(time);
    return row;
  }

  function composerPlaceholder() {
    if (state.awaitingKind === "dynamic-input" && state.currentQuestion) {
      var q = state.currentQuestion;
      var hint = q.unit ? " in " + q.unit : "";
      return "Enter a value" + hint + (q.optional ? ", or 'skip'" : "");
    }
    if (state.awaitingKind === "input") return getStep(state.currentStepId).placeholder;
    if (state.awaitingKind === "loading") return "Checking...";
    return "Choose an option above";
  }

  function render() {
    el.thread.innerHTML = "";
    state.messages.forEach(function (message) {
      if (message.kind === "welcome") {
        el.thread.appendChild(buildWelcomeCard());
        return;
      }
      if (message.kind === "recommendation") {
        el.thread.appendChild(buildRecommendationRow(message));
        return;
      }
      el.thread.appendChild(buildMessageRow(message));
    });

    if (state.virtualOptions) {
      var vOptions = document.createElement("div");
      vOptions.className = "option-list";
      state.virtualOptions.forEach(function (option) {
        vOptions.appendChild(
          buildOptionCard(option, function () {
            state.virtualOptions = null;
            option.onSelect();
          })
        );
      });
      el.thread.appendChild(vOptions);
    } else if (state.awaitingKind === "options") {
      var step = getStep(state.currentStepId);
      var options = document.createElement("div");
      options.className = "option-list";
      step.options.forEach(function (option) {
        options.appendChild(
          buildOptionCard(option, function () {
            submitOption(option.value, option.label);
          })
        );
      });
      el.thread.appendChild(options);
    }

    var isInputStep =
      (state.awaitingKind === "input" || state.awaitingKind === "dynamic-input") &&
      !state.virtualOptions;
    el.composerInput.disabled = !isInputStep;
    el.composerInput.placeholder = composerPlaceholder();
    if (!isInputStep) el.composerInput.value = "";
    el.sendBtn.disabled = !isInputStep || !el.composerInput.value.trim();

    if (state.inputError) {
      el.inputError.textContent = state.inputError;
      el.inputError.hidden = false;
    } else {
      el.inputError.hidden = true;
    }

    el.thread.scrollTop = el.thread.scrollHeight;
  }

  function handleSend() {
    if (el.composerInput.disabled) return;
    var value = el.composerInput.value;
    if (!value.trim()) return;
    el.composerInput.value = "";
    if (state.awaitingKind === "dynamic-input") {
      submitDynamicAnswer(value);
    } else {
      submitText(value);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    el.thread = document.getElementById("thread");
    el.composerInput = document.getElementById("composer-input");
    el.sendBtn = document.getElementById("send-btn");
    el.inputError = document.getElementById("input-error");
    el.detailsBackdrop = document.getElementById("details-backdrop");
    el.detailsBody = document.getElementById("details-body");
    el.detailsClose = document.getElementById("details-close");
    el.detailsFav = document.getElementById("details-fav");
    el.menuBtn = document.getElementById("menu-btn");
    el.menuDropdown = document.getElementById("menu-dropdown");
    el.menuRestart = document.getElementById("menu-restart");
    el.menuContinue = document.getElementById("menu-continue");

    el.sendBtn.addEventListener("click", handleSend);
    el.composerInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") handleSend();
    });
    el.composerInput.addEventListener("input", function () {
      el.sendBtn.disabled = el.composerInput.disabled || !el.composerInput.value.trim();
    });

    el.detailsClose.addEventListener("click", closePumpDetailsModal);
    el.detailsFav.addEventListener("click", function () {
      var pressed = el.detailsFav.getAttribute("aria-pressed") === "true";
      el.detailsFav.setAttribute("aria-pressed", pressed ? "false" : "true");
    });
    el.detailsBackdrop.addEventListener("click", function (event) {
      if (event.target === el.detailsBackdrop) closePumpDetailsModal();
    });

    function closeMenu() {
      el.menuDropdown.hidden = true;
      el.menuBtn.setAttribute("aria-expanded", "false");
    }
    el.menuBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      var wasHidden = el.menuDropdown.hidden;
      el.menuDropdown.hidden = !wasHidden;
      el.menuBtn.setAttribute("aria-expanded", wasHidden ? "true" : "false");
    });
    el.menuRestart.addEventListener("click", function () {
      closeMenu();
      restartConversation();
    });
    el.menuContinue.addEventListener("click", closeMenu);
    document.addEventListener("click", function (event) {
      if (!el.menuDropdown.hidden && !el.menuDropdown.contains(event.target)) closeMenu();
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !el.detailsBackdrop.hidden) closePumpDetailsModal();
      if (event.key === "Escape" && !el.menuDropdown.hidden) closeMenu();
    });

    initConversation();
    render();
  });
})();
