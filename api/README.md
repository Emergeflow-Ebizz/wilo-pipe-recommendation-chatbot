# Pump Chatbot

Chatbot backend serving 5 independent pump-selection use cases. A UI lets the
user pick one of the 5 up front; the backend runs that use case's fixed
question sequence and rule engine to recommend a pump. The LLM is only used to
parse free-text answers into structured values, not to choose the pump.

## Data

`json_new/` holds every model-family catalog file (Challenger, WBW-3,
WBW-4 Prathak, etc.) in one shared folder. Use cases reference these files by
name via their own `sheet_map.py` rather than owning private copies.

## Structure

- `app/common/` - shared catalog loading (`catalog_loader.load_sheet`), unit conversions
  (`units.py`), LLM parsing, session state
- `app/use_cases/<slug>/` - each use case's own `sheet_map.py` (selector value to
  `json_new/` filename), `questions.py` (fixed question sequence), and `rules.py`
  (deterministic pump-selection rule engine)
- `tests/` - unit tests for shared code and per-use-case rule engines

## Use cases

| Slug | Status |
|---|---|
| `water_transfer` | Implemented |
| `tank_filling` | implemented |
| `pressure_boosting` | Implemented |
| `dewatering` | Implemented |
| `hot_water_circulation` | Not yet implemented |

## Running

```
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```
