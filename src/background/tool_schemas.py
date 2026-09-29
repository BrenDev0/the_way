from pydantic import BaseModel, Field


class StartBackgroundTask(BaseModel):
    """Run a long-running task in the background so the conversation can continue.

    Use this for work that spans many operations or would take more than a few seconds --
    bulk lookups, audits, multi-step research, anything that analyses CX data. Do not use
    it for work the user is waiting on right now; answer those directly instead."""

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
    deliver_to_project: str | None = Field(
        default=None,
        description=(
            "Project where the finished files should be delivered, exactly as ListProjects "
            "shows it. The worker always does its work in the '.the_way' workspace, which "
            "the user does not browse; whatever it produces is copied here automatically "
            "the moment the task succeeds. ASK the user where they want it before starting "
            "any task that produces files they will want to see. Leave it unset only for "
            "work with no deliverable."
        ),
    )
    deliver_to_path: str | None = Field(
        default=None,
        description="Folder inside deliver_to_project, for example 'reports'. Created if missing.",
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
