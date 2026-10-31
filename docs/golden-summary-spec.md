# Golden summary spec (v1)

What a "golden summary" is in Klaro, and the rules every one of them follows.

## What it is

Corporate bid teams do not read a 100-page RFP end to end before deciding to bid. A proposal or bid
manager first produces a short **RFP summary** (also called a bid brief or bid qualification summary),
and the go/no-go decision is made from it. That summary answers six questions:

1. What is being bought, and by whom?
2. Can we qualify at all? (pass/fail eligibility)
3. When is everything due?
4. How will bids be scored?
5. What will it cost us to bid and to deliver? (EMD, security, penalties, payment terms)
6. What could hurt us? (unusual liability, tight timelines, ambiguity)

A golden summary is that document, written to a fixed standard, with every point traceable to a page.
It is the reference Klaro's output is trained toward and measured against.

Note on naming: in industry "executive summary" usually means the pitch section a vendor writes in
its own proposal. Klaro's output is the bidder-side RFP summary. Keep calling the app output
"executive summary" if the codebase does, but describe it as an RFP summary in the report.

## Sections

The golden summary uses the same sections as the app's summary schema
(`ExecutiveSummaryOutput`). Conceptually they are:

| # | Section | What goes in | What stays out | Limit |
|---|---|---|---|---|
| 1 | Overview | 2 to 4 sentences: who is buying what, why, contract length, location. Reference number if present | Marketing language, background history | 80 words |
| 2 | Issuing organization | Exact legal name of the buyer, department, tender/reference number, contact office | Consultants who drafted the RFP, unless they are the contracting party | 1 to 3 lines |
| 3 | Scope | The deliverables and services, one bullet each: what, how much, where | Evaluation method, eligibility, payment | 8 bullets |
| 4 | Key requirements | The most important mandatory technical and functional requirements. Pass/fail items first | Every minor clause. Buyer's own obligations | 10 bullets |
| 5 | Eligibility | Pre-qualification criteria: turnover, experience, similar projects, certifications, registrations, JV/consortium rules, blacklisting declarations | Scored criteria (those go to evaluation) | 8 bullets |
| 6 | Timeline | Every dated event: release, pre-bid meeting, query deadline, submission deadline, bid opening, bid validity, contract duration, delivery milestones | Undated phases | one bullet per date |
| 7 | Commercial terms | EMD/bid security, performance security, tender fee, payment terms and milestones, price basis (fixed, inclusive of taxes), liquidated damages and penalties, warranty | Scope details | 8 bullets |
| 8 | Evaluation and submission | How bids are scored (QCBS, L1, weights, minimum technical score), submission mode (portal, physical, envelopes), required forms and annexures, format rules | Eligibility thresholds | 8 bullets |
| 9 | Risks and red flags | Things a bid manager would flag: unlimited liability, very short timelines, heavy penalties, vague scope, unusual IP or data clauses, mandatory site visits, conflicts between sections | Generic risks that apply to every contract | 6 bullets |

If the app schema has different section names or a different split (for example no separate
evaluation section), map these onto the existing schema and keep the content rules. Do not change
the schema for the golden set.

## Writing rules

- **Every bullet ends with the page it came from.** Use the page number as printed by our PDF
  extractor (1-based physical page), not the page number printed in the document footer.
- **Numbers are copied exactly.** Amounts, percentages, dates, durations, quantities. No rounding,
  no currency conversion. Keep the original currency and format (Rs. 50,000/-, INR 2 crore, USD).
- **Mandatory vs desirable is preserved.** shall, must, required, mandatory, will be rejected stay
  mandatory. should, may, desirable, preferred are written as desirable.
- **Paraphrase, do not copy paragraphs.** Short and plain. One fact per bullet.
- **Absent means absent.** If the RFP does not state something, write
  "Not specified in the document". Never infer or invent a value.
- **Bidder's perspective.** Only obligations on the bidder or contractor count as requirements.
  What the buyer will do is context at most.
- **Conflicts are flagged, not resolved.** If two pages give different deadlines, list both with
  pages and put the conflict in Risks.
- **Addenda and corrigenda win** if they are part of the same PDF, and the original value is noted.

## Quality bar

A golden summary is acceptable when:

- Every bullet has a page and the fact is actually on that page.
- All dates and amounts match the PDF exactly.
- A bid manager could make a go/no-go call from it without opening the RFP.
- Nothing is in it that the RFP does not say.

## Provenance

Golden summaries are **LLM-drafted, human-verified**. Each record stores who drafted it, who
verified it, and what was changed during verification. A summary that has only passed automatic
checks is labelled `auto_checked`, not `verified`, and must not be described as human-verified.

The evaluation split (10 documents) is never used for training.
