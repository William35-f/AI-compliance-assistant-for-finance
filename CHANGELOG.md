# Changelog

## v1.0.0 (2026-11-13)

First release.

**Ask (question answering with citations)**
- Answers about 10 MAS guidelines and notices, as numbered points, each citing a document, page
  and verbatim quote that the code checks against the source; unsupported claims are dropped.
- Refuses when the documents don't cover the question (similarity threshold, then the model's
  own "not answerable" flag).
- One-line summary heading, rejected if it contains a number the cited claims don't.
- Keeps the source's obligation strength: "must" becomes "should" when the cited guideline says
  "should".
- The cited page opens beside the answer, with the cited paragraph highlighted.

**Extract and Risk check**
- Revenue, net profit, total debt and key risks from SGX annual reports; units converted and each
  number verified on its statement page.
- Risk check page: links disclosed risks to MAS guideline passages and flags ones for human review.

**Interface**
- Light and dark themes, phone layout with a bottom navigation bar, 44 px touch targets, WCAG AA
  contrast.

**Measured** (90 questions, `gemini-3.5-flash-lite`, run `20261113T081952Z`)
- Retrieval hit@5 0.950 (baseline 0.800), MRR 0.819
- Answer correctness 0.887, citation accuracy 0.987, out-of-scope refusal 1.000, false refusals
  3 of 80
- Median latency 6.3 s, about $0.0003 per question at paid-tier prices
- Extraction: 15 of 15 numbers correct
- Demo test in the real UI: 32 of 32 questions answered or refused correctly

**Known limitations**
- Not deployed yet (see DEPLOY.md); runs locally.
- Gemini's free tier can be slow or overloaded at busy times.
- Not legal or regulatory advice.
