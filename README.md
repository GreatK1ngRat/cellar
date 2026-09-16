# Cellar

A private log of wines you'd buy again, shared by whoever you invite onto
it. Runs as one Docker container on your home network. No cloud dependency
for the data itself -- SQLite file on a local volume, password-gated,
nothing exposed beyond your LAN unless you choose to expose it.

## Why one container, not a stack

SQLite is a library, not a server -- there's no daemon for a "database
container" to run. The Python app opens the `.db` file directly. Splitting
that into two containers would mean two processes fighting over the same
file, which is the opposite of what you want. One container, one process,
one file on a mounted host path.

## Setup

1. Create the folder the database will live in, and hand it to the same
   uid the container runs as (1000) -- otherwise the app can't write to it:
   ```
   sudo mkdir -p /opt/docker/cellar
   sudo chown 1000:1000 /opt/docker/cellar
   ```

2. Copy the environment template and fill it in:
   ```
   cp .env.example .env
   ```
   - Set `APP_PASSWORD` to whatever you want to type to get in.
   - Generate a real `SECRET_KEY`:
     ```
     python3 -c "import secrets; print(secrets.token_hex(32))"
     ```
   - `OPENROUTER_API_KEY` is optional. Without it, barcode lookup (free,
     unlimited, via Open Food Facts) still works. The label-photo fallback
     needs it -- get a free key at https://openrouter.ai (no credit card
     required for the free tier).

3. Build and start:
   ```
   docker compose up -d --build
   ```

4. Open `http://<the-machine's-lan-ip>:61618` from any device on your network.
   Leave the username blank (or type `admin`) and log in with `APP_PASSWORD`
   -- that's the administrator account. See **Accounts** below for adding
   other people.

Change the `61618:61618` in `docker-compose.yml` if that port is already in use on
your network.

## Accounts

There are two kinds of account:

- **Administrator** -- one account, logged into with `APP_PASSWORD` and no
  username (or the username `admin`). This is the same login that's always
  existed; adding other accounts doesn't change it. Only the admin can
  delete a wine outright, and only the admin can create or remove other
  accounts.
- **Members** -- created by the admin from the "Manage users" button in
  the app (visible only when logged in as admin). Each needs a username
  and a password of at least 10 characters, enforced on the server, not
  just in the browser. Members can add and edit wines same as admin, but
  can't delete one outright -- they can only **mark it for deletion**,
  which flags it (with their name attached) for the admin to actually
  remove later.

Everyone shares the same list -- there's no per-user view. Every wine
shows who added it, and a marked-for-deletion wine shows who marked it,
visible to anyone looking at that entry.

There's currently no self-service password reset or username change --
if a member is locked out, the admin removes their account and creates a
new one.

## Deploying via Portainer

Do the `mkdir` and `chown` from step 1 above on whichever machine actually
runs the container -- the Docker environment/endpoint Portainer is deploying
to -- not on the computer you're using to browse to the Portainer UI, if
those are different machines. `/opt/docker/cellar` in `docker-compose.yml`
is a path on that Docker host.

`build: .` needs the Dockerfile and `app/` folder alongside the compose file
as build context. Portainer's plain **Upload** and **Web editor** stack
methods only take the compose YAML itself, with nothing else -- so `build:`
silently fails from either of those. Use one of the two paths below instead.

### Option A — Git repository (recommended)

This is Portainer's own preferred path, and it gets you one-click
redeployment on future changes for free.

1. Push this folder to a Git repo (a private GitHub repo is fine).
2. In Portainer: **Stacks → Add stack → Build method: Repository**.
3. Fill in the repo URL, the branch, and `docker-compose.yml` as the
   Compose path.
4. Under **Environment variables**, add `APP_PASSWORD`, `SECRET_KEY`,
   `OPENROUTER_API_KEY`, and `OPENROUTER_MODEL` -- the same values that
   would otherwise go in `.env`. Portainer injects these into the same
   `${VARIABLE}` slots in `docker-compose.yml`, so don't commit a real
   `.env` file to the repo.
5. **Deploy the stack.** Portainer clones the repo and builds the image
   itself.

To pick up later changes, push to the repo, then **Stacks → cellar → Pull
and redeploy**.

### Option B — No Git: build the image in Portainer, then deploy

If you'd rather not stand up a repo, build the image directly from the
Portainer UI and point a plain stack at the result.

1. **Images → Build a new image.**
2. Name it `cellar:latest`.
3. Under **Build method**, upload this whole `cellar` folder (or a `.tar`
   of it) as the build context, with `Dockerfile` as the Dockerfile path.
4. Build it.
5. **Stacks → Add stack → Web editor**, and paste `docker-compose.yml` but
   swap the `build: .` line for `image: cellar:latest`.
6. Add the same four environment variables as in Option A, then deploy.

The trade-off: there's no auto-redeploy on change here. Rebuilding the
image and manually redeploying the stack is how you pick up any future
edits to the app.



1. **Barcode** -- if you type or scan a barcode, the app checks it against
   Open Food Facts. Free, no key, no rate limit. Coverage skews toward
   grocery-store wine, so this misses often for small producers or
   restaurant pours -- that's expected.
2. **Label photo** -- if there's no barcode or it doesn't match, take a
   photo of the label instead. A free vision-capable model via OpenRouter
   reads it directly. It only identifies the wine -- no web search, no
   listing or image -- so a match this way still saves with no photo, same
   as manual entry.
3. **Manual entry** -- if both miss, or you just want to type it yourself,
   the form is always right there, pre-filled with whatever was identified.

Every match is shown to you to confirm before it's saved -- nothing gets
written to the database without you seeing it first.

## Backing up your data

Everything that matters lives at `/opt/docker/cellar/` on the host -- the
SQLite file itself (`cellar.db`), plus a `photos/` subfolder holding
anything you've uploaded yourself. That's what the bind mount in
`docker-compose.yml` points at, so it's all just regular files, nothing
locked inside Docker. Back up the whole directory, not just the database:

```
cp -r /opt/docker/cellar ~/cellar-backup-$(date +%F)
```

or point whatever backup tool you already run at `/opt/docker/cellar/`
directly.

To restore, stop the container, copy a backup's contents back into
`/opt/docker/cellar/` (both the `.db` file and the `photos/` folder), then
start it again.

## Updating

```
docker compose up -d --build
```

The volume is untouched by rebuilds -- your data survives.

## What's stubbed vs real

- **Barcode lookup**: fully working against the live Open Food Facts API.
- **Label photo identification**: fully working against OpenRouter,
  provided `OPENROUTER_API_KEY` is set. Reads the label directly rather
  than matching against a fixed database, asks for a ranked list of
  candidates so a low-confidence guess is offered as a pickable option
  rather than discarded, and returns a wine identity only -- no image, no
  listing link. See BACKLOG.md for what's still open on this.
- **Finding a listing image automatically** isn't available -- every
  photo-identified wine saves with no photo unless a barcode match found
  one via Open Food Facts, or you upload one yourself (below). See
  BACKLOG.md for why automatic image lookup isn't free.
- **Uploading your own photo**: fully working, from a wine's edit form.
  Resized and compressed server-side (Pillow -- the one genuinely new
  dependency in this project) to a 1200px long edge at 85% JPEG quality,
  which keeps label text legible while shrinking a typical phone photo by
  roughly 90-95%. Handles portrait photos with EXIF rotation correctly.
  HEIC (the default format on many iPhones) isn't supported -- use JPEG
  or PNG. Stored on the same persistent volume as the database, and
  cleaned up automatically if the wine is deleted.
- **Accounts and marking for deletion**: fully working -- passwords are
  hashed (PBKDF2-SHA256, stdlib only, no extra dependency), the
  admin/member permission split is enforced server-side on every
  endpoint, not just hidden in the UI.
- **Barcode *scanning* from the camera** is not implemented -- there's a
  text field for the barcode number instead of live camera decoding. A
  library like `html5-qrcode` would add that on top of what's here without
  changing the backend at all.
