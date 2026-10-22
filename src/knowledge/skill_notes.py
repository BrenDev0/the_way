"""How a skill written for another agent runs with this one's tools.

The kit's skills are written for an agent with a shell: `node render.js`, `curl`, `git`, a
command-line router. Ours has none of those, by design. Read as written, such a skill
sends the agent after a tool it does not have -- and a skill that contradicts the tools
gets dropped, so the agent learns that skills are noise. The note goes ahead of the
skill's own text, so it is read first and on the first page of a long skill.

Keyed by skill name: the note is about our tools, not the skill's method, so it lives
here rather than in the skill text, which stays as its authors wrote it.
"""

HEADER = (
    "=== RUNNING THIS SKILL HERE (read first; where the skill below names a command or a "
    "tool you do not have, this is what to do instead) ==="
)
FOOTER = "=== THE SKILL, AS ITS AUTHORS WROTE IT ==="

NO_SHELL = (
    "You cannot run commands: there is no shell, no node, no python, no curl, and no git "
    "command line. Never claim to have run one."
)

# The desktop app's git tools stand in for the git commands, in the folder the user has open.
GIT_TOOLS = (
    "Git works only through the Git tools, and only in the desktop app, on the folder the "
    "user has open: GitStatus, GitLog, GitDiff, GitShow, GitFetch, GitAdd, GitCommit and "
    "GitPush. If you are not on the desktop app, say the skill cannot run here. If a Git "
    "tool says git is not installed or not set up on the user's computer (no name and email, "
    "no remote, not signed in), tell the user what it says they must do, in their language: "
    "that setup is theirs, and you never ask for a password or token. Never claim a commit "
    "or push happened unless the tool said so."
)

NOTES: dict[str, str] = {
    "output-documents": (
        "- Do not run `node engine/render.js` or set CHROME_PATH. HtmlToPdf is that renderer "
        "here: the same headless Chromium, with this engine's print CSS put in at render time.\n"
        "- Make the HTML with BuildHtmlPage: page_type='report', brand=<the brand's folder in "
        "the library, e.g. 'SLS'> (its tokens.css is layer 2), skill='output-documents' (the "
        "builder then gets engine/core.css and engine/document.TEMPLATE.html as layer 1 and "
        "the template). The source Markdown is layer 3: pass its full text in the brief.\n"
        "- Then convert the same file twice: HtmlToPdf layout='paged' (email, print) and "
        "layout='scroll' (messaging apps). Two PDFs, one source.\n"
        "- Law 3 holds: review the PDFs with ReadPdf, not the HTML.\n"
        "- Law 4 holds: deliver the files in a project; never a link."
    ),
    "landing-pages": (
        "- When the page is for a brand in the library, read its pack BEFORE asking anything: "
        "ReadProjectFile on <brand>/voice.md and <brand>/identity.md in the library project "
        "your context names. The brief's questions on voice, tone and forbidden words are "
        "answered there -- state what the pack says and ask only to confirm, never ask from "
        "scratch.\n"
        "- In that same first message, warn about anything in the user's own request that "
        "the page could not publish: a word the brand's voice.md forbids (quote its rule), "
        "another library brand's name, logo or colours, an unsigned price, a figure with no "
        "source. Propose the fix (for SLS: 'Plan Maestro', not 'cotización') and let them "
        "choose; do not carry it silently into the section list.\n"
        "- Steps 0 (brief) and 1 (structure) end in a gate someone approves. Ask the user "
        "in the conversation, all missing answers in ONE question. A background worker "
        "cannot ask anyone, so close these gates before starting a background task, and "
        "write the answers and the approved section list into its instructions.\n"
        "- Step 3: build with BuildHtmlPage, page_type='landing', skill='landing-pages', "
        "brand=<the library folder> when the page is for one of the brands. The builder "
        "gets laws.md and the brief; pass the answered brief and approved sections in "
        "`brief`.\n"
        "- Step 4: verification.md's `curl` checks (status codes, byte counts, headers) "
        "need a live site and a shell. The builder already measures the page with CheckPage "
        "at 375 px and 1440 px; report that, and say plainly that the live checks are not "
        "run here.\n"
        "- Step 5: The Way does not deploy or host sites. You deliver one self-contained "
        "HTML file in a project. Say that publishing it, and verifying it live, is the "
        "user's step -- never that it is live."
    ),
    "ai-ops-measurement": (
        "- This method needs raw session logs and repository history. You have neither: "
        "no shell, no git, and no access to agents' session transcripts. "
        "SearchConversationHistory finds earlier conversations of this user only; it is "
        "not a log and cannot be counted as one.\n"
        "- Do not estimate any metric this skill names. Tell the user it cannot run here "
        "and what it would need (exported session logs and commit history, uploaded to a "
        "project as files). If they upload them, read them from the project and follow "
        "the method on those files."
    ),
    "content-reverse-engineering": (
        "- Lane A is TranscribeMedia: give it the link to each post (YouTube, TikTok, "
        "Instagram, Facebook, Vimeo, X, LinkedIn...) or a recording in a project. It reads "
        "YouTube's own captions when there are any, and otherwise downloads the audio and "
        "transcribes it with the user's OpenAI key. Each transcript is saved in "
        ".the_way/transcripts/; read it from there instead of fetching it again.\n"
        "- When TranscribeMedia says it could not get one (a platform blocking the server, a "
        "private post, no OpenAI key), fall back to lane B: ask the user to paste the "
        "transcript or attach it. Lane C (WebSearch, ExtractWebPages) works when web search "
        "is connected.\n"
        "- Never pretend a transcript came through when it did not."
    ),
    "signal-extraction": (
        "- 'capture' and 'transcribe' are TranscribeMedia, for a link to a post or a "
        "recording in a project; it keeps each transcript in .the_way/transcripts/ (that "
        "is 'conserve the source'). Where it cannot get one, work from what the user pastes "
        "or attaches, and say which sources you could not reach."
    ),
    "delivery-routing": (
        "- There is no `tool --validate / --route / --report` command here. Do the same "
        "steps with project file tools: ListProjectFolder and ReadProjectFile to diagnose "
        "the intake folder, then report the routing plan (the dry run) before moving "
        "anything.\n"
        "- Move with MoveProjectPath; it asks the user to approve each move, which is the "
        "`--apply` step. Create a missing subfolder (CreateProjectFolder) only inside a "
        "project that already exists, as the skill says.\n"
        "- The intake folder is a folder in one of the user's projects; if none exists, ask "
        "which project holds it."
    ),
    "capture-system": (
        "- A voice memo is transcribed with TranscribeMedia once it is in a project "
        "(project:<project>/<path>); ask the user to upload it if it is only on their phone."
    ),
    "drift-check": (
        f"- {NO_SHELL} {GIT_TOOLS}\n"
        "- The three checks, with the Git tools instead of the commands: GitFetch first "
        "(`git fetch`). 1 uncommitted work: GitStatus. 2 ahead and behind: the first line of "
        "GitStatus after the fetch (`[ahead 2, behind 1]`; no brackets means in step with "
        "the remote; no remote named on that line means the branch tracks nothing, which is "
        "itself a finding). 3 phantom documents: GitStatus with ignored=true, then pick the "
        "lines marked `!!` that are .md, .yaml, .yml or .json files.\n"
        "- There is no exit code or hook here: report the findings, or say there are none."
    ),
    "session-handoff": (
        f"- {NO_SHELL} {GIT_TOOLS}\n"
        "- Step 4 with the Git tools: GitFetch, GitStatus and GitLog (limit 5) are the "
        "`git fetch && git status --short && git log --oneline -5` line. Stage with GitAdd "
        "and the exact paths, never a whole-folder path to sweep everything up; GitShow "
        "(HEAD) is the `git show --stat HEAD` proof that the files match what you touched. "
        "GitCommit with a message, then GitPush: each asks the user to approve, and GitPush "
        "asks every time. If the branch has never been pushed, call it with "
        "set_upstream=true.\n"
        "- If the push is refused because the remote has newer commits, stop and tell the "
        "user: you cannot pull or merge, and nothing was overwritten.\n"
        "- The handoff note is a file: write it with CreateFile and commit it like the rest."
    ),
    "using-this-kit": (
        "- The kit is already mounted for you: its skills are the ones in your skill listing, "
        "and ReadSkill reads them and their reference files. There is no repository or "
        f"skills.json for you to read, and no index to regenerate. {NO_SHELL}"
    ),
}


def note_for(name: str) -> str:
    """The note for a skill, ready to go ahead of its text -- or nothing."""
    note = NOTES.get(name.strip().lower())
    return f"{HEADER}\n{note}\n{FOOTER}\n\n" if note else ""
