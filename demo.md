# Demo mode

Demo mode cycles through a playlist of projects on its own, for instance to leave a board with a VGA Pmod and a screen running at a booth with no computer attached.  It can also play a fixed sequence of inputs to each project, so a game plays itself.

## Starting it

There are two ways:

 * **Hold the project reset (RST) button while plugging in power.**  The LED blinks while the button is held; let go and the demo starts once the board has booted.
 * **Kiosk mode:** set `"enabled": true` in `/demo.json` and the demo starts on every boot.  On a kiosk board, holding RST while powering up *skips* the demo for that boot.

Either way the playlist comes from `/demo.json`.  If that file is missing, or has neither an entry for the detected chip nor a `*` entry, the chip's built-in playlist is used: the designs the Tiny Tapeout shuttle index marks for demos (from each shuttle repo's `projects/demo.yaml`), bundled into the firmware as `/shuttles/<shuttle>.demo.json`.  With neither, nothing happens.

From the REPL, the demo is available as `tt.demo`:

```
>>> tt.demo
<DemoRunner running, 3 projects: 907, 260, 674>
>>> tt.demo.next()     # switch now
>>> tt.demo.stop()
>>> tt.demo.start()    # starts again from the first project
```

Enabling any project yourself -- `tt.shuttle.tt_um_whatever.enable()` or selecting one in the commander app -- stops the demo, so it never switches away from your choice.

## /demo.json

There is exactly one way to write each thing:

```
{
  "version": 1,
  "enabled": false,
  "duration_ms": 15000,
  "shuttles": {
    "ttsky25a": {
      "projects": [
        {"address": 907, "subtile": 0, "ui_in": 0},
        {"address": 260, "subtile": 0, "ui_in": 7, "duration_ms": 30000,
         "keys": {"via": "ui", "steps": [
           {"set": 5}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 120},
           {"set": 6}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 250}]}}
      ]
    },
    "*": {
      "projects": [{"address": 586, "subtile": 0}]
    }
  }
}
```

 * **enabled**: `true` to start the demo on every boot (default `false`).
 * **duration_ms**: default time each project is shown, in milliseconds (default 15000).
 * **shuttles**: one playlist per chip, keyed by shuttle id as read from the chip ROM (`tt.shuttle.run`, e.g. `tt09`, `ttsky25a`; `FPGA` on the FPGA breakout).  The `*` entry is used for any chip without its own entry.  Each has a single key, **projects**, listing the entries in order.

Each entry is an object:

 * **address** and **subtile** (both required, integers): the project's `address` and `subtile_addr` in the [shuttle index](https://index.tinytapeout.com/); `subtile` is 0 for normal projects.  Projects are only ever identified this way -- names can differ on the board (Wokwi projects are renamed).
 * **duration_ms**: how long to show this project.
 * **clock_hz**: project clock, overriding the shuttle index's -- useful for VGA designs that list no clock.
 * **ui_in**, **uio_oe_pico**, **uio_in**: values to set (0-255).  `ui_in` is also the base value for **keys**.
 * **keys**: inputs to play while the project is shown, see below.

The project's own [config.ini](config.md) section, if any, is applied first, as whenever a project is enabled; the values above are applied on top of it.

Projects that aren't on the detected chip are skipped, as are projects that refuse to be enabled because of their danger level.  An invalid entry is skipped; invalid **keys** are dropped but the project is still shown; unknown fields are ignored -- all with a warning in the log.

### keys

```
{"via": "ui", "steps": [{"set": 5}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 120}]}
```

 * **via**: `"ui"` -- each `set` writes `ui_in`; or `"gamepad"` -- each `set` is a 12-bit [Gamepad Pmod](https://github.com/TinyTapeout/tt-gamepad-pmod) report, sent on `ui[4..6]` (latch, clock, data) with the other `ui_in` pins left at their base value.  Report bits: b0 y1 select2 start3 up4 down5 left6 right7 a8 x9 l10 r11.
 * **steps**: run in order.  Each step has exactly one key: `{"set": N}` applies a value at once, `{"wait_ms": N}` waits.  The steps must wait for some time in total.

When the steps run out the project is reset, `ui_in` is set back to the entry's value and the steps start over, so every loop plays out from the same state -- until the project's time is up.  Projects without **keys** are never reset while shown.

## Notes

 * The time per project counts from when the project has finished loading, so on the FPGA breakout (where loading a bitstream takes a second or so) each step is a little longer than `duration_ms`.
 * `ui_in` values (and **keys**) only reach the project when the board drives the inputs (mode `ASIC_RP_CONTROL`, and no `ui_in` DIP switch on).
 * The REPL stays usable while the demo runs; it pauses briefly at each switch.
 * `ttboard/demo.py` only uses the public SDK API, so the same module can be run on SDK releases that don't include it.
