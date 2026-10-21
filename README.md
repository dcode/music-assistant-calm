# Music Assistant + Calm

Play [Calm](https://www.calm.com) content (sleep stories, meditations, soundscapes,
music) in [Music Assistant](https://music-assistant.io), using
[python-calm-client](https://github.com/dcode/python-calm-client).

This repository contains:

| Path | What it is |
|---|---|
| `music_assistant_calm/provider/calm/` | The Calm music provider for Music Assistant |
| `music_assistant_calm/` | A Home Assistant add-on: the official MA server image plus the provider |
| `tests/` | Provider tests, run against Music Assistant 2.10.7 |

## Install on Home Assistant OS

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add
   `https://github.com/dcode/music-assistant-calm`.
2. Install **Music Assistant (with Calm)** and read its *Documentation* tab first: it
   replaces the official Music Assistant add-on (only one can run at a time) and
   explains how to carry over your existing setup.

## How Calm maps to Music Assistant

| Calm | Music Assistant |
|---|---|
| Program (album, course, series, playlist) | Album |
| Guide (one story, session or track) | Track |
| Narrator / composer | Artist |
| Feeds (Sleep, Meditate, Music, …) and packs | Browse folders |
| Home feed rows | Recommendations |
| Favorites | Library albums and tracks |

Items Calm reports as locked for your account are listed but not playable.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python --no-deps -e /path/to/music-assistant-server@2.10.7
uv pip install --python .venv/bin/python calm-client==0.1.0 pytest pytest-asyncio ...
ln -s "$PWD/music_assistant_calm/provider/calm" /path/to/music-assistant-server/music_assistant/providers/calm
.venv/bin/python -m pytest
```

CI does the same in `.github/workflows/ci.yml`, and also builds the add-on image.

## Long-term: no custom image needed

The add-on exists only because Music Assistant can't load providers from outside its
own package. [dcode/music-assistant-server@feat/custom-providers](https://github.com/dcode/music-assistant-server/tree/feat/custom-providers)
adds a `custom_providers` directory (like Home Assistant's `custom_components`). With
that in Music Assistant, installing Calm becomes: copy `music_assistant_calm/provider/calm`
to `/addon_configs/<music assistant slug>/custom_providers/calm` and restart, on the
official add-on. The provider runs unmodified that way (verified against the branch).

## Status

Unofficial and experimental. Calm's web API is undocumented and may change.
