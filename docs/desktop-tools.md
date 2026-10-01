# Desktop tools: the contract

The assistant runs on the server. Some of what it does can only happen on the user's own
machine — reading their files, driving their browser, uploading a folder. Those tools are
**offered to the model by the server but carried out by the desktop app**. This document is
what the desktop app has to implement.

The schemas live in `src/desktop/schemas.py`; approval flags in `src/desktop/tools.py`.
Those two files are the source of truth — if this document and they disagree, they win.

## Signing in

Every call below goes to `/api/desktop/v1` with `Authorization: Bearer <token>`. There is
no request signature on this prefix, and it never accepts a cookie.

- `POST /api/desktop/v1/auth/login` with `{"email", "password", "deviceName"}` returns
  `{"token", "expiresAt", "user"}`. The token is shown once; store it encrypted with
  Electron's `safeStorage`, in the main process only.
- Each request pushes the expiry 30 days out, so a device in use stays signed in.
- A `401` means the token is gone (signed out, revoked, expired, user removed): drop it
  and show the sign-in screen. A `429` on login means too many failed attempts.
- `POST /api/desktop/v1/auth/logout` revokes the token. `GET /api/desktop/v1/auth/sessions`
  and `DELETE /api/desktop/v1/auth/sessions/{id}` list and sign out the user's devices.

## The round trip

1. Create a conversation with `client: "desktop"` (the default). A `"web"` conversation is
   never offered desktop tools.

   `POST /api/desktop/v1/conversations` → `{"title": "...", "client": "desktop"}`

2. Send a message. The worker starts the turn.

   `POST /api/desktop/v1/conversations/{id}/messages` → `{"message": "..."}`

3. Follow the conversation's event stream, `GET /api/desktop/v1/conversations/{id}/events`
   (server-sent events, same bearer token). It opens with a `status` event holding the
   conversation exactly as `GET .../{id}` returns it, then relays, as they happen:

   | event | data |
   |---|---|
   | `status` | the conversation, sent whenever the turn's state is saved |
   | `text` | `{text}` — a piece of the assistant's reply as the model writes it |
   | `message` | a message the turn added (assistant with any `toolCalls`, or a clipped tool result) |
   | `tool.started` / `tool.finished` | `{id, name, args}` / `{id, name, failed}` for server-side tools |
   | `task.started` / `task.finished` | `{taskId, description}` / `{taskId, description, status}` for a background task this conversation started |

   Some server tools run an assistant of their own: `BuildHtmlPage` (a designer, then a
   builder) and `BuildSkill`. Their tool calls are published too, with **`parentId`**, the id of the
   call they run inside, so show them as steps of that call. Their text is not streamed:
   it's working-out for the tool, not the reply. A background task's tool calls carry
   **`taskId`** instead. It runs after the turn ends, so they only reach a client that keeps
   the stream open.

   Every relayed event carries an `id`. After a dropped connection, reconnect with
   `Last-Event-ID: <last id seen>` and nothing is missed. A `: keep-alive` comment goes out
   after 15 quiet seconds, so silence longer than that means the connection is dead. The
   server ends each stream after 30 minutes; reconnect the same way. A `status` event is
   only sent once its state is committed, so answering an `awaiting_client` right away is
   safe. Act on the `status`:

   | status | meaning |
   |---|---|
   | `idle` | the turn finished; read `GET .../messages` |
   | `awaiting_client` | the turn is paused on `pendingToolCalls` — see below |
   | `failed` | the turn failed (no AI key, step limit, server error) |

4. When `awaiting_client`, every entry in `pendingToolCalls` needs an answer:

   ```json
   {
     "id": "call_abc",
     "name": "ReadFile",
     "args": {"file_path": "notes/todo.md"},
     "location": "desktop",
     "requiresApproval": false,
     "detail": null
   }
   ```

   - **`location: "desktop"`** — the app runs it. If `requiresApproval` is true, ask the user
     first. Answer with the output, or with a refusal.
   - **`location: "server"`** — the app does *not* run anything. These always have
     `requiresApproval: true` (editing or deleting a project file, saving a preference or a
     skill). Show `name`, `args` and `detail`, and answer with the user's decision.

5. Post **all** answers in one request. A partial answer is refused with
   `tool_calls_unresolved`.

   `POST /api/desktop/v1/conversations/{id}/tool-results`

   ```json
   {
     "resolutions": [
       {"toolCallId": "call_abc", "approved": true, "output": "- buy milk\n- call Ana"},
       {"toolCallId": "call_def", "approved": true, "output": "FileNotFoundError: x.md", "failed": true},
       {"toolCallId": "call_ghi", "approved": false, "feedback": "archive it instead of deleting"}
     ]
   }
   ```

   | field | rule |
   |---|---|
   | `approved: true` on a desktop call | `output` is required — what running it produced. `""` is a valid output. |
   | `failed: true` | the tool ran and errored; put the error text in `output`. The model is told it failed. |
   | `approved: false` | the user refused; nothing ran. `feedback` is optional and the model is told to follow it instead of retrying. |
   | `output` on a server call | refused with `tool_call_output_not_expected` |

6. The server answers `202` with the conversation back in `running`; keep following the stream (reopen it with `Last-Event-ID` if you closed it while answering).
   One turn can pause several times.

Outputs are capped at 60,000 characters on the server; send the full output and let it
truncate, rather than truncating silently on the client.

## The tools

Every local path is **relative to the folder the user has open in the app**. The app must
resolve each path against that folder and **refuse anything that escapes it** (`..`,
absolute paths, symlinks out). Return that refusal as a failed output, never run it.

### Local files

| tool | args | approval | notes |
|---|---|---|---|
| `ReadFile` | `file_path` | – | Text only. Reading a directory is an error that lists its entries. A file with null bytes in its first 4 KB is binary — refuse, do not decode garbage. |
| `ListDir` | `dir_path="."` | – | Folders first with a trailing `/`, then `name  (1,234 bytes)`. `(empty directory)` when empty. |
| `SearchFile` | `file_name`, `base_dir="."` | – | Every word of the query must appear somewhere in the relative path. Skip `.venv venv env node_modules __pycache__ .git .mypy_cache .pytest_cache .ruff_cache dist build .idea .vscode .next target`. Best hits first (words in the file name beat words in a parent folder), cap at 50 and say how many more. |
| `SearchCode` | `pattern` (regex), `base_dir="."`, `file_glob`, `case_sensitive=false`, `files_only=false` | – | Lines as `path:line: text`. Same skipped folders; skip binaries and files over 2 MB. Cap 100 lines overall and 10 per file; cut lines at 200 chars. **End with the true total** (`N matching lines in M files (searched K)`) even when the listing was cut short. |
| `CreateDir` | `dir_path` | – | Creates parents. |
| `CreateFile` | `file_path`, `content=""`, `overwrite=false` | – | Refuse an existing file unless `overwrite`. Creates parents. |
| `UpdateFile` | `file_path`, `old_string`, `new_string`, `replace_all=false` | **yes** | `old_string` must occur; if it occurs more than once and not `replace_all`, refuse and say how many times. Show the user the diff in the approval. |
| `CopyPath` | `source`, `destination`, `overwrite=false` | – | A file copied onto an existing folder lands inside it under its own name. Refuse copying a folder into itself. |
| `MovePath` | `source`, `destination`, `overwrite=false` | **yes** | Same conventions as `CopyPath`. Refuse moving the open folder itself. |
| `RenamePath` | `path`, `new_name` | **yes** | Same folder, new name. `new_name` is a name, not a path. Refuse when the name is taken (a case-only change is fine) and refuse the open folder itself. |
| `DeleteFile` | `file_path` | **yes** | Refuse a directory (point to `DeleteDir`). |
| `DeleteDir` | `dir_path`, `recursive=false` | **yes** | Non-recursive refuses a non-empty folder. Refuse the open folder itself. |

**Line endings.** Read every file with line endings collapsed to `\n` (a run of `\r` before
`\n` counts as one — that repairs files damaged by earlier Windows round trips), and write
with `\n` and no translation. Otherwise an `UpdateFile` whose `old_string` uses `\n` never
matches a file stored with `\r\n`, and every edit adds another `\r`. Decode as UTF-8 (strip a
BOM), UTF-16 when it starts with a BOM, then cp1252, then latin-1.

### Between the computer and the user's projects

| tool | args | approval | notes |
|---|---|---|---|
| `UploadToProject` | `local_path`, `project`, `destination_path="."` | **yes** | A file or a whole folder, skipping the build folders above. Use the projects API: `POST /projects/{id}/files` for an upload URL, `PUT` the bytes with the same `Content-Type`, then `POST .../complete`. Resolve `project` by name from `GET /projects`. Suggested caps: 500 files, 512 MB per call. |
| `DownloadFromProject` | `project`, `path`, `local_path="."`, `overwrite=false` | **yes** | Use `GET /projects/{id}/tree` to find the entries and `GET .../files/{fileId}/download` for each URL. Refuse to overwrite local files unless `overwrite`. |

### The user's browser

A real, visible browser window with its own persistent profile, so signed-in sessions
survive between runs (the command-line assistant kept it in `~/.the_way/browser`). Page
text returned to the model should be the visible text, trimmed to a sensible size.

| tool | args | approval | notes |
|---|---|---|---|
| `OpenBrowserPage` | `url` | – | Open and return the visible text. |
| `ReadBrowserPage` | – | – | Re-read the current page. |
| `ClickBrowserElement` | `text` | **yes** | First button or link whose visible text contains `text`. |
| `TypeInBrowser` | `text`, `then_enter=false` | **yes** | Types into the focused field. |
| `ListBrowserTabs` | – | – | Title and URL of every tab. |
| `SwitchBrowserTab` | `match` | – | First tab whose title or URL contains `match`; return its text. |
| `CloseBrowser` | – | – | Sessions are kept. |
| `FindWhatsappChat` | `name` | – | Chat names exactly as WhatsApp shows them. |
| `ReadWhatsappChat` | `name`, `limit=15` | – | Open the chat, **check the header matches** before reading, mark each line with who sent it. |
| `SendWhatsappMessage` | `to`, `message` | **yes** | `to` is a full international number (open via URL — cannot land on the wrong chat) or an exact chat name from `FindWhatsappChat`. Verify the open chat's header is exactly `to` before typing; if not, refuse. One message per call. Show the chat name and the full message in the approval. |

## What runs on the server instead

For reference — these need no desktop code. The server runs them, and only the ones marked
"approval" come back to the client as `location: "server"` calls to approve.

| group | tools | approval |
|---|---|---|
| knowledge | `ReadKnowledgeDocument`, `ReadSkill` | – |
| projects | `ListProjects`, `CreateProject`, `ListProjectFolder`, `FindProjectFiles`, `ReadProjectFile`, `WriteProjectFile`, `CreateProjectFolder`, `CopyProjectPath` | – |
| projects | `EditProjectFile`, `MoveProjectPath`, `RenameProjectPath`, `DeleteProjectPath` | yes |
| CX (needs a GoHighLevel key) | `SearchCXOperations`, `DescribeCXOperation`, `ExecuteCXOperation`, `FetchCXDataset`, `QueryCXDataset` | – |
| web (needs a Tavily key) | `WebSearch`, `MapWebPages`, `ExtractWebPages`, `CrawlWebPages`, `WebResearch` | – |
| pages | `BuildHtmlPage`, `HtmlToPdf`, `HtmlToPng` | – |
| PDF and image edits | `ReadPdf`, `EditPdfPages`, `MergePdfs`, `PdfToImages`, `ImagesToPdf`, `InspectImage`, `TransformImage`, `AddTextToImage`, `OverlayImage` | – (each writes a new file; replacing one takes `overwrite`) |
| images (needs an OpenAI key) | `GenerateImages`, `EditImage` | **always**, even in background tasks (they pause until answered, up to 7 days); the approval carries `choices.model` and the answer `args.model` |
| background | `StartBackgroundTask`, `CheckBackgroundTask`, `DeliverTask` | – |
| memory | `SearchConversationHistory` | – |
| memory | `RememberPreference` | yes |
| skills (owners and admins) | `BuildSkill` | yes |

Background tasks run on the worker while the conversation continues. Show them from
`GET /api/desktop/v1/background-tasks`; a finished one is also relayed in the conversation's next
reply. Saved preferences are listed and removable at `GET/DELETE /api/desktop/v1/preferences`.
