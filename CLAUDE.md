# Supernova x SpacePoint Hackathon — "Seas of Data" (maritime and ports)

Goal: detect ships (and dark vessels) from Sentinel-1 radar with an ML model, show them on a dashboard, and design a monitoring
buoy in CAD. Deliverables: pitch deck + data prototype + CAD file. Submissions close Mon 2 Nov 2026 (check exact cutoff with Tohraan);
finale Wed 4 Nov.

Two humans, two Claude Code agents. Read your area's CLAUDE.md (`ml/`, `dashboard/`, `cad/`) before working.

## Ownership (hard rule: never edit files outside your paths)
| Owner | Agent name | Paths |
|---|---|---|
| Tohraan | ml-agent | `ml/`, `deck/`, `contracts/` |
| Aayush | dash-cad-agent | `dashboard/`, `cad/` |

Anything else at the repo root (`CLAUDE.md`, `README.md`, `scripts/`, `docs/`, `.github/`) is read-only for everyone except Tohraan.
If you need a change outside your paths, open a GitHub issue; do not make the edit.

## Branches and commits (so no work is ever lost)
- Work only on your own branch: `tohraan` or `aayush`. Never commit to `main` directly.
- Commit AND push early and often: after every working step, and at least every ~20 minutes of work. Small commits are fine.
- Use `scripts/save.sh "<message>"`. It stages only your owned paths, commits, and pushes your branch.
- Open a PR into `main` at each milestone. Paths are disjoint, so merges should never conflict. If one does, stop and comment on the issue.

## Communication: GitHub issues and comments
- Tasks live in GitHub issues. Labels: `for:ml-agent`, `for:dash-cad-agent`, `contract-change`, `blocked`.
- At session start and after every milestone, run `gh issue list --label for:<your-agent> --state open` and read new comments.
- Report progress by commenting on the relevant issue: `gh issue comment <n> --body "[<agent>] <what changed, branch, commit, what you need>"`.
- Always prefix comments with your agent tag so humans can tell agents apart.
- Blocked or need something from the other side? Comment on the issue, add the `blocked` label, and keep working on something else.
- The only data interface is `contracts/`. Do not import code across `ml/` and `dashboard/`.

## Style
- Keep it small and working: a demo that runs beats an ambitious one that does not.
- Never commit large data (satellite scenes, model weights >50MB). `.gitignore` already blocks most of it.
- Never commit secrets or passwords. Use environment variables and `.env` (ignored).
