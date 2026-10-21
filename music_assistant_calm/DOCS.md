# Music Assistant (with Calm)

This add-on is the **official Music Assistant server**, unchanged, with one extra
music provider baked in: **Calm** (sleep stories, meditations, soundscapes and music
from your Calm subscription).

It exists because Music Assistant can only load providers that ship inside its own
package. Until Music Assistant supports external providers, the add-on rebuilds the
official image with the Calm provider copied in.

## Before you install

- **Only run one Music Assistant add-on at a time.** Both use port 8095 and the same
  player integrations. Stop (and disable "Start on boot" for) the official add-on first.
- The add-on is built on your Home Assistant host from the official
  `ghcr.io/music-assistant/server` image, so the first install takes a few minutes.
- Calm is an unofficial, reverse-engineered integration. It can break whenever Calm
  changes its web API.

## Moving your existing Music Assistant setup (optional)

A new add-on starts with an empty Music Assistant. To keep your players, providers
and library, copy the official add-on's data before first start:

1. Install this add-on, but **don't start it yet**.
2. Stop the official Music Assistant add-on.
3. In the *Advanced SSH & Web Terminal* add-on (protection mode **off**), run:

   ```bash
   # find both add-on data folders
   ls /mnt/data/supervisor/addons/data | grep music_assistant
   # copy the official add-on's data into this add-on's folder
   docker run --rm -v /mnt/data/supervisor/addons/data:/addons alpine \
     sh -c 'cp -a /addons/d5369777_music_assistant/. /addons/<this-addon-slug>/'
   ```

   Replace `<this-addon-slug>` with the folder from the `ls` output, for example
   `local_music_assistant_calm` or `<hash>_music_assistant_calm`.
4. Start this add-on.

The official add-on's data is left untouched, so you can switch back at any time.

## Adding Calm

In Music Assistant: **Settings → Providers → Add → Calm**, then enter your Calm email
and password. Calm then shows up under **Browse**, in **Search** and in your library
(your Calm favorites).

## Updating

When the official add-on gets a new version, this one has to be rebuilt against it:
bump `version` in `config.yaml` and the image tag in `build.yaml`, then reinstall.
