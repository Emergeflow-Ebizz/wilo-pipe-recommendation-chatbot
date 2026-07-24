# Wilo Pump Selection Chatbot - Frontend

A static, vanilla JS/CSS/HTML chat widget that walks a user through selecting
a Wilo pump for their application. It talks to the Wilo pump-selection
backend (FastAPI service, hosted separately) for use-case questions, answer
parsing, and pump recommendations.

## Structure

- `index.html` - page shell and chat widget markup
- `app.js` - conversation flow (application/use-case picker, lead-capture
  steps, thank-you sign-off) and all calls to the backend API
- `style.css` - chat widget styling
- `favicon.svg`, `WILO_Logo_2013.svg`, `mascot.jpeg` - static assets

## Backend

`app.js` calls a backend at `API_BASE_URL` (currently hardcoded to
`http://127.0.0.1:8000`) for:

- `/{use_case_slug}/next_question`, `/answer_category`, `/answer` - drives the
  use case's question sequence
- `/{use_case_slug}/recommend` - runs the rule engine and returns a
  recommended pump
- `/explain_model` - LLM-generated explanation for a recommended model

The backend source lives in a separate repo
([`Emergeflow-Ebizz/wilo-pipe-recommendation-chatbot`](https://github.com/Emergeflow-Ebizz/wilo-pipe-recommendation-chatbot)),
which also serves this same frontend under its `static/` folder on Vercel.

## Running locally

This is a static site with no build step. Serve the folder and open it in a
browser, e.g.:

```
python3 -m http.server 5500
```

Then visit `http://localhost:5500`. Point `API_BASE_URL` in `app.js` at a
running instance of the backend.
