# mithro/tt-micropython-firmware

A fork of [TinyTapeout/tt-micropython-firmware](https://github.com/TinyTapeout/tt-micropython-firmware),
the MicroPython SDK and firmware for the Tiny Tapeout demo board.

You are looking at the **`actions`** branch. It is the repository's default
branch, but it holds no firmware code and shares no history with the other
branches: only this README and the fork's own GitHub Actions. The firmware
code is on the branches below.

## Branches

| Branch | What it is | Rule |
|---|---|---|
| `actions` | Default branch: this README and repository-wide workflows | Only workflows that run on a schedule or by hand, which GitHub reads from the default branch |
| `main` | An exact mirror of upstream `main` | Never commit here: `sync-upstream.yml` force-pushes upstream over it every 6 hours |
| `dev` | The "working main": upstream `main` with several feature branches merged in, to build one firmware with all of them (currently `demo-gamepad`, `config-multi-project`, `fpga-enable-return`) | Merge feature branches in; don't develop on it directly. `sync-upstream.yml` merges upstream `main` in every 6 hours |
| feature branches | One change each, branched from upstream `main` | What upstream pull requests are made from |

### Feature branches

| Branch | Change |
|---|---|
| `demo-mode` | Demo mode: cycle through a list of projects (`/demo.json`), entered by `[DEFAULT] demo = yes` in `config.ini` or by holding RST at power-on |
| `demo-shuttle-sequences` | On top of `demo-mode`: bundled default sequences, `demos/<shuttle>.demo.json`, checked against the shuttle index at build time |
| `demo-gamepad` | On top of `demo-shuttle-sequences`: `"gamepad"` steps that emulate the Gamepad Pmod |
| `config-multi-project` | `config.ini`: several default projects with a `switch_interval` |
| `fpga-enable-return` | Fix: FPGA `BitStream.enable()` returns the mux's result instead of `None` |
| `ci-publish-every-push` | `release.yml`: build and publish firmware on every branch push (see below) |
| `demo-index-playlist` | Superseded by `demo-shuttle-sequences`; kept for reference |

## Firmware builds

Workflows triggered by a push are read from the pushed commit, so the build
workflow (`.github/workflows/release.yml`) lives on the code branches, not
here. A branch that contains the `ci-publish-every-push` change builds
firmware on every push and publishes it as a rolling pre-release named
`dev-<branch>`, replaced by each new push:

```sh
gh release download dev-<branch> -R mithro/tt-micropython-firmware
```

Pushing a `v*` tag builds a normal release, as upstream does.

## Syncing with upstream

[`sync-upstream.yml`](.github/workflows/sync-upstream.yml) runs every
6 hours (or by hand from the Actions tab). It force-pushes upstream `main`
over this fork's `main`, then merges upstream `main` into `dev`; a merge
conflict fails the run and has to be merged by hand. It pushes with a write
deploy key stored in the secret `SYNC_DEPLOY_KEY`, because `GITHUB_TOKEN` is
refused for pushes that write new commits changing `.github/workflows/`, and
because, unlike `GITHUB_TOKEN` pushes, its push to `dev` starts `dev`'s
firmware build.

GitHub only runs scheduled workflows from the default branch, and disables
them after 60 days without repository activity, so keep `actions` as the
default branch and re-enable the workflow if it has been switched off.
