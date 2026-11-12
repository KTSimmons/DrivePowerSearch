# Google Cloud Setup for DrivePowerSearch

| | |
|---|---|
| **Version** | 1.0.0 |
| **Created** | 2026-11-11 |
| **Last updated** | 2026-11-11 |
| **Applies to** | DrivePowerSearch v0.1.0 (`drive_search` package), spec v1.3.1 |
| **Time needed** | About 15 minutes, done once |
| **Cost** | Free. No billing account or credit card is needed for the Drive API |

**Changelog**
- **1.0.0** (2026-11-11): First version.

---

## What you're setting up, and why

DrivePowerSearch reads your Drive through Google's official **Drive API**. Google only allows that if:

1. A **Google Cloud project** exists to own the app.
2. The **Google Drive API** is turned on in that project.
3. An **OAuth consent screen** describes the app and lists who may use it.
4. An **OAuth client** ("Desktop app") gives the tool its identity. You download this as **`credentials.json`**.

The first time you run the tool, you sign in through your browser and approve **read-only access to file details** (names, dates, folders). The tool saves that approval as **`token.json`**, so later runs don't need the browser.

| File | What it is | Where it goes | Share or commit it? |
|---|---|---|---|
| `credentials.json` | The app's identity (client ID and secret) | `DrivePowerSearch\credentials.json` | **Never** |
| `token.json` | Your saved sign-in | Created by the tool, next to `credentials.json` | **Never** |


Both names are already in `.gitignore`.

> **Path placeholders:** `{PATH_PREFIX}` is the folder that contains this repository (for example `C:\Users\<you>\Documents\<projects>`), and `{USER_ACCOUNT}` is your Windows user folder (the same as `%USERPROFILE%`). Your real values are in the untracked `.env` file. Replace the placeholders with them when you copy a command.

> **Google renames menu items now and then.** If a label below doesn't match exactly, look for the closest equivalent. The order of the steps stays the same. These steps match the console as of November 2026, where OAuth settings live under **Google Auth Platform**.

---

## Step 1: Sign in to Google Cloud Console

1. Open <https://console.cloud.google.com/> in your browser.
2. Sign in with **the Google account whose Drive you want to search**. A personal Gmail account works.
3. First visit only: choose your country, accept the **Terms of Service**, and click **Agree and continue**. Ignore any offer of a free trial. You don't need it, and you don't need to enter a credit card.

## Step 2: Create a project

1. At the top left, click the **project picker**. It shows "Select a project" or the name of an existing project.
2. In the dialog, click **New project** (top right).
3. Fill in:
   - **Project name:** `DrivePowerSearch`
   - **Location / Organization:** leave it as **No organization**. That's normal for a personal account.
4. Click **Create** and wait about 10–30 seconds for the notification.
5. Open the project picker again and **select `DrivePowerSearch`**. Check that its name now shows at the top of the page. **Every following step must happen inside this project.**

## Step 3: Turn on the Google Drive API

1. Open the menu **☰** (top left) → **APIs & Services** → **Library**.
2. In the search box, type **Google Drive API** and press Enter.
3. Click the **Google Drive API** result (published by Google Enterprise API).
4. Click **Enable**.
5. You'll land on the API's overview page. Check that it shows **Disable API** or "API enabled". That confirms it's on.

## Step 4: Set up the OAuth consent screen

This is the screen you'll see when you sign in. It says which app is asking for access.

1. Open the menu **☰** → **APIs & Services** → **OAuth consent screen**. This opens **Google Auth Platform**.
2. Click **Get started**.
3. **App information:**
   - **App name:** `DrivePowerSearch`
   - **User support email:** choose your email from the list.
   - Click **Next**.
4. **Audience:** select **External**, then click **Next**.
   *(Choose **Internal** only if you use a Google Workspace work or school account and only people in that organization will use the tool. Personal Gmail accounts must choose External.)*
5. **Contact information:** enter your email address, then click **Next**.
6. **Finish:** tick the box agreeing to the **Google API Services User Data Policy**, click **Continue**, then click **Create**.

## Step 5: Add yourself as a test user

New apps start in **Testing** mode. In Testing mode, only people listed as test users can sign in, so this step is required.

1. In the Google Auth Platform menu on the left, click **Audience**.
2. Check that **Publishing status** says **Testing**. Leave it that way for now (see "Testing vs In production" below).
3. Under **Test users**, click **+ Add users**.
4. Enter **the same Google account email you'll search with**, then click **Save**.

## Step 6: Register the permission the tool asks for (recommended)

The tool asks for one permission when you sign in: read-only access to file details. Listing it here keeps the app's settings accurate and makes the consent screen clearer.

1. In the left menu, click **Data Access**.
2. Click **Add or remove scopes**.
3. In the filter box, type `drive.metadata.readonly`.
4. Tick the row for **`.../auth/drive.metadata.readonly`** ("See information about your Google Drive files").
5. Click **Update**, then click **Save** at the bottom of the page.

> Google classes this as a **restricted** permission. That's fine for a personal app in Testing mode. It only matters if you publish the app for other people (see below).

## Step 7: Create the OAuth client and download `credentials.json`

1. In the left menu, click **Clients**.
2. Click **+ Create client**.
3. **Application type:** choose **Desktop app**. This matters: a "Web application" client won't work with this tool.
4. **Name:** `DrivePowerSearch CLI`
5. Click **Create**.
6. A dialog shows the **Client ID** and **Client secret**. Click **Download JSON** **now**.
   > **Important:** Google may show the client secret **only once**, when the client is created. If you close the dialog without downloading, you'll need to add a new secret to the client, or delete it and create another.
7. Your browser saves a file named like `client_secret_123456789-abc....apps.googleusercontent.com.json`, usually in **Downloads**.

## Step 8: Put `credentials.json` where the tool expects it

1. **Rename** the downloaded file to exactly **`credentials.json`**.
   *(If Windows hides file extensions, make sure you don't end up with `credentials.json.json`. In File Explorer, turn on View → Show → **File name extensions**.)*
2. **Move** it to the project folder:
   ```
   {PATH_PREFIX}\DrivePowerSearch\credentials.json
   ```
3. **Check that git will never commit it.** In a terminal inside the project folder, run:
   ```
   git check-ignore -v credentials.json
   ```
   It should print a line naming `.gitignore`. If it prints nothing, **stop** and fix `.gitignore` before committing anything.

**Optional: keep the secret outside the project folder.** You can store the file anywhere and point the tool to it with an environment variable. In PowerShell, for the current session:
```powershell
$env:GDRIVE_CREDENTIALS = "{USER_ACCOUNT}\.secrets\drivepowersearch\credentials.json"
$env:GDRIVE_TOKEN       = "{USER_ACCOUNT}\.secrets\drivepowersearch\token.json"
```
To make the setting permanent, open the Start menu, search for **"Edit environment variables for your account"**, and add both variables there.

## Step 9: First run and sign-in

1. Open **Anaconda Prompt** and run:
   ```
   conda activate powertools
   cd "{PATH_PREFIX}\DrivePowerSearch"
   python -m drive_search --name report --verbose
   ```
   Replace `report` with a word you know appears in one of your file names.
2. Your browser opens a Google sign-in page. If it doesn't, copy the long URL the terminal prints and paste it into your browser.
3. **Choose the account** you added as a test user.
4. **"Google hasn't verified this app":** this is expected for your own app in Testing mode.
   - Click **Continue**.
   - If you only see **Back to safety**, click **Advanced** first, then **Go to DrivePowerSearch (unsafe)**. "Unsafe" here just means Google hasn't reviewed the app. It's your own app.
5. **Permission screen:** it should ask only to **"See information about your Google Drive files"**. Click **Continue** (or **Allow**).
6. The browser shows **"The authentication flow has completed. You may close this window."** Close the tab.
7. Back in the terminal, the search runs and prints the report. With `--verbose`, you'll see messages such as `Browser sign-in completed` and `Saved sign-in token to ...\token.json`.

## Step 10: Check that it worked

- [ ] The terminal shows the report tables, and then lines for the **Markdown report** and **HTML report** files it saved.
- [ ] `search_results\` contains a new `drive_search_<date>_<time>.md` and `.html`.
- [ ] Opening the `.html` report and clicking a path opens that file in Google Drive.
- [ ] `token.json` now exists next to `credentials.json`, and `git check-ignore -v token.json` reports it as ignored.
- [ ] Running the same command again does **not** open the browser.
- [ ] `git status` doesn't list `credentials.json` or `token.json`.

---

## Testing vs In production (the 7-day sign-in)

| | **Testing** (where you are now) | **In production** |
|---|---|---|
| Who can sign in | Only the test users you listed | Any Google account |
| Saved sign-in (`token.json`) | **Expires after 7 days.** The tool then opens the browser again, which takes about 30 seconds | Lasts until you revoke it |
| "Unverified app" screen | Shown | Shown, unless Google verifies the app |
| Google review needed | No | Required only if the app is for the public. Apps for personal use with restricted permissions can stay unverified, with a limit of 100 users |

**Recommendation:** stay in **Testing**. Signing in again once a week is the price of not dealing with Google's review process. If the weekly sign-in becomes annoying, open **Audience** → **Publish app**. If Google then asks you to submit the app for verification, just move it back to Testing.

---

## Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| `ERROR: OAuth client file not found: ...credentials.json` (exit code 3) | The file is missing, misnamed, or in the wrong folder | Repeat Step 8. Check for `credentials.json.json`. If you set `GDRIVE_CREDENTIALS`, check that path |
| Browser: **"Error 403: access_denied"** or **"…has not completed the Google verification process"** | Your account isn't a test user | Step 5: add the exact email you're signing in with |
| `Google Drive rejected the search request (HTTP 403)`, and the log mentions `accessNotConfigured` or "API has not been used in project" | The Drive API is off, or is on in a different project | Step 3, making sure the right project is selected at the top. Allow a few minutes after enabling it |
| Browser: **"Error 400: redirect_uri_mismatch"** | The client was created as **Web application** | Step 7 again, choosing **Desktop app** |
| Browser: **"Error 401: invalid_client"** | `credentials.json` is from a deleted client, or was edited | Download a fresh JSON (Step 7) |
| `Saved sign-in token could not be refreshed ... signing in again` | Normal after 7 days in Testing, or after you revoked access | Sign in when the browser opens. Nothing to fix |
| `Google sign-in failed or was cancelled` (exit code 3) | You closed the browser tab or clicked Cancel | Run the command again and complete the sign-in |
| The browser doesn't open | No default browser set, or a remote session | Copy the URL the terminal prints into your browser |
| The sign-in page loads, then fails to reach `localhost` | Firewall or antivirus blocking local connections | Allow Python to accept local connections, then try again |
| The search runs but finds nothing you expected | Google's "contains" matching only checks the **start of words** | Search for the start of a word (`budg`, not `dget`). See README "Known limitations" |

When in doubt, read `logs\drive_search.log`. Every run is labeled with a `run=xxxxxxxx` ID, and the full error details are there.

---

## Security and housekeeping

- **Never** commit, email, upload, or paste `credentials.json` or `token.json` anywhere, including into AI chats. Anyone with both files can read your Drive file details.
- **Revoke the tool's access at any time:** go to <https://myaccount.google.com/permissions>, choose **DrivePowerSearch**, then **Delete all connections**. Then delete `token.json`, and the tool will ask you to sign in again.
- **If `credentials.json` leaks:** in Google Cloud Console → Google Auth Platform → **Clients**, open the client, add a new secret, and delete the old one. Or delete the client and redo Step 7. Then revoke access as above.
- **Least privilege:** the tool asks only for `drive.metadata.readonly`. It **can't** open, download, change, or delete your files. If a sign-in ever asks for more than "See information about your Google Drive files", stop and investigate.
- **Cleanup:** to remove everything, delete the project in Google Cloud Console (**IAM & Admin → Settings → Shut down**). Google permanently deletes it after 30 days.
