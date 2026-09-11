# Put Relay online with Render

All account setup below can be done on your Windows PC. Once deployed, your PC can be turned off. Your Chromebook needs only the final **HTTPS website link**. You do not need your router login, port forwarding, a domain purchase, or Python on the Chromebook.

The code is prepared for deployment; it has **not** been uploaded to your accounts or deployed yet. Use a **new password of at least 16 characters**, not the short password shared in the conversation.

## 1. Get the upload files

Open `dist/Relay-Render.zip` in this project folder. Right-click it and choose **Extract All**. Open the extracted `relay-render` folder.

This is a clean upload package containing only the application, its deployment configuration, instructions, and tests. It excludes your `.venv`, saved passwords, local environment files, and the unrelated `OmniSearch.html`.

You will upload the **contents** of `relay-render`, including its `static`, `templates`, and `tests` folders. Do not upload the ZIP itself or put another `relay-render` folder around the files in GitHub.

## 2. Put the code in a private GitHub repository

1. Visit [GitHub](https://github.com) and sign in or create an account.
2. Open [Create a repository](https://github.com/new).
3. Name it `relay-reader` and select **Private**. Leave initialization options such as adding a README unchecked; this project already includes them.
4. Click **Create repository**.
5. On the new repository page, choose **uploading an existing file**. If your repository already has files, use **Add file → Upload files**.
6. In Windows File Explorer, open the extracted `relay-render` folder, select all its contents, and drag them into the GitHub upload area. Keep the folder structure intact.
7. Click **Commit changes**.
8. Check the repository's main file list. You should see `app.py`, `config.py`, `requirements.txt`, `render.yaml`, `.python-version`, `README.md`, `RENDER_SETUP.md`, and the `static`, `templates`, and `tests` folders. In particular, `render.yaml` and `app.py` must be directly in the repository root.

Never upload `.venv` or place your Relay password in a source file. Instructions for file uploads: [GitHub documentation](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository).

## 3. Create the Render service using the included Blueprint

1. Visit [Render](https://dashboard.render.com) and sign in or create an account. You can use your GitHub account.
2. Choose **New → Blueprint**. A Blueprint reads the included `render.yaml` so you do not have to enter build commands yourself.
3. Connect GitHub when asked. Give Render access to the `relay-reader` repository, then select that repository.
4. Use the repository's default branch and the Blueprint path `render.yaml` if asked.
5. Give the Blueprint a name such as `relay-reader`.
6. When Render asks for **GATEWAY_AUTH_KEY**, enter your new password of at least 16 characters. Enter the password itself, with no surrounding quotes. Save it in your password manager. Do not paste it into GitHub, chat, or an email.
7. Review the service preview. It should show **one Python web service**, named `relay-reader`, on the **Free** instance plan. No database or additional paid resource is needed. If it shows a paid instance, correct the selection before proceeding.
8. Click **Deploy Blueprint** (the confirmation may instead be labeled **Apply**).
9. Open the created web service and wait for its deployment status to become **Live**. Watch its deployment logs for any error. An initial dependency install can take several minutes.

The Blueprint configures:

| Field | Value |
| --- | --- |
| Runtime | Python 3.13, selected by `.python-version` |
| Build command | `pip install -r requirements.txt` |
| Start command | `python app.py` |
| Health check | `/healthz` |
| Instance | Free |
| Password | `GATEWAY_AUTH_KEY`, entered privately in Render |
| Debug | Disabled |
| Automatic deploys | Off; deploy changes manually when ready |

The app uses Render's `PORT` and `RENDER_EXTERNAL_URL` automatically. **Do not set a home IP address, port 5000, or localhost as the public URL.** Render supplies the public hostname and HTTPS certificate. [Blueprint documentation](https://render.com/docs/infrastructure-as-code) · [Render web services](https://render.com/docs/web-services)

## 4. Open the deployed site on your Windows PC

1. Copy the HTTPS URL displayed on the Render service page. It will resemble `https://relay-reader-xxxx.onrender.com`; that example is not your actual URL.
2. Open **your actual URL** in your browser.
3. At the browser login prompt, enter username `relay` and your `GATEWAY_AUTH_KEY` password. The username can be any text.
4. You should see **Relay**, **Gateway online**, and **Hosted on Render**.
5. In Relay's address bar, type `https://example.com` and click **Go**. The reader should display **Example Domain**.
6. Click its **Learn more** link, then try Relay's Back and Forward buttons.
7. Bookmark a page with the star, return Home, and confirm it appears in Saved Pages.

This checks the deployed site before introducing any school-network restrictions. The separate public URL `/healthz` returns `{"status":"ok"}` and does not expose any reader content. All reader routes, including `/status`, remain password-protected.

## 5. Test on the Chromebook at school

1. Send yourself **only your actual HTTPS Render link**, or type it into Chrome. No attachments are needed. Do not add `:5000` to the URL.
2. Open the link on your Chromebook. Enter username `relay` and the new password when asked.
3. Confirm Relay opens. Enter `https://example.com` inside Relay and click **Go**.
4. Try another ordinary page you need, such as `https://en.wikipedia.org/wiki/Moon`.
5. Try a search. If DuckDuckGo reports a challenge, try a direct URL instead. Hosting on Render does not guarantee search-provider access; datacenter addresses can be challenged too.
6. Try starring a page and reopening it. Bookmarks are stored on that device, so your PC's bookmarks will not automatically appear on the Chromebook. JSON export/import transfers them if needed.
7. You can close PowerShell and turn off your home PC. The Render site should continue working.

The managed Chromebook or school network can still block the Render address or reader functionality. Test only where permitted; the app does not change device or network policies.

## If something fails

| Symptom | What to do |
| --- | --- |
| Render cannot find `render.yaml` or `app.py` | Check that you uploaded the extracted folder's contents at the repository root. |
| Build fails with a dependency error | Copy the error lines from Render's build log, excluding passwords, and share them for diagnosis. |
| Deploy log says `Set GATEWAY_AUTH_KEY...` | Set a password of at least 16 characters in the service's **Environment** settings, save, and redeploy. |
| Deploy fails a health check | Confirm the health-check path is `/healthz`, not `/status` or `/`. The latter routes require a password. |
| Login repeats | Use the Render environment password, not your GitHub, Wi-Fi, or old local Relay password. Use a fresh browser session if it cached an old password. |
| Render displays a loading/waking-up page | Wait about a minute, then retry. Free instances sleep after 15 minutes without traffic. |
| The site works at home but shows a school block page | The school is blocking the address. Contact its administrator if access is needed. |
| Relay opens but a destination fails | That website may reject server-side fetching or require unsupported scripts. Check `https://example.com` to distinguish gateway failure from a destination issue. |
| DuckDuckGo challenge | Search is temporarily unavailable from the server. Direct URL reading can still work. |
| Resource exceeds 4 MB | Hosted mode caps individual resources to fit free-instance memory. Try a smaller page or image. |
| Free service is suspended | Check Render's dashboard for the specific bandwidth, usage, or account limitation. |

Free hosting is for testing/hobby use and has monthly limits. It sleeps after 15 idle minutes and takes about a minute to wake. There is no paid subscription or keep-alive workaround configured by this project. [Current free-instance limits](https://render.com/docs/free)

## Later changes

Update the source files in the private repository, then open the Render service and choose **Manual Deploy → Deploy latest commit**. For a password change, update `GATEWAY_AUTH_KEY` in Render's Environment settings and redeploy. The ZIP is a snapshot; rebuild it after making code changes if you want a fresh upload package.

To stop the hosted service, suspend or delete it from the Render dashboard. Closing PowerShell only stops a local copy. You do not need any router port-forwarding rules for Render; any rules you previously created for home hosting can be removed.
