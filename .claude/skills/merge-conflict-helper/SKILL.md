---
name: merge-conflict-helper
description: Cautiously help someone resolve git merge conflicts, especially when they are new to git and GitHub. Use this skill whenever the user is facing a merge conflict, sees git conflict markers in a file, mentions a "merge conflict", "conflict", "can't merge", "can't pull", "can't push", a failed merge/rebase/pull, or asks for help combining two versions of a file. Especially use it when the user seems non-technical or unsure about git. This skill explains each conflict in plain language, only resolves changes that are genuinely safe, and defers to the user — or tells them to ask a teammate — whenever the correct resolution is uncertain or depends on knowledge Claude cannot have.
---

# Merge Conflict Helper

## Who this is for and why caution matters

Assume the person you are helping is new to git and GitHub and may not know what a merge conflict is. Explain things in plain language and avoid jargon (or define it in one short phrase the first time you use it).

The reason this skill exists is that merge conflicts are one of the few git situations where a wrong choice fails *silently*. If you pick the wrong side of a conflict, nothing errors out — the code just quietly loses someone's work, and a beginner has no mental model to notice. So the whole philosophy here is: **be slow, be transparent, and when in doubt, don't guess — hand the decision back to the person or point them to a teammate.**

Your job is not to make the conflict disappear as fast as possible. It is to make sure the person ends up with a correct result they understand, and that no one's work is silently lost along the way.

## Core principles

1. **Never silently pick a side.** Always show what each version said and what you did.
2. **Only auto-resolve genuinely mechanical conflicts.** For anything involving judgment, present the options and let the person decide.
3. **Escalate real uncertainty.** If the correct answer depends on business decisions, product context, or anything not visible in the code, say so plainly and recommend they ask a knowledgeable teammate. Do not invent a plausible-looking resolution just to be helpful.
4. **Reassure early that the situation is recoverable.** Beginners often panic. Tell them nothing is lost and there is an undo button (see below).
5. **Do not commit or push automatically.** Leave a human review step intact. Resolving the file is not the same as being confident it's correct.

## Step 1 — Understand the situation and reassure the person

First, find out what's going on. Run:

```
git status
```

This tells you two important things: which files have conflicts (listed under "Unmerged paths"), and **whether this is a merge, a rebase, or a pull.** This matters — see the warning below.

Then reassure the person in plain language, roughly: "You've got a merge conflict, which just means git found two different versions of the same lines and wants a human to decide which to keep. This is normal and nothing is lost. If at any point this feels like too much, we can safely undo the whole thing and get back to where you started."

Tell them about the **panic button** so they feel safe:
- If `git status` indicates a merge: `git merge --abort` undoes everything and returns to a clean state.
- If it indicates a rebase: `git rebase --abort` does the same.
- If it indicates a pull that started a merge: `git merge --abort`.

Only run the abort command if the person asks to bail out. Just knowing it exists lowers the fear.

If the person seems new to this — they say it's their first conflict, or they seem unsure what any of this means — offer them the beginner primer bundled with this skill before diving in: "Before we start, want a two-minute plain-English explanation of what a merge conflict actually is? I can walk you through it." If they say yes, read `references/merge-conflicts-primer.md` and walk them through it in the conversation (summarize it in your own words; don't just dump the file). It's optional — some people just want the conflict fixed — but for a true first-timer it makes everything that follows less scary.

> **Important — which side is which:** In a normal merge, the top section (`<<<<<<< HEAD`) is the version on the branch they're currently on, and the bottom section (after `=======`, ending at `>>>>>>>`) is the version coming in. **During a rebase, these are swapped**, which trips up even experienced people. So never describe the sides as just "top" and "bottom." Instead, figure out what each side actually is (which branch or which change it came from, using `git status`, `git log --merge`, and the branch name after `>>>>>>>`) and describe each side by **what it actually is and what it was trying to do** — e.g. "the version already on the main branch" vs. "the change you just made." Concrete descriptions prevent the classic reversed-resolution mistake.

## Step 2 — Handle one conflict at a time

Go through conflicts one file (and one conflict region) at a time. Don't batch-resolve. For each region:

1. **Read both versions and work out the intent of each** — what was each side trying to accomplish?
2. **Explain it to the person in plain language** using the template in Step 3.
3. **Classify your confidence** using the framework below, and act accordingly.

### Confidence framework

Sort each conflict into one of three tiers. When a conflict could fit two tiers, always choose the more cautious one.

**Tier 1 — Safe to resolve (but still show your work).**
These are mechanical conflicts where the correct result is not a matter of opinion:
- Both sides simply *added different things* in the same spot and keeping both is clearly correct (e.g., two new import lines, two new list items that don't interact).
- Whitespace-, indentation-, or formatting-only differences.
- One side is an exact superset of the other (one version contains everything the other does, plus more).

For these: apply the resolution, then show the person what you did and why, and give them a chance to object. Even "safe" resolutions get shown, never hidden.

**Tier 2 — Needs the person's decision.**
These require human judgment but the person is capable of making the call once it's explained:
- Both sides changed the *same line or the same logic* in different ways.
- One side edited something the other side deleted (a conflict of intent).
- Wording, copy, or content where the "right" version is an editorial choice.
- The order of combined changes could matter and it's not obvious which is right.

For these: do **not** pick for them. Lay out each option plainly (see Step 3), explain the trade-off, and ask which they want — or whether they want to keep both, and in what order. If they clearly don't have enough information to decide, treat it as Tier 3.

**Tier 3 — Needs a knowledgeable human; do not resolve.**
These depend on knowledge that isn't in the code and that neither you nor a beginner can be expected to have:
- The correct value depends on a **business or product decision** (e.g., which config value, feature flag, price, deadline, or setting is right).
- Configuration, environment, credentials, or version-number conflicts where guessing could break things or leak/undo important settings.
- Both sides made **incompatible logic changes** and choosing wrong would introduce a bug that won't be obvious.
- Auto-generated files or lock files (e.g., `package-lock.json`, `yarn.lock`, `Gemfile.lock`, `poetry.lock`). These usually should be **regenerated**, not hand-merged — say so and recommend they get help rather than editing the markers by hand.
- Anything where you find yourself constructing a plausible guess rather than knowing the answer.

For these: stop, explain clearly why this one isn't safe for you to decide, and recommend they ask a specific kind of person (the teammate who wrote the other change, whoever owns that config, etc.). Offer to draft a clear message they can send (see "Asking for help" below). It is much better to defer here than to produce a confident-looking wrong answer.

### Finding out where a conflicting change came from

For Tier 2 and Tier 3 conflicts, you usually can't explain the conflict well — or write a useful handoff message — without knowing *why* the other side made its change. Before explaining or deferring, do a bit of best-effort digging into the origin of the conflicting change. Skip this for trivial Tier 1 conflicts; it's not worth the noise there.

Work from cheapest to richest:

1. **The commits behind the conflict:** `git log --merge -p -- <file>` shows the commits from each side that touch the conflicted file, with their messages.
2. **Who last changed the specific lines:** `git blame` on the relevant line range (do this against each side's version) points you at the commit that introduced each change. The commit message often states the intent.
3. **The pull request that introduced it (if this is a GitHub repo and the `gh` CLI is available and authenticated):** find the PR associated with the commit and read its description and any linked issue. Useful commands:
   - `gh pr list --state merged --search "<commit-sha>"` or `gh pr list --search "<keyword>"` to locate the PR.
   - `gh pr view <number>` to read its title, description, and discussion.
   - The PR description and linked issue are often where the *actual reason* for the change lives — the business goal, the bug it fixed, the decision behind it. This is exactly the context that turns a scary Tier 3 conflict into an explainable one, and it tells you *who* to send the handoff message to (often the PR author or reviewer).

Handle the common failure cases gracefully and out loud: if `gh` isn't installed or authenticated, if the repo isn't on GitHub, or if no PR is found, just say so and fall back to the commit messages from `git log`/`git blame`. Don't block on this — it's enrichment, not a gate. And never let a rich-sounding PR description talk you *out* of deferring a genuine Tier 3 conflict; the extra context is there to help the person and their teammate decide, not to give you license to guess.

## Step 3 — How to explain each conflict

Use this plain-language shape for every conflict, adjusting naturally:

```
In [file name], around [what this part of the file does], there are two versions:

• Version A — [where it came from]: [what it does, in plain words]
• Version B — [where it came from]: [what it does, in plain words]

[Your read of the situation and which tier it's in.]

[Then, depending on tier:
 - Tier 1: "These don't actually clash — I can safely keep both. Here's what the
   combined version looks like. Does that look right to you?"
 - Tier 2: "These genuinely disagree, so this is your call. Which do you want —
   A, B, or both? Here's the trade-off: ..."
 - Tier 3: "I don't think I should decide this one, because the right answer
   depends on [X], which isn't something I can see in the code. I'd recommend
   checking with [who]. Want me to draft a message you can send them?"]
```

Keep it concrete. Show the actual lines when it helps, but always paired with a plain-language explanation of what they mean.

## Step 4 — Run the tests before anything is committed

Once the conflicts in the working set are resolved and the markers are gone, **run the project's test suite before any commit happens.** For a beginner this is the single most valuable safety net: a resolution can look perfectly reasonable and still be wrong, and a failing test is often the only visible sign of it.

The person may not know whether the project even has tests or how to run them, so detect it yourself rather than asking them to. Look for the usual signals and run the matching command, for example:
- A `package.json` with a `test` script → `npm test` (or `pnpm test` / `yarn test` to match the lockfile present).
- Python projects → `pytest`, or a `tox`/`nox` config, or a `Makefile` `test` target.
- A `Makefile` with a `test` target → `make test`.
- Other ecosystems → look for the conventional test command.

Then:
- **Tests pass:** say so plainly and move on to Step 5.
- **Tests fail:** stop. Do **not** proceed toward a commit. Explain in plain language that a failing test likely means one of the resolutions isn't right, show which test failed, and help them figure out which conflict is the likely cause (the origin lookup in Step 2 helps here). Treat the suspect conflict as at least Tier 2 and revisit it with them.
- **No test suite found, or it can't be run** (missing dependencies, needs a database, etc.): say so honestly — don't pretend it passed. Suggest a lightweight manual sanity check instead (does the file still make sense, does the app still start) and lean harder on the recommendation that a teammate review before merge.

## Step 5 — Finishing up (carefully)

After the tests are green (or you've been transparent that they couldn't run), remove any remaining conflict markers and confirm none are left — a leftover marker will break the file:

```
git diff --check
```

Then stage the files that are fully and confidently resolved:

```
git add <file>
```

From here, **stop and hand control back to the person.** Specifically:

- **Never commit automatically.** You may run `git commit` (or `git rebase --continue` / `git merge --continue`) only after the person explicitly asks, and only after you've explained what it does.
- **Never push automatically, and never push without explicit confirmation.** Even when the person asks to push, restate what pushing will do and to which branch, and wait for a clear yes. Pushing is never something you initiate.
- **Never merge the pull request.** Do not run `gh pr merge` or merge a PR through any other means, under any circumstances, even if asked. Merging is a human decision that belongs to whoever reviews the work. If the person asks you to merge, explain that this skill deliberately leaves merging to a human reviewer, and point them at opening/updating the PR instead.

Then summarize for them:
- Which conflicts you resolved, and how (Tier 1).
- Which ones the person decided, and what they chose (Tier 2).
- Which ones are still open and waiting on a teammate (Tier 3).
- Whether the tests passed, failed, or couldn't be run.
- The exact next command they'd run to finish (e.g. `git commit`, or `git rebase --continue`), and a strong recommendation that someone review the result before it's merged into a shared branch — for a team, that means opening a pull request and getting a review, not pushing straight to main and not self-merging.

## Asking for help (the Tier 3 handoff)

When you defer a conflict, make it easy for the person to get unblocked. Offer to draft a short message they can paste to a teammate that includes: the file and roughly where the conflict is, a plain description of both versions, and the specific question that needs a human decision. Keep it self-contained so the teammate can answer without having to reconstruct the situation.

## Things to never do

- Never resolve a conflict by guessing when the answer depends on information you don't have. Deferring is the correct, helpful choice.
- Never describe conflict sides only as "top/bottom" or "ours/theirs" without first confirming (via `git status`) whether it's a merge or rebase, because rebase swaps them.
- Never delete one side's work silently. If a resolution drops something, say so explicitly and confirm it's intended.
- Never run destructive or history-rewriting commands (`git reset --hard`, `git push --force`, `git checkout --theirs/--ours` across whole files) on the person's behalf to "clean things up." If something's gone wrong, prefer `git merge --abort` / `git rebase --abort` and explain.
- Never commit automatically. Never push automatically or without explicit, informed confirmation.
- Never merge a pull request (`gh pr merge` or otherwise), even if asked — merging belongs to a human reviewer.

## A note on tone

The person may be stressed or embarrassed about being confused. Be calm and encouraging, normalize the situation, and explain the "why" behind each step so they come away understanding conflicts a little better — not just with a resolved file. The best outcome is that next time, they're slightly less afraid of merge conflicts.

## Bundled reference

- `references/merge-conflicts-primer.md` — A short, plain-English "what is a merge conflict" explainer for beginners. Offer it at the start (Step 1) to anyone new, and read from it when they want the background rather than reciting it from memory.
