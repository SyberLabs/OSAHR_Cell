# RISE external validation — contractor brief and pilot protocol

Status: **ready for a quote after budget/channel approval; not sent or awarded**.
This is a study scope, not a signed contract or legal terms. Commercial terms,
privacy arrangements and a named researcher must be approved before recruitment.
Keep proposals, personal details and recordings out of this public repository.

## Hire for the decision, not for a positive testimonial

Engage one independent human usability researcher for a small fixed-fee pilot:
recruit and moderate three 45-minute sessions, compare RISE with an ordinary
reading workflow, and deliver a defensible continue/change/stop recommendation.
The researcher must not be a RISE contributor or financially rewarded for a
favorable product finding. Software test automation is not a substitute.

Proposed audience to confirm before recruitment: adults who read long-form text
at least weekly and can describe a recent interruption or difficulty continuing.
Exclude team members, close associates, prior RISE users and professional
familiarity with the current design. Do not recruit based on a promise that RISE
improves attention, wellbeing or comprehension. This is non-clinical usability
research; no health data or efficacy claims are needed.

## Procurement sequence

1. Director approves all-in spending cap, currency, contracting channel and
   intended audience. Confirm who can award and pay the contract.
2. Request a fixed-fee quote from an independent moderator with one relevant
   work sample showing how a negative observation changed a product decision.
   Ask for availability, exact recruitment method, consent/recording practice,
   analysis sample and how they prevent leading participants.
3. Obtain a named researcher and itemized scope: facilitation/recruiting/analysis,
   participant incentives, platform fees, taxes and replacement/no-show policy.
   No recurring subscription, deposit or work begins without approval.
4. Approve the screener, neutral script, test build and quote. Conduct one session
   first as a procedural checkpoint; stop and fix access/privacy/session failures
   before running the remaining two. Do not exclude valid negative observations.
5. Pay for valid work and participation regardless of product outcome. Missing
   contractual deliverables can require correction; dislike of RISE cannot.

Publicly checked sourcing options (2026-09-05), not endorsements or confirmed
availability/prices:

| Route | What is actually offered | What still needs confirmation |
|---|---|---|
| [Cardinal Peak usability services](https://www.cardinalpeak.com/product-design-services/user-experience-design-services/usability-testing-services) | Provider advertises managed usability testing including moderated research | Will they accept a three-session pilot, named moderator, fixed fee and this independence brief? |
| Independent moderator + [User Interviews Recruit](https://www.userinterviews.com/recruit) | Participant recruiting, **not evidence that a moderator is included** | Hire the researcher separately; quote platform costs and incentives separately |

Prefer a small independent engagement if it meets the scope and spending cap;
do not buy an enterprise research platform to run three sessions. No individual
has been vetted, no provider has been contacted and no reservation has been made.

## Pre-session safety and build gate

- Freeze the RISE commit, deployment URL, browser/device versions and current
  asset/voice manifest hash. Recheck the actual build; a past green CI result
  is not a current release certification.
- Use supplied public-domain/licensed text. No personal documents, accounts,
  cloud drives or credentials. Do not expose unreleased confidential material.
- Verify the selected entry/read/exit corridor works on the study devices and
  review applicable privacy/data-clear behavior before participants use it.
  Stop if unexpected personal-data collection or disclosure is observed.
- Explain voluntary participation, withdrawal, what is recorded, who sees it
  and the agreed retention/deletion period. Recording requires separate opt-in;
  choose a note-only alternative when practical. Do not promise a retention
  period until the provider and director have agreed it.
- This study does not certify the full device matrix, every audio phrase,
  accessibility, security or privacy. Do not mark unrelated release gates done.

## Session script (45 minutes; moderator pilots timing)

1. **5 min: recent behavior.** “Tell me about the last time you tried to continue
   reading something and it did not go as you wanted. What did you actually do?”
   Capture current tools and consequences before mentioning RISE's benefits.
2. **12 min: first workflow.** Start from a clean entry state. “Use this text as
   you normally would. Begin reading, stop when asked, then return and continue.”
   Do not name controls, explain the interface or complete the task for them.
   After two minutes stuck on a step, record failure and assistance, then offer
   the minimum prompt needed to continue. Stop immediately on discomfort.
3. **12 min: second workflow.** Repeat with the other tool and a different,
   similar-length/difficulty text. Compare RISE with a plain browser reader or
   the participant's ordinary tool if available without disclosing private data.
   Alternate order across participants; record the inevitable 2:1 imbalance
   with n=3. Freeze task and text pairings before sessions.
4. **10 min: neutral comparison.** “What, if anything, would make you choose one
   next time? What would you lose by switching? Show me where it got in your way.”
   Ask for a concrete repeat situation; do not suggest a benefit or ask for praise.
5. **6 min: debrief and data handling.** Confirm participation/incentive, consent
   choices and unresolved observations. State clearly that the prototype is
   being tested, not the participant.

Measure unassisted start, interrupted-task return, wrong turns, assistance count,
time to first usable reading state, ability to exit, discomfort and stated reason
to switch/not switch. Keep observed behavior separate from interpretation.
Times and preferences from three people are descriptive, not reliable population
estimates. Do not infer learning gains from a tiny comprehension exercise.

## Deliverables / acceptance

- Approved screener/script and exact test-build record.
- Three de-identified session records, including failed tasks and timestamps;
  device/browser and tool order; no names or raw recordings in public GitHub.
- Per-task matrix: attempted, unassisted success, assisted success, failure,
  timing, evidence pointer and severity. Preserve all valid negative sessions.
- Ranked findings with reproduction steps, confidence and smallest corrective
  change. Explicitly distinguish usability friction from absence of a need.
- Two-page synthesis answering: is the recurring job real, does RISE help relative
  to the existing workflow, what failed, what should be deleted, and what evidence
  is still missing? Include a recommendation even if that recommendation is stop.
- Confirmation of the agreed secure handoff and retention/deletion process.

Proposed diagnostic decision rule to approve before sessions: if fewer than two
of three complete the core corridor unassisted, revise that corridor before
adding features. If fewer than two identify a concrete recent repeat-use situation
where RISE is preferable, pause feature expansion and revisit the value hypothesis.
Any serious privacy issue pauses the study. Passing these thresholds licenses
another small test, **not** an effectiveness, retention or market-fit claim.

Optional follow-up is a separately approved seven-day return-use observation;
stated willingness to return is not actual retention. Do not condition incentives
on using RISE or on reporting a positive result.
