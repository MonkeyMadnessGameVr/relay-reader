# Try Relay inside Google Sites

This update adds a Google Sites embedding option and an in-page password form. Render still runs Relay. Nothing has been changed in your live Render service or Google account yet.

## 1. Update the existing GitHub repository

1. Extract `dist/Relay-Google-Sites-Update.zip` on your Windows PC.
2. Open the **same folder in your GitHub repository that currently contains `app.py`**. If your Render Root Directory is a subfolder, open that subfolder in GitHub first.
3. Choose **Add file → Upload files**. Drag the extracted update's **contents** into the upload area, preserving `templates/`, `static/`, `tests/`, and `scripts/`. Do not upload the ZIP itself.
4. Commit the changes. The update replaces existing app files and adds `templates/embed_login.html`. It contains no password.

The full replacement package `dist/Relay-Render.zip` is also refreshed, but you only need the smaller update ZIP for your existing service.

## 2. Enable it in Render

1. Open your existing **relay-reader web service** in the Render dashboard.
2. Open **Environment → Edit** and add:

   | Key | Value |
   | --- | --- |
   | `GOOGLE_SITES_EMBED` | `true` |

3. Keep your existing `GATEWAY_AUTH_KEY` unchanged and private. Do not remove authentication.
4. Save the environment setting. Use **Manual Deploy → Deploy latest commit** so the new code from GitHub is deployed too. Wait for **Live**.
5. Open [Relay's embed entry page](https://relay-reader.onrender.com/embed) directly. It should show **Sign in to Relay**, with a password field inside the page. Enter your existing Relay password. There is no username field in this mode.
6. Test `https://example.com` inside Relay before proceeding.

The option is off by default, so uploading the files alone does not allow Google Sites to frame the reader. To turn the option off later, set it to `false` and redeploy; the normal browser password prompt and same-origin frame policy return.

## 3. Create the Google Sites page

1. Open [Google Sites](https://sites.google.com) and create a **Blank** site, or open a site you own.
2. Give the site a name such as **My reading space**.
3. In the right panel, choose **Insert → Embed → By URL**.
4. Paste this URL, with no password added:

   ```text
   https://relay-reader.onrender.com/embed
   ```

5. Choose **Whole page** if Google offers a choice, then click **Insert**. Resize the embedded box so it is wide and tall enough to use the reader.
6. Click **Publish**, choose an available Google Sites web address, and select the sharing options suitable for you.
7. Open the **published site**, not the editor or edit-link. Sign in within the embedded Relay panel using your gateway password. Test `https://example.com`.

Use the **By URL** option; you do not need HTML embed code or a password in the Google Site. Google documents URL and full-page embeds in [Sites Help](https://support.google.com/sites/answer/90569?hl=en).

## 4. Test on the Chromebook

Open your published Google Sites link in Chrome. Enter your Relay password inside the reader, then open `https://example.com`. Check an in-page link, Back, search, and bookmarking. A separate **Sign out** button ends the embedded browser session.

If you signed in directly on Render first, you may need to sign in again inside Google Sites. Embedded sessions are separate from direct visits. A session lasts one hour; after expiration, reload the Google Sites page to sign in again. Bookmarks may also be stored separately in the embedded context.

## If it does not load

- **Old browser login box or `/embed` not found:** confirm the latest commit deployed and `GOOGLE_SITES_EMBED=true` is set on the web service, not only on the Blueprint.
- **Refused to connect / embedding not allowed:** check the setting and that you used the exact HTTPS `/embed` URL. Test the published page; the editor can introduce different framing contexts. Share the error or a screenshot, without the password.
- **Sign-in returns to the same screen:** the browser may not support or permit the embedded cookie. Use the **Open Relay in a new tab** link. Do not disable the password to work around this.
- **“Open the published Google Site or Relay directly to sign in”:** the form was submitted from an unexpected or opaque origin. Test the published **By URL** embed, or use the direct link.
- **Reader works directly but not embedded:** report that distinction and the published Google Sites link so the frame context can be inspected.
- **Render waking up:** wait about a minute, then reload. Free hosting still has its normal idle behavior.

Embedding does not move the backend to Google. Browser/device policies can still prevent embedding, cookies, downloads, or access to the underlying service. We have not yet verified your published Google Site or Chromebook.

## Implementation notes

- Enabling the option permits frame ancestors from `sites.google.com` and Google's `*.googleusercontent.com` embed wrappers, plus Relay itself. It does not permit every internet origin. This allowance covers all pages on those Google origins, not just your particular Google Site; CSP cannot identify a particular site by its URL path.
- The same ancestor policy is applied to the nested proxied reader because browsers check every ancestor. The fetched-page sandbox, script removal, destination checks, and authentication remain enabled.
- Login posts the password only to Relay over HTTPS and exchanges it for a signed, one-hour cookie. The cookie is `Secure`, `HttpOnly`, `SameSite=None`, and `Partitioned`; no gateway key is placed in URLs, localStorage, HTML, or Google Sites code.
- Password POSTs validate the Relay origin and are limited to ten attempts per minute per observed client address. Render proxy addresses may share that limit. Logout clears the browser cookie; as with other stateless sessions, a previously copied token expires after one hour. Changing the gateway password invalidates all existing tokens immediately.
- In embed mode, login pages and static UI assets are public so the form can render. Search and fetched content stay protected. The original API-key/Basic-auth mechanism still works for API clients.

References: [CSP frame ancestors](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors), [partitioned cookies](https://developer.mozilla.org/en-US/docs/Web/Privacy/Guides/Third-party_cookies/Partitioned_cookies).
