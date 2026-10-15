from pydantic import BaseModel, Field


class StartBackgroundTask(BaseModel):
    """Run a long-running task in the background so the conversation can continue.

    Use this for work that spans many operations or would take more than a few seconds --
    bulk lookups, audits, multi-step research, anything that analyses CX data -- and for
    anything the user asks to run in the background ("en segundo plano", "en segunda
    capa", "en el fondo", "in the background"), however quick. Otherwise, do not use it
    for work the user is waiting on right now; answer those directly instead."""

    description: str = Field(
        description="Short label for the task, shown to the user while it runs, for example "
        "'Audit all contacts for missing email addresses'"
    )
    instructions: str = Field(
        description=(
            "Complete, self-contained instructions for the background worker. The worker "
            "starts with a fresh context and cannot see this conversation, so restate "
            "everything: the subject and scope, plus any constraint established earlier -- "
            "the language to write in, tone, target audience, output format, length, and "
            "which files or records to use. If the user has been writing in a language "
            "other than English, state that language explicitly."
        )
    )
    skills: list[str] | None = Field(
        default=None,
        description=(
            "The organization skills this work falls under, by name exactly as your skill "
            "listing gives them. The worker is told to read each one in full and follow it "
            "before it starts. Pass every skill that matches the request; leave it out only "
            "when none does. Anything a skill needs the user to decide (a brief, an approval) "
            "must be settled with them first and written into the instructions -- the worker "
            "cannot ask."
        ),
    )
    deliver_to_project: str | None = Field(
        default=None,
        description=(
            "Project where the finished files should be delivered, exactly as ListProjects "
            "shows it. The worker always does its work in the '.the_way' workspace, which "
            "the user does not browse; whatever it produces is copied here automatically "
            "the moment the task succeeds. Set it ONLY when the user said where they want "
            "this, or a standing preference names a place. Left unset, the files go to the "
            "'Borradores' (drafts) project, in a folder named after the task -- do not ask "
            "the user where to put things."
        ),
    )
    deliver_to_path: str | None = Field(
        default=None,
        description=(
            "Folder inside deliver_to_project, for example 'reports'. Created if missing. "
            "To revise a file delivered earlier, give that file's project and folder so the "
            "revision replaces it."
        ),
    )


class CheckBackgroundTask(BaseModel):
    """Check the status and result of a background task by its id."""

    task_id: str = Field(description="Task id returned by StartBackgroundTask")


class DeliverTask(BaseModel):
    """Copy a finished background task's files out of the '.the_way' workspace and into a
    project folder the user can open.

    Use this whenever the user asks for a task's output to be moved, copied, or put
    somewhere -- it looks the task folder up by id and copies the bytes, rather than
    re-creating files from content you would have to remember. Never satisfy 'move the
    files' by reading them and calling WriteProjectFile."""

    task_id: str = Field(description="Task id from StartBackgroundTask or the completion notice")
    project: str = Field(description="Project to copy the files into")
    path: str = Field(default=".", description="Folder inside the project. Created if missing.")
