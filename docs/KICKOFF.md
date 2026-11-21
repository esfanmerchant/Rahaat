# Kickoff: who does what, in what order

Follow this top to bottom. The plan itself is in `PLAN.md`.

## 1. Before any code (people, about 40 minutes, in parallel)

Answer these four questions first, then tell the lead session:

1. **Seats.** How many teammates have their own Claude subscription and laptop?
2. **Host.** Which row of PLAN 5.4 can you do? University email for Azure for Students, a card for Hugging Face PRO ($9), or neither (laptop + tunnel).
3. **Keys.** Can someone create a free Groq key (better Urdu speech recognition)? Any LLM key? Both are optional.
4. **Languages.** Decided: Urdu and English. No regional language is shipped unless a native speaker can check every string.

Then:

- [ ] Create an **empty public GitHub repo** and note its URL.
- [ ] Set your git identity once per machine: `git config --global user.name "..."` and `git config --global user.email "..."`.
- [ ] Install `uv` (PowerShell), then reopen the terminal:
      `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- [ ] Create a **Neon** project (free, no card) for the deployed site and copy its direct connection string. Development and tests need no database setup: an embedded PostgreSQL starts by itself.
- [ ] Start the account for your chosen host.
- [ ] Find an Android phone with Chrome and a USB cable for testing.
- [ ] Optional: `winget install UB-Mannheim.TesseractOCR` so OCR also runs on the laptop.

Never paste a secret into a prompt or commit it. Secrets go in `.env`, which is git-ignored.

## 2. How Claude Code agents work here

There are three ways to put agents to work. Use them together.

**a) Subagents: specialists inside one session.** They are the files in `.claude/agents/`. Each has its own instructions and its own context, so the main conversation stays clean. Type `/agents` to see them. Start a new session after adding or editing a file so it is loaded. To use one, name it in your message:

> Use the decision-engineer agent to implement B1 and B3 from PLAN 7.B.

The main session can also launch several at once when their work does not overlap.

**b) Parallel sessions: one per track.** Each session works in its own copy of the repo (a git worktree) on its own branch, so sessions cannot overwrite each other. Each teammate supervises one or two. This is the main way we go fast.

**c) Workflows.** In a session, the words "use a workflow" let Claude script a larger fan-out of agents, for example one agent per admin screen followed by a checker. It spends usage quickly. Keep it for Phase 3 work that is well specified and independent.

The agents:

| Agent | Use it for |
|---|---|
| `backend-core` | auth, RLS, consent, cases, payments, webhooks, API keys, sync (Track A) |
| `decision-engineer` | rules, cost-based decisions, calibration, name matching, evals, Digital Twin (Track B) |
| `ai-engineer` | OCR/QR/forgery, scam classifier, voice, RAG, agent, guardrails (Track C) |
| `citizen-ui` | the citizen PWA: voice, icons, offline, Urdu and RTL (Track D1) |
| `staff-ui` | officer, admin and auditor consoles, charts, Challenge Lab (Track D2) |
| `devops` | Dockerfile, CI, deploy, seed, health and metrics |
| `security-reviewer` | read-only review of a change against the security rules |
| `verifier` | runs the app and the tests and reports what really works; writes no feature code |

## 3. Phase 0: one session, lead only (Sat 12:30-15:00)

Nobody else writes code until this is on `main`, because every track builds on it.

In the project folder:

```powershell
git init -b main
git add .
git commit -m "Plan, project rules and agent definitions"
git remote add origin <your-repo-url>
git push -u origin main
```

No `.env` is needed for development (copy `.env.example` only if you have optional keys). Then paste this into a fresh session on the strongest model you have:

> Read CLAUDE.md and PLAN.md fully. Execute PLAN 7.0 (Phase 0, foundation) now. Build the backend foundation yourself. In parallel, use the citizen-ui agent for F9 (frontend scaffold) and the devops agent for F10 to F12 (scripts, CI, Dockerfile, deploy files). Commit in small slices. Stop when Gate 0 in PLAN section 8 passes, then report what you ran, what failed, and what you could not verify. Do not start Phase 1.

While it runs, the people do the first deploy (PLAN 5.4) with the `devops` agent's files and confirm the URL opens.

## 4. Phases 1 to 3: one session per track

**With teammates.** Each teammate clones the repo and works on one branch. No `.env` and no database setup are needed:

```powershell
git clone <your-repo-url> rahat ; cd rahat
git switch -c track/b-decision
npm install ; npm run install:all ; npm run migrate ; npm run seed
npm run dev        # API on :8000, web on :5173; demo sign-ins at /demo
```

**Several sessions on one machine.** Use worktrees, one VS Code window each:

```powershell
git worktree add ..\rahat-b  -b track/b-decision
git worktree add ..\rahat-c  -b track/c-ai
git worktree add ..\rahat-d1 -b track/d1-citizen
git worktree add ..\rahat-d2 -b track/d2-staff
code ..\rahat-b
```

In each worktree run `npm install`, `npm run install:all`, `npm run migrate` and `npm run seed` once. Each worktree gets its own embedded database, so sessions cannot disturb each other's data. Only one of them can use port 8000 at a time; give the others `--port 8001` and so on.

**The prompt for a track session** (replace the letter, the section and the phase):

> You own Track B. Read CLAUDE.md, PLAN sections 5 and 6, PLAN 7.B and docs/CONTRACTS.md. Do the Phase 1 items of 7.B in order. For each item: implement it, write tests, run them, commit. Stay inside the directories Track B owns; put any request for a change elsewhere in docs/REQUESTS.md. When the Phase 1 items are done, run `npm run verify`, tick docs/STATUS.md, and report what you ran, what failed, and what you could not verify. Then stop.

For the next phase, start a **fresh session** with the same prompt and the next phase number. A fresh session has a clean context and stays sharp.

**Working alone.** One session, all tracks as subagents:

> Read CLAUDE.md and PLAN.md. Run Phase 1. Launch the backend-core, decision-engineer, ai-engineer, citizen-ui and staff-ui agents in parallel, each on its Phase 1 items from PLAN section 7, each staying in its own directories. When they finish, use the verifier agent to check Gate 1 on the running app and report honestly.

## 5. The merge loop (lead, about every 90 minutes)

In each track: `git fetch origin`, `git rebase origin/main`, `npm run verify`, `git push`.

Lead, on `main`, one track at a time:

```powershell
git switch main ; git pull
git merge --no-ff origin/track/b-decision
npm run verify
git push            # triggers or is followed by the deploy
```

Then open the live URL and click through the anchor flow. If it broke, fix or revert before merging anything else.

Check the gate with a fresh pair of eyes:

> Use the verifier agent to check Gate 1 from PLAN section 8 against the live URL <url>. Run things; do not rely on reading code. List what passes, what fails and what could not be checked.

After any change to auth, RLS, consent, uploads, webhooks or payments:

> Use the security-reviewer agent to review the last three commits.

## 6. Gates and cuts

Gate times are in PLAN section 8. At each gate: anything not green is cut or hidden behind a flag, cuts come from the bottom of the tier, and the next tier does not start until the gate passes on the live URL. Feature freeze is Sun 10:00. Code freeze is Sun 14:00.

## 7. Only people can do these

- Test the citizen flow on a real phone, with the network throttled and in airplane mode.
- Read every Urdu string aloud. Fix anything a grandmother would not understand.
- Record the fixed prompts in a quiet room (the list is generated in item C5) and drop the files in by name.
- Rehearse the eight-minute demo twice with a timer, then record the video.
- Check the Google Drive link in a private browser window. Submit by 16:30.

## 8. Keeping usage limits alive

- Check `/usage` every couple of hours.
- Use the strongest model for Phase 0, RLS and consent, the decision core and offline sync. Use Sonnet (`/model sonnet`) for screens, tests and documents.
- Do not run more than two heavy sessions on one subscription at the same time.
- If one account hits its limit, another teammate continues from `PLAN.md` and `docs/STATUS.md`. That is why both are kept current.

## 9. When something goes wrong

- **An agent says "done" but it does not work.** Ask the `verifier` agent to reproduce it, then give the failing output back to the owning track.
- **Merge conflict.** It almost always means someone left their directories. Keep the owner's version and move the other change into a request.
- **Deploy is red and time is short.** Revert the last merge. `main` must stay deployable.
- **"Address already in use" on port 8000.** An old server is still running. In PowerShell: `Get-NetTCPConnection -LocalPort 8000 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`, then `npm run dev` again.
- **Behind at a gate.** Cut. A smaller system that works beats a larger one that breaks in front of the judges.
