# Ajaia LLC — Technical Project Manager Assessment

**Video:** `<paste link>`
**Build file:** https://github.com/hasina1990/Ajaia/tree/main/build
**Repo:** https://github.com/hasina1990/Ajaia
**Resume:** https://drive.google.com/file/d/1oeavpFB8k0rOzEMUlKDDhOPD7bmHI_DB/view
**Company reference:** https://ajaia.ai

Submitted by Hasinabanu Ansari.

---

## Task 1 — Triage

Ranked by risk to the September 8 date.

| Rank | Item | Call | Why |
|---|---|---|---|
| 1 | **C** — DET-121, Terminal 3 EDI schema mismatch, null urgency scores | **Worked — escalate today** | Scoring silently returns null for a chunk of one of three terminals. It does not error, it returns nothing, so bad data looks like good data. Open since 8/6 and never picked up. The 2-day estimate only starts when Corrigan Peak IT answers, so every day without a named contact is a day off the date. |
| 2 | **B** — Priya's routing retry / duplicate push | **Worked — fix before merge** | If the queue push succeeds and the "routed" DB write fails, the same exception is pushed again next cycle. Overlapping poll cycles cause the same thing. Two dispatchers acting on one shipment destroys trust in the tool in week one. Caught pre-merge, so it is cheapest now and never cheaper again. |
| 3 | **D** — DET-118, schedule routing-rules review with three terminal leads | **Worked — today, 20 minutes** | Tagged "no blocker, just sitting," which is why it is a risk. The work is not the review, it is the calendar latency of three external people three weeks from go-live. Costs nothing to clear today, becomes a slip if it sits another week. |
| 4 | **A** — Dana: auto-reassign to a backup carrier | **Deferred — committed to the first post-launch sprint** | Not a feature add, a category change: the tool moves from recommending to a human to taking a commercial action on freight — carrier eligibility, rate agreements, liability, rollback when it picks wrong. It would also sit directly on top of item B; a duplicate alert becomes a duplicate carrier booking once the human is removed from the loop. Deferred rather than declined because the request is legitimate and has a named business driver, so it gets a committed sprint slot and a date, not a no. Handled through the **change request flow**: written scope, estimate and date impact, signed off by Dana before it enters a sprint — not absorbed informally into the current one. |
| 5 | **E** — Marcus: different shade of blue on the queue UI | **Declined for launch — logged in backlog, not sprinted** | No named requester, no stated problem, relayed secondhand as "mentioned in passing." "Probably a quick CSS thing" is a design decision plus a review plus a redeploy, against the one deliverable still awaiting client review. This is the noise item. |

### Which item is noise

**E.** It is the only item on the list with no identified requester and no problem behind it.

The pairing worth naming: **E looks like work and is noise. D looks like noise and is work.**

### What moves or gets cut to protect the date

The 8th holds because **A and E stay out of this sprint**, not because anyone works faster.

The mechanism matters as much as the decision: **A goes through the change request flow** — written scope, estimate, date impact, client sign-off — rather than being absorbed informally. Informal scope absorption is how a committed date dies quietly, and a change request is what makes the trade-off visible to the person who owns the date. E does not reach change request; it has no requester to sign one.

The residual risk is not ours to absorb: **C's two-day tail does not start until Corrigan Peak IT confirms the Terminal 3 field mapping.** If that answer is not in hand by **Thursday 20 August**, September 8 is at risk and I will say so in writing at that point rather than at the end.

### Counter-case I considered

The defensible alternative on **A** is to build the suggest-only version now — the tool proposes the backup carrier and pre-fills it, the dispatcher confirms with one click. It is genuinely smaller than full auto-reassign. I still declined it for 9/8, because any new write path into the routing service competes for the same engineer who is fixing item B in the same week, and B is a correctness bug on the primary path. Suggest-only is the first post-launch item instead.

---

## Task 2 — Build

**File:** `build/main.py` (plus `build/exceptions_raw.csv`)

**Run:**

```bash
python build/main.py            # normalize + summary report
python build/main.py --selftest # verification suite
```

**What it does.** It normalizes the three fields that are inconsistent in the export — terminal (`T3` and `Terminal 3` collapse to one value), carrier code (`swft`, `SWFT`, `Swft` collapse to `SWFT`), and timestamp (three different formats into ISO 8601) — then prints a count by event type and an explicit review queue. Result: doc_mismatch 2, missed_pickup 2, carrier_substitution 1, total 5. One record, **CPX-88216**, is flagged as not confidently cleanable: its `carrier_code` is empty in the source. I left it blank and flagged it rather than inferring a carrier, because that field drives who gets billed and who gets called. The design rule throughout is that nothing is dropped and nothing is silently guessed — every input row appears in the output, with a reason attached where a value could not be determined.

**How I checked it actually worked, not just that it ran.** I worked out the expected output from the five records by hand first, then wrote 19 assertions against those values — per-field and end-to-end — so a pass means the numbers are right, not that the process exited cleanly. The suite deliberately includes cases the sample data does not contain: a date that is ambiguous between MM/DD and DD/MM must raise a warning rather than silently pick one; a date that can only be DD/MM must be detected as such; unparseable garbage must be flagged instead of crashing. I also assert that the input and output row counts match, because a row quietly vanishing is the most dangerous failure in this kind of pipeline and the easiest one to miss.

**The finding that matters more than the counts.** Four of the five timestamps carry no timezone; one carries an explicit `Z`. I did not flatten that difference — the output preserves a `ts_basis` column recording which is which. Urgency scoring is elapsed-time arithmetic, so if those un-zoned timestamps are terminal-local and get read as UTC, the tool produces confidently wrong urgency scores with no visible error. That is the same shape as the null-score symptom in DET-121, and it is a question for Corrigan Peak IT, not something to guess. I deliberately did **not** mark those four rows as "needs review" — flagging 80% of a file makes the review queue useless. It is one systemic question, not five record defects, so it is reported once, separately.

**Out of scope, deliberately:** no timezone conversion until the client confirms the basis; no carrier-code validation against Corrigan Peak's carrier master; no dedupe across exports.

---

## Task 3 — Client Status Update

**Subject: Dispatch Exception Triage — status moving to Amber, and an answer on the auto-reassign question**

Dana,

I'm changing this week's status to **Amber**, and I want to correct last Friday's update before anything else.

Friday's note described the Terminal 3 work as "a minor data validation task" expected to wrap up without impact, and reported no blockers. That was not accurate, and I'd rather you hear it from me than find it later. The Terminal 3 issue is a schema mismatch in the EDI feed, it has been open since 6 August, and it is currently producing **null urgency scores for a portion of Terminal 3 exceptions**. It is also blocked on our side pending an answer from your team, which means it should have been reported as a blocker and was not. That reporting gap is mine to own.

**Where the September 8 date actually stands.** I still believe we make it. It is not comfortable, and it depends on one thing from you.

We need your IT contact for the FreightWorks Terminal 3 feed to confirm which fields Terminal 3 actually sends, including whether its timestamps are terminal-local or UTC. The export your team sent helped — I've run it through a normalizer and can tell you exactly which fields are inconsistent, which is a useful head start. But the field mapping has to be confirmed by someone on your side. Once we have it, the fix is two days.

**If that answer is not with us by Thursday 20 August, September 8 is at risk.** I would rather flag that now, with three weeks of room to react, than tell you in the first week of September.

Alongside that, our engineer identified a defect in the routing retry logic in her own pre-merge review — under certain failure conditions the same exception could be sent to a dispatcher twice. She caught it before it shipped, and we're fixing it this week. I'm mentioning it because it bears directly on your next question.

**On auto-reassignment to a backup carrier.** I'm not going to commit that for the 8th, and I want to give you the real reason rather than a scheduling one.

Today the tool recommends and a dispatcher decides. Auto-reassignment changes what the tool *is* — it would take a commercial action on live freight on its own. That needs carrier eligibility rules, your rate agreements, and a defined rollback for when it picks wrong, none of which we've scoped with you. More immediately: the duplicate-send defect above is exactly the kind of fault the dispatcher confirmation step currently absorbs. Remove the human, and a duplicate alert becomes a duplicate carrier booking on a real shipment. I don't want to hand your COO an automation story that turns into an incident in launch week.

What I can offer, and would commit to as the first item after go-live: the tool **identifies the backup carrier and pre-fills the reassignment**, and the dispatcher confirms it with one click. That gets your COO most of the speed he's after, keeps a person accountable for the decision, and is the natural first step toward full automation once we've watched the scoring behave on live data.

I'll raise this as a **formal change request** this week so it's not just a conversation — scope, estimate and any date impact in writing, for your sign-off. I'd rather your COO sees a costed commitment with a date than a verbal maybe, and it means neither of us is guessing later about what was agreed. You'll have it within a week of launch, and I'd expect it in the first post-launch sprint.

**This week:** Terminal 3 field mapping (blocked on your IT contact), routing retry fix, and I'm scheduling the routing-rules review with your three terminal leads directly — I'll send those invites today rather than wait for schedules to line up.

One request: a name and an email for the Terminal 3 FreightWorks contact, today if possible. That single item is the difference between comfortable and at-risk on the 8th.

Happy to get on a call if that's faster.

Hasinabanu Ansari
Technical Project Manager, Ajaia — https://ajaia.ai

---

## Task 4 — AI Workflow Note

**Where I used AI.** Task 2, for the normalizer scaffolding — the regex patterns for the terminal and slash-date formats, and the structure of the assertion suite. I also used it as a first reader on the Task 3 draft, specifically to check whether the correction landed as ownership rather than as blame-shifting onto the account team.

**What I kept human.** All five triage calls in Task 1, and the reasoning behind each. The decision to declare Amber rather than Green. The decision to decline auto-reassignment and the argument used to decline it — that one came from connecting Priya's duplicate-send defect to Dana's request, which is a judgement about blast radius, not a code question. The Thursday 20 August trigger date. And the choice to state plainly in the client email that the reporting gap was mine.

**One thing I rejected.** The first draft of the normalizer converted every timestamp to UTC, which produced clean uniform output and looked correct. It was wrong: only one of the five records actually carries a timezone, so converting the other four silently assumes they are UTC. Since urgency scoring is elapsed-time arithmetic, that assumption yields confidently wrong scores with no error to notice — the same shape as the bug in DET-121. I rewrote it to preserve a `ts_basis` column and escalate the question instead of resolving it. Clean output would have buried the most important finding in the file.

AI also suggested flagging all four un-zoned rows as "needs review." I declined that too — flagging 80% of a file trains people to ignore the queue.

---

## Optional

- GitHub: https://github.com/hasina1990
- Company reference: https://ajaia.ai
