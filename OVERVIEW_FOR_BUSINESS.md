# Conflict Screening Assistant — Business Overview

*A plain-language guide to what this system does, why it exists, and how it works.
No technical background needed.*

---

## 1. The problem

When a Deloitte SEA Tax & Transformation team wants to take on new work, someone has to
check that the firm isn't already conflicted — for example, that we don't audit the same
company we're about to advise, or that a client isn't flagged as restricted.

Today a conflicts analyst does this by hand. For every request they:

1. Read the request in DCCS (the conflict check system) and work out who the relevant
   parties are — the client, its shareholder, its ultimate parent company.
2. Search each of those names, one at a time, across **four separate databases**.
3. Open a 14-slide rulebook and apply its rules to interpret every hit they find —
   is this engagement an audit or not? Is this match too old to matter? Does this
   trigger a cross-border request to another country's Deloitte firm?
4. Hand-write a response, remembering to paste in a mandatory legal footer.

**Why this hurts:**

| Problem | Effect |
|---|---|
| Slow | A single request means dozens of manual searches |
| Repetitive | The same lookups, in the same order, every time |
| Inconsistent | Two analysts can read the same rulebook and reach different answers |
| Hard to audit | The reasoning lives in the analyst's head, not on paper |

---

## 2. The objective

Automate the search-and-interpret work, and draft the response — **while keeping the
analyst as the decision maker.**

Three principles shaped every design choice:

1. **It drafts, it does not approve.** No conclusion is ever auto-submitted. An analyst
   reviews and signs off.
2. **Every conclusion cites its rule.** If the system says "this engagement is
   Non-Assurance", it shows you the rulebook slide that says so. A human can check and
   overturn any line.
3. **Be honest about gaps.** One of the five data sources has no data available. The
   system says so on screen rather than quietly skipping it.

---

## 3. The solution

An assistant with **four specialist agents** that work a case the way a team of analysts
would — each with a defined job, each able to look things up for itself.

```
                    ┌──────────────────────────┐
   A conflict  ───► │   1. ORCHESTRATOR        │  Reads the request. Checks it's
   check request    │      "Who am I checking?" │  complete and internally consistent.
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │   2. SEARCH AGENT        │  Looks up every party in every
                    │      "What's out there?"  │  database. Finds nothing by memory.
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │   3. RULES & COMPLIANCE  │  Applies the rulebook to every hit.
                    │      "What do the rules   │  Catches contradictions. Decides
                    │       say about this?"    │  cross-border requirements.
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │   4. SYNTHESIS           │  Writes the analyst-facing answer
                    │      "What's the answer?" │  and the draft response.
                    └────────────┬─────────────┘
                                 ▼
                      Draft response + evidence
                      for the analyst to review
```

### What makes these "agents" rather than just software

Each agent is given a **job description and a set of tools**, then decides for itself what
to do. The search agent isn't told "run these 15 queries" — it's told "find every relevant
party in every source" and works out the queries itself.

In one real run, the search agent noticed the rulebook requires checking *the individual who
controls the parent company*, and went looking for that person by name — a step nobody
scripted.

---

## 4. The key design decision: judgement vs. rules

This is the most important thing to understand about the system, and the reason it can be
trusted.

The rulebook contains two very different kinds of instruction, and we handle them
differently:

| | **Mechanical rules** | **Judgement calls** |
|---|---|---|
| Example | "COT matches before 15 July 2025 don't count" | "Is this hit actually the same company?" |
| | "Released = Ongoing" | "Does this engagement description match the service being sold?" |
| Handled by | **Fixed code.** Same input, same answer, every time | **The AI model** |
| Can it vary? | **Never** | Yes — it's a judgement |

**Why this split matters:** the answers that carry compliance risk — is this an audit
client, is this match too old, is a cross-border request required — are produced by fixed
code that cannot drift, cannot hallucinate, and returns the same verdict every single time.
The AI decides *which* rules to consult and *how to explain* the outcome, but never what
a rule says.

The fixed rules are wrapped as **tools the agents call**. So the agent decides "I need to
classify this engagement", calls the classification tool, and gets back an unarguable
answer plus the slide number it came from. Every one of those calls is recorded and shown
on screen.

### The tools available to the agents

**Look things up (5 databases)**
- Search DESC — the master list of entities and their restriction status
- Search WBS — actual chargeable engagements
- Search COT — client onboarding requests in flight
- Search DCCS history — ~3,500 previous conflict checks
- Search One Window — *stub; no data provided, and the system says so*

**Consult the rulebook**
- Find rules for a specific database
- Search the rulebook by question
- Get the mandatory legal footer (returned word-for-word, never rewritten)

**Look up people, not just companies**
- Find which clients a named partner or manager already serves
- Find who holds the Deloitte relationship for a client (the person to clear with)

**Triage and disambiguate**
- Score a match as High / Medium / Low reviewer priority
- Compare a borderline match against the client being screened, so false positives
  (similar name, different company) can be rejected

**Apply a rule (fixed answers)**
- Classify an engagement as Audit / Assurance / Non-Assurance
- Decide whether a completed engagement still counts
- Apply the COT cutoff date
- Apply the "too old / wrong status / already counted" tests to history
- Compare what the request claims against what the master database says
- Decide whether a cross-border request is required

---

## 5. How a real case flows through

Using request **12246557** — a genuine closed case, so we can compare against the answer a
human analyst actually gave.

**The request:** an HR transformation project in Malaysia, involving three companies —
a Thai client, its Singapore shareholder, and its Japanese ultimate parent (KDDI).

| Step | What happens |
|---|---|
| **1. Orchestrator** | Loads the case. Confirms the service offering matches the work described. Notices the *individual controlling the parent* isn't listed and flags it for the analyst. |
| **2. Search** | Searches all three companies across all five sources. Finds the parent in the master database, plus ongoing engagements, onboarding requests, and prior checks. Records One Window as unchecked. |
| **3. Rules** | Classifies every hit against the rulebook. **Catches a contradiction:** the request claims the Japanese parent is "Restricted", but the master database says "Audit Team Restricted, Relationship". Raises a warning with the exact escalation path. Decides Japan needs no cross-border request, because the parent is already in the master database. |
| **4. Synthesis** | Concludes *Approved with Conditions*, lists the conditions, and writes the draft — ending with the legal footer copied word-for-word. |

### The result, checked against the human analyst

The analyst who actually worked this case recorded their answer. We score ourselves against
it automatically:

| What we check | Human analyst said | System said | |
|---|---|---|---|
| Final outcome | Approved with Conditions | Approved with Conditions | PASS |
| Condition | "Relationship client in DESC" | Relationship designation in DESC | PASS |
| Engagement type | "Local WBS: Non-Assurance" | Non-Assurance | PASS |
| Engagements found | WBS & COT match | Both found | PASS |
| Japan cross-border | Request Not Required | Request Not Required | PASS |
| Designation contradiction | Caught it | Caught it, with escalation path | PASS |

**We reproduce the human analyst's determination on a real closed case.**

> ### The one that proves it's working
>
> One engagement is filed under "Audit & Assurance". A naive system sees the word "Audit"
> and flags the client as an audit client — which would be **wrong**, and would block work
> that should be allowed.
>
> The rulebook says A&A only counts as Audit under specific extra conditions, which this
> engagement doesn't meet. The system correctly classifies it **Non-Assurance** — matching
> what the human analyst wrote.

---

## 5b. Why the reviewer isn't handed 160 rows

A screening typically finds around 160 matches worth recording. Handing a reviewer that as
a flat list moves the problem rather than solving it.

Every match is therefore scored for **how much attention it deserves**:

| Priority | What it means | Example |
|---|---|---|
| **High** | Independence risk — read this first | The entity is Restricted in the master database, or the engagement is an audit |
| **Medium** | A condition will probably be needed | The entity has a Relationship designation — or carries a label the system doesn't recognise |
| **Low** | Worth recording, changes nothing on its own | Ongoing non-audit work, or a prior conflict check |

On the worked case this takes **160 matches down to 2** that need a reviewer: the Japanese
parent (Restricted) and the Thai entity (Relationship). The other 158 are recorded and
tucked away.

The result screen opens on **"Needs your attention"** and collapses the rest behind
**"For the record"**. A reviewer reads two rows instead of scrolling a spreadsheet.

The scoring is fixed code, not a judgement, so the same match always gets the same priority
and the reason is always shown — e.g. *"DESC records a Restricted designation (Audit Team
Restricted) — independence risk (slide 5)"*.

---

## 6. Example questions you can ask it

The assistant is conversational, and it answers by *doing the check* — searching the
databases, applying the rulebook, and prioritising what it finds. It is not a search box
over the rulebook.

**"Can we take this on?"** — the main question

| You ask | What it does |
|---|---|
| *"We've been asked to do an HR transformation project for KDDI (Thailand) Limited, requested from Malaysia. Any conflicts, and what conditions apply?"* | Searches all four databases, prioritises the hits, answers with the conditions |
| *"A partner wants to pitch tax advisory to KDDI Corporation. Anything blocking it?"* | Same, focused on what would stop the work |
| *"We're considering a statutory audit for KDDI Corporation. Is that allowed?"* | Surfaces the Restricted designation as the blocker |
| *"Of everything that came back, what actually needs my attention?"* | Returns the two matches that matter, not all 160 |

**"Who can work on it?"** — the engagement-team side

| You ask | What it does |
|---|---|
| *"We want to staff Soon Bee Koh as engagement partner. Does that create a conflict?"* | Lists the clients that partner already serves |
| *"KDDI Corporation is Audit Team Restricted. What does that mean for who we staff?"* | Explains the restriction and names the Deloitte contact to clear with |
| *"Who do I need to clear this relationship with?"* | Returns the responsible partner recorded against the client |

**"Is this really a match?"** and **"Does this old record still count?"**

| You ask | What it does |
|---|---|
| *"Search brought back 'Motto Auction Thailand Company Limited' for my client 'KDDI (Thailand) Limited'. Same company?"* | Compares country and parent company, rejects the false match |
| *"I found a conflict check from March 2021. Does it still count?"* | Applies the two-year rule and says no, with the reason |
| *"The requestor says Restricted but our master data says Relationship. Which do I go with?"* | Master data wins, and it gives the escalation path |
| *"What hasn't this tool checked that I still need to do myself?"* | Names the sources it couldn't reach |

Every answer shows an **agent trace** — which tools it used and what came back — so a
reviewer sees the working, not just the conclusion. A recorded run of all eighteen questions
is in [`QA_TRANSCRIPT.md`](QA_TRANSCRIPT.md).

**It remembers the conversation.** Ask a follow-up like *"and what designation does it
carry?"* and it knows what you're referring to. Conversations are saved, so closing the tab
and coming back picks up where you left off. It still re-checks the databases for every
answer rather than trusting what it said earlier.

**Typing doesn't have to be exact.** `KDDI CORPORATION`, `kddi corporation` and `kddi corp`
all return the same results.

---

## 6b. What happens when the data changes

The system will be pointed at new data — different clients, different countries, and labels
nobody has seen before. The design rule for that case is simple:

> **Anything the system doesn't recognise gets escalated to a human, never quietly filed
> as harmless.**

Concretely:

- A restriction label we've never seen (say "Sanctions Restricted") is still treated as a
  restriction, because the system reads the *meaning* of the word rather than looking it up
  in a fixed list.
- A designation that genuinely matches nothing is marked **Medium priority** with the note
  *"not risk-assessed — reviewer to confirm"*. It is never assumed to be low risk.
- If a spreadsheet column is renamed, the system still finds it. If it genuinely can't, it
  says so rather than leaving the field blank without explanation.
- If rows in a source document can't be read, it reports how many. Silent data loss is the
  one failure that would be invisible, so it is measured. Applying this to the existing
  sample recovered around 400 rows that had been dropped without anyone knowing.

The **rules themselves** stay fixed on purpose. "Audit engagements are restricted" comes
from the rulebook, not from the data, so it shouldn't change when the data does. What has
been made flexible is everything that was really an assumption about the one sample file.

---

## 7. What we are honest about

Stating these openly is deliberate. A visible limitation reads as engineering judgement;
a hidden one reads as a defect when someone finds it.

1. **One data source has no data.** One Window (strategic clients, directorships,
   sanctions) wasn't provided. The architecture treats it as one more tool; the UI lists
   it as unchecked on every result.
2. **We have one worked case, not a test set.** Scoring 6/6 proves we *reproduce* a known
   correct answer. It does not prove we generalise.
3. **One rule has no negative example in the data.** Every onboarding record post-dates the
   cutoff, so that rule never fires here. We prove it works with a synthetic test instead.
4. **"Recently completed" is undefined in the rulebook.** We assume 180 days and show the
   assumption rather than burying it.
5. **It drafts, it does not approve.** Every classification carries its rule citation
   precisely so an analyst can overturn it.
6. **Speed depends on the model.** Running on a small local model, a full screening takes
   a few minutes. The fixed rules are instant; the time is the AI reading and reasoning.

---

## 8. Why this approach is defensible

- **The risky answers can't drift.** Compliance-relevant verdicts come from fixed code, not
  from a model that might phrase things differently tomorrow.
- **Everything is attributable.** Every classification names the rulebook slide behind it.
- **The working is visible.** The agent trace shows every lookup that informed an answer.
- **It's measurable.** We score against a real analyst's real determination, so "it works"
  is a number, not an impression.
- **A human still decides.** The system does the searching and the drafting. The judgement
  that matters stays with the analyst.
