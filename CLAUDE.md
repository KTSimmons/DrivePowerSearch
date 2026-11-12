# CLAUDE.md
- created: 2026-11-10

Google Drive search CLI. The spec is `docs/SPEC.md` (v1.3.x); the original idea is in `docs/rough_prompt.md`. Change the spec first (bump its version), then the code, ideally in the same commit.

## Layout
| Path | Contents |
|---|---|
| `drive_search/` | The package (7 modules; `local_search.py` searches the Google Drive for desktop mount, the rest use the Drive API) |
| `tests/` | pytest suite; `tests/fakes.py` is the fake Drive service |
| `docs/` | `SPEC.md`, `rough_prompt.md`, `google_cloud_setup.md` (Drive API credentials guide; keep its error messages in sync with `auth.py`/`cli.py`) |
| `setup/` | `environment.yml` (conda env `powertools`), `requirements.txt` (pip fallback) |
| `pyproject.toml` | pytest settings (stays at the top level) |

## Environment
- Windows 11, PowerShell 5.1 (no `&&`, `||`, `?:`, `??`).
- Anaconda at `C:\ProgramData\Anaconda3\`. conda is NOT on PATH, so call it by full path. Never use conda `base`.
- Conda env: `powertools`, defined in `setup/environment.yml` (conda-forge only).

## Commands
- Tests: `C:\ProgramData\Anaconda3\Scripts\conda.exe run -n powertools python -m pytest`
- Run: `C:\ProgramData\Anaconda3\Scripts\conda.exe run -n powertools python -m drive_search --name <text>`

## Architecture rules (from the spec)
- Only `auth.py` touches credentials, tokens, or OAuth scopes.
- Only `logging_setup.py` configures logging handlers. Other modules use `logging.getLogger(__name__)`. No `print()`: the terminal output goes through rich in `reports.py` and `cli.py`.
- `search.py` and `paths.py` receive the Drive service and never build it, so tests use `tests/fakes.py`.
- At INFO, log counts only, never file names (those go at DEBUG). Never log token contents.
- Tests must make no network calls and must never scan the real Drive for desktop mount (`tests/conftest.py` hides it; local tests use a `tmp_path` fake mount).
- `local_search.py` reads directory listings and file details only. It never opens files (that would trigger downloads) and never hard-codes a drive letter or user path.

## Never commit
`credentials.json`, `token.json`, `logs/`, `search_results/`, `*transcript*` (all in `.gitignore`).
