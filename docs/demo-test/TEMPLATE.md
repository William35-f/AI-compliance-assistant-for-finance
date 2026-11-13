# ReguLens demo test: blank template

Copy this file for each test round. One row per question; put screenshots in `screenshots/`
named `qNN-short-name.png`.

**Round:** _date_ · **Tester:** _name_ · **Model:** _e.g. gemini-3.5-flash-lite_ · **Theme / screen:** _light, 1440 px_

## How to judge each question

| Field | What to write |
|---|---|
| Expected | `Answer` if the indexed MAS documents cover it, `Refuse` if they don't |
| Got | `Answered` or `Refused` |
| Behaviour | Pass if Got matches Expected |
| Correct | For answers: does the answer match the highlighted source paragraph? Yes / Partly / No |
| Citations | Do the highlighted paragraphs support every point? Yes / Partly / No. Note any "Closest match" flags |
| Time | The response time shown on the page (first ask, not a cached repeat) |
| Notes | Anything odd: wrong page, missing detail, slow, error message |

## Results

| # | Question | Expected | Got | Behaviour | Correct | Citations | Time | Screenshot | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 01 |  | Answer |  |  |  |  |  | [q01](screenshots/) |  |
| 02 |  | Answer |  |  |  |  |  | [q02](screenshots/) |  |
| 03 |  | Refuse |  |  |  |  |  | [q03](screenshots/) |  |

## Summary

- Behaviour pass rate: _x of n_
- Answers judged correct: _x of n_
- Wrong refusals (should have answered): _list_
- Wrong answers (should have refused): _list_
- Issues to fix: _list_
