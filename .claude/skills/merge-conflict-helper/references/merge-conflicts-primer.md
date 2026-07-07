# Merge conflicts, in plain English

A short primer for people who are new to git and GitHub. No prior knowledge assumed.

## What a merge conflict actually is

Git is the tool that keeps track of changes to a project's files. Most of the time, when two people (or two branches of work) change different things, git combines them automatically and you never notice.

A **merge conflict** happens in the one case git *can't* safely decide on its own: when two changes touch **the same lines of the same file** in different ways. Git doesn't want to guess and risk throwing away someone's work, so it stops and says, in effect, "two versions of these lines exist — a human needs to tell me which to keep."

That's the whole thing. A conflict is not an error, not a bug, and not something you broke. It's git being careful.

## Why it's not scary

Three things worth knowing up front, because they take almost all the fear out of it:

1. **Nothing is lost.** Both versions of the conflicting lines are still there. You're choosing between them, not recovering something deleted.
2. **There's an undo button.** If it gets overwhelming, the whole conflict can be cancelled and you go right back to where you started, as if nothing happened. (The command is `git merge --abort`, or `git rebase --abort` — whoever's helping you will know which.)
3. **Nothing becomes permanent until you decide it does.** Resolving the conflict, saving, committing, pushing, and merging are all separate steps. You (or a reviewer) get to check the result before it affects anyone else.

## What a conflict looks like in a file

When there's a conflict, git edits the file to show you both versions, wrapped in marker lines. It looks something like this:

```
some code everyone agrees on
<<<<<<< (one version)
the first version of the disputed lines
=======
the second version of the disputed lines
>>>>>>> (the other version)
more code everyone agrees on
```

- Everything between the `<<<<<<<` line and the `=======` line is one version.
- Everything between `=======` and `>>>>>>>` is the other version.
- The lines above and below the markers are fine — only the bit between the markers is in dispute.

"Resolving" the conflict means editing that section down to the single version you want (which might be one side, the other, or a sensible combination), and then deleting the three marker lines so the file reads normally again.

> One important subtlety: which side is "yours" and which is "theirs" depends on whether git is doing a *merge* or a *rebase* — and a rebase flips them. That's a common way people accidentally keep the wrong version. It's exactly why it's worth having help (or this skill) describe each side by *what it is* — "the version already on the main branch" vs. "the change you just made" — instead of just "top" and "bottom."

## How to think about which version to keep

Not every conflict is equal. Roughly:

- **Some are trivial** — the two sides added different things that don't actually clash (say, two new items in a list). Keeping both is obviously right.
- **Some are a judgment call** — both sides genuinely changed the same thing, and someone has to decide which is correct. If you understand what the code or content is for, this can be your call.
- **Some shouldn't be your call at all** — the right answer depends on a decision, a setting, or context that isn't visible in the code. The correct move there is not to guess, but to ask the person who made the other change. Deferring is the smart, professional choice, not a failure.

## The order of operations (so nothing surprises you)

1. **Resolve** the conflicting lines in each file and remove the markers.
2. **Check it works** — ideally run the project's tests. A failing test is often the only sign a resolution was wrong.
3. **Commit** — record the resolved result. Still local to your machine.
4. **Push** — send it up to GitHub so others can see it.
5. **Review and merge** — a human reviews the change (usually via a pull request) and merges it into the shared branch.

Each step is reversible or reviewable up until that final merge. Take them one at a time, and when in doubt, ask.
