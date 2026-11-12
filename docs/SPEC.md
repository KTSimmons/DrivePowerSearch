# Google Drive File Search Utility: Prompt

| | |
|---|---|
| **Version** | 1.3.1 |
| **Created** | 2026-11-10 |
| **Last updated** | 2026-11-10 |

**Changelog**
- **1.3.1** (2026-11-10): Moved from the Prompt_Engineering repo into `drive_search/docs/SPEC.md` (from Prompt_Engineering commit 27c4c13). No requirement changes.
- **1.3.0** (2026-11-10): The log folder is created on first run, its write access is checked on every run, and there is a fallback location. The default log folder is now next to the utility instead of in the current working directory.
- **1.2.0** (2026-11-10): Added a separate `logging_setup` module that records every operation, plus `--log-level` and `--log-dir` options.
- **1.1.0** (2026-11-10): Moved authentication and authorization into a separate `auth` module.
- **1.0.0** (2026-11-10): First structured version of the rough prompt.

## Goal
Build a Python command-line utility that searches my Google Drive for files by name and creation date. It prints a results report to the terminal and saves the same report as Markdown and HTML files.

## Environment
- Windows 11, PowerShell 5.1, Python 3.11+
- Access Drive through the official **Google Drive API v3** using `google-api-python-client` and `google-auth-oauthlib`.
- Authentication and authorization live in their own module. See the next section.

## Authentication and authorization module (`auth.py`)
Put all sign-in and permission logic in a separate module that the rest of the tool imports. No other module may read credential files, handle tokens, or name OAuth scopes.

- **Public interface:**
  - `get_credentials(credentials_path="credentials.json", token_path="token.json", scopes=DEFAULT_SCOPES) -> google.oauth2.credentials.Credentials`
  - `build_drive_service(credentials) -> Resource`: returns a ready-to-use Drive v3 client.
- **Flow:**
  1. If `token.json` exists and is valid, use it.
  2. If the token has expired but has a refresh token, refresh it silently and save the new token.
  3. Otherwise, run the OAuth 2.0 "Desktop app" flow (`InstalledAppFlow.run_local_server`) with the client secrets in `credentials.json`, then save the resulting token.
- **Scopes:** define `DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]` as a constant in this module. This is the narrowest scope that works. If the saved token was granted different scopes, ask me to sign in again instead of failing with an unclear error.
- **Configurable paths:** let the credential and token paths be overridden by the function arguments or by environment variables (`GDRIVE_CREDENTIALS`, `GDRIVE_TOKEN`), so the files can live outside the project folder.
- **Errors:** raise custom exceptions (`CredentialsNotFoundError`, `AuthenticationError`) with clear messages. Let the CLI decide how to show them, and don't call `sys.exit` inside this module.
- **Security:** never print or log token contents. Write `token.json` only to the configured path. Add `credentials.json` and `token.json` to `.gitignore`.
- **Reuse:** the module must not depend on the search or report code, so it can be reused in other Google Drive tools.

## Logging module (`logging_setup.py`)
Keep a record of every operation the tool performs. Put all logging configuration in one module, built on Python's standard `logging` library (no third-party logging packages).

- **Public interface:** `setup_logging(level="INFO", log_dir=None, verbose=False) -> str`. `None` means use the default log folder. It configures logging once, at program start, and returns a short **run ID**, for example the first 8 characters of a UUID.
- **How other modules log:** every module gets its own logger with `logger = logging.getLogger(__name__)`. No module except `logging_setup.py` adds handlers, sets formats, or calls `logging.basicConfig`. Use `logger` instead of `print` for everything except the report itself.
- **Handlers:**
  - **File:** `drive_search.log` in the log folder, UTF-8. Use a `RotatingFileHandler` (1 MB per file, keep 5 backups) so logs don't grow forever. The folder is prepared as described in "Log folder setup" below.
  - **Console:** writes to stderr so it never mixes with the report on stdout. It shows `WARNING` and above by default, or `INFO` and above with `--verbose`.
- **Format:** `2026-11-10T14:32:05.123-05:00 | INFO | run=3f9a1c2e | drive_search | Page 2 returned 100 files`. That is a local ISO 8601 timestamp with the time zone offset, then the level, run ID, module name, and message. Include the run ID on every line (use a `logging.Filter`) so you can find all the lines from one run.
- **What to log:**

  | Level | Events |
  |---|---|
  | `INFO` | Program start (tool version, Python version, search arguments) and end (exit code, total duration). Auth steps: cached token used, token refreshed, or browser sign-in started/completed. Each API page requested (query string, page number, number of files returned, time taken). Total matches. Each report file written (absolute path). |
  | `DEBUG` | Individual file names and IDs returned. Folder lookups during path rebuilding, with cache hits and misses. Full API request parameters. |
  | `WARNING` | Retries after rate limits (attempt number and wait time). Paths that couldn't be resolved. Saved token with different scopes. |
  | `ERROR` | Any failure that stops the run, with the full traceback (`logger.exception`) in the log file only. |

- **Privacy and security:** never log tokens, refresh tokens, client secrets, or the contents of `credentials.json` or `token.json`. File names are personal data, so log them only at `DEBUG`. At `INFO`, log only counts. Add `logs/` to `.gitignore`.
### Log folder setup (first run and every run)
The log folder must exist and be writable before the tool does anything else, including signing in or reading arguments beyond `--log-dir`, `--log-level`, and `--verbose`.

1. **Default location:** a `logs` folder next to the utility's own files, found with `Path(__file__).resolve().parent`, not the current working directory. That way the logs end up in the same place no matter which folder I run the tool from. `--log-dir` overrides this.
2. **First run:** create the folder and any missing parent folders (`Path.mkdir(parents=True, exist_ok=True)`). Running the tool again, or two copies at the same time, must not fail because the folder already exists.
3. **Every run, check write access:** create and then delete a small test file in the folder. Don't rely on the folder merely existing, because a folder can exist and still be read-only, locked by sync software such as OneDrive, or have changed permissions.
4. **Fallback location:** if step 2 or 3 fails, use `%LOCALAPPDATA%\DriveSearch\logs` on Windows, or `~/.drive_search/logs` if `LOCALAPPDATA` isn't set. Create and check it the same way, and print a one-line warning naming both the folder that failed and the fallback in use.
5. **Last resort:** if the fallback also fails, log to the console only, print a clear warning, and carry on with the search. Logging problems must never stop a search.
6. **Record the result:** once the handlers are attached, log at `INFO` which folder is in use. On first run, add "Created log folder at <path>". Logging isn't running when the folder is created, so hold that message until the handlers are ready.
7. **Report the folder:** `setup_logging` makes the folder actually in use available to the rest of the tool, for example as part of a small result object alongside the run ID. Error messages and `--verbose` output then show the real log path, not the requested one.

## Inputs (command-line arguments via `argparse`)
| Argument | Required | Meaning |
|---|---|---|
| `--name TEXT` | Yes | Text to match against the file name |
| `--exact` | No | Match the whole name exactly. Without it, find names that *contain* TEXT (case-insensitive) |
| `--created-on YYYY-MM-DD` | No | Only files created on this calendar date |
| `--created-after YYYY-MM-DD` / `--created-before YYYY-MM-DD` | No | Inclusive date range. Can't be combined with `--created-on` |
| `--include-shared-drives` | No | Also search shared drives, not just My Drive |
| `--output-dir PATH` | No | Where to save reports. Default: `./search_results` |
| `--log-level LEVEL` | No | How much detail goes in the log file: `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Default: `INFO` |
| `--log-dir PATH` | No | Where to save log files. Default: a `logs` folder next to the utility's own files (see "Log folder setup") |
| `--verbose` | No | Also show `INFO` log messages in the terminal. Without it, the terminal shows only warnings and errors |

Validate the inputs. Reject bad dates, `--created-on` combined with a range, and an "after" date that comes later than the "before" date. Each error should print a clear message and exit with a non-zero code.

## Search behavior
- Build the query with the Drive API `q` parameter (`name contains '...'`, `createdTime >= '...'`). Escape quotes in user input.
- Treat dates in my **local time zone** and convert them to UTC (RFC 3339) for the API.
- Exclude trashed files (`trashed = false`). Include folders and Google Docs/Sheets/Slides as well as uploaded files.
- Handle pagination (`nextPageToken`) so every match is returned, not just the first page.
- **Full path:** Drive has no real paths. Rebuild one by walking each file's `parents` up to the root, for example `My Drive/Projects/2026/report.pdf`. Cache folder lookups to avoid repeated API calls. If a file has several parents, show the first one. If the path can't be resolved (for example, a file shared with me whose parent I can't see), show `(shared with me)/<name>`.
- Sort results by creation date, newest first.

## Report content (same in all three outputs)
1. Title: "Google Drive Search Report"
2. Search terms used: every argument and its value, including defaults
3. Report run date and time: local time, ISO 8601 format, with the time zone offset
4. Total number of files found
5. Results table with these columns, in this order:
   - File name
   - Created (local time, `YYYY-MM-DD HH:MM`)
   - Modified (local time, `YYYY-MM-DD HH:MM`)
   - Full path
6. If nothing matches, show "No files found" instead of an empty table.

## Outputs
- **Terminal:** a readable aligned table (use `tabulate` or `rich`). Shorten long paths if needed so the table fits.
- **Markdown:** a valid GitHub-flavored Markdown table. Escape `|` characters in file names.
- **HTML:** a single self-contained page (inline CSS, no external dependencies) with a styled, readable table. The **full path is a hyperlink** to the file's Drive `webViewLink` and opens in a new tab. HTML-escape every value taken from Drive.
- File names: `drive_search_<YYYYMMDD_HHMMSS>.md` and `.html`, so earlier reports are never overwritten. Create the output folder if it doesn't exist.
- After saving, print the absolute paths of both report files.

## Error handling
Show friendly messages, not raw tracebacks, for these cases: `credentials.json` missing, authentication failed or was cancelled, network/API errors (retry rate-limit errors with backoff), and an output folder that can't be written to. Write the full traceback to the log file, and end the terminal message with the log file path, for example "See logs/drive_search.log for details."

## Code structure
Keep the parts separate so each can be tested on its own:

| Module | Responsibility |
|---|---|
| `auth.py` | Credentials, tokens, scopes, and building the Drive client (see above) |
| `logging_setup.py` | Setting up logging once: handlers, format, rotation, run ID (see above) |
| `cli.py` | Argument parsing, input checks, calling `setup_logging` first, and turning exceptions into friendly messages and exit codes |
| `drive_search.py` | Building the query, calling the API, and pagination. Receives a Drive service object and never creates one itself |
| `paths.py` | Rebuilding full paths from parent folders, with caching |
| `reports.py` | Rendering the terminal, Markdown, and HTML outputs |

The search module receives the Drive service as an argument (dependency injection). This makes it easy to pass in a mock during tests. Add type hints and short docstrings.

## Deliverables
1. The script (or a small package) with a clear entry point, for example `python drive_search.py --name budget --created-after 2026-01-01`
2. `requirements.txt`
3. `README.md` with step-by-step Google Cloud setup (enable the Drive API, create OAuth desktop credentials, download `credentials.json`), install steps, and usage examples
4. `pytest` unit tests for query building, date validation and conversion, and Markdown/HTML rendering, including escaping and the "no results" case. Use a mocked Drive service so the tests make no network calls.
5. `pytest` unit tests for `auth.py` with the Google auth library mocked. Cover four cases: a valid cached token, an expired token that gets refreshed, no token (the sign-in flow runs), and a missing `credentials.json`.
6. `pytest` unit tests for logging, using `caplog` and a temporary folder. Check that:
   - the log file is created with the expected line format and run ID
   - console output respects `--verbose`
   - a missing log folder, including missing parent folders, is created on first run
   - a second run with the folder already in place works and adds to the same log file
   - an existing but read-only log folder switches to the fallback location, with a warning
   - if both the main and fallback folders fail, logging continues on the console only and the search still runs
   - no token or secret values appear in the log, even when auth fails

## Acceptance criteria
- A search with known matches returns every one of them, including results beyond the first API page.
- All three outputs show the same search terms, run timestamp, count, and rows.
- Every path link in the HTML report opens the correct file in Drive.
- Running the tool twice produces two separate report pairs.
- Only `auth.py` reads credential or token files. A search for `credentials.json`, `token.json`, and scope URLs finds them in no other module.
- After the first sign-in, later runs don't open a browser until the token is revoked or the scopes change.
- On a fresh copy with no `logs` folder, the first run creates it next to the utility and logs "Created log folder at <path>". This works the same whichever folder I run the tool from.
- Each run adds one start line and one end line to `drive_search.log`, sharing the same run ID. Every API page, auth step, and report write in between is logged at `INFO`.
- At the default `INFO` level, the log contains no file names. At `DEBUG`, it does.
- Only `logging_setup.py` configures logging handlers. A search for `basicConfig`, `addHandler`, and `print(` finds none elsewhere, except `print` calls that output the report.
- `pytest` passes.

## Out of scope
Downloading or changing files, searching file contents, and a GUI.

## Before writing code
If any requirement is ambiguous or conflicts with how the Drive API works, list your questions or assumptions first, then continue.
