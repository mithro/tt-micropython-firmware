# Demo mode

Demo mode cycles through a playlist of projects on its own, for instance to leave a board with a VGA Pmod and a screen running at a booth with no computer attached.

## Starting it

There are two ways:

 * **Hold the project reset (RST) button while plugging in power.**  The LED blinks while the button is held; let go and the demo starts once the board has booted.
 * **Kiosk mode:** set `"enabled": true` in `/demo.json` and the demo starts on every boot.  On a kiosk board, holding RST while powering up *skips* the demo for that boot.

Either way the playlist comes from `/demo.json`; with no playlist for the detected chip, nothing happens.

From the REPL, the demo is available as `tt.demo`:

```
>>> tt.demo
<DemoRunner running, 3 projects: tt_um_vga_example, tt_um_rebeccargb_colorbars, 123-2>
>>> tt.demo.next()     # switch now
>>> tt.demo.stop()
>>> tt.demo.start()    # starts again from the first project
```

Enabling any project yourself -- `tt.shuttle.tt_um_whatever.enable()` or selecting one in the commander app -- stops the demo, so it never switches away from your choice.

## /demo.json

```
{
  "version": 1,
  "enabled": false,
  "seconds": 15,
  "shuttles": {
    "tt09": {
      "seconds": 20,
      "projects": [
        "tt_um_vga_example",
        {"macro": "tt_um_rebeccargb_colorbars", "clock_hz": 25175000},
        {"address": "123-2", "seconds": 30, "ui_in": 0}
      ]
    },
    "*": {
      "projects": ["tt_um_vga_example"]
    }
  }
}
```

 * **enabled**: `true` to start the demo on every boot (default `false`).
 * **seconds**: default time each project is shown (default 15).
 * **shuttles**: one playlist per chip, keyed by shuttle id as read from the chip ROM (`tt.shuttle.run`, e.g. `tt09`, `ttsky25a`; `FPGA` on the FPGA breakout).  The `*` entry is used for any chip without its own entry, so one file can travel with a board as you swap chips.
   * **seconds**: default time per project for this shuttle.
   * **projects**: in order.  Each is either just a project (macro) name, or an object with:
     * **macro** (the project name) *or* **address** (`"ADDR"` or `"ADDR-SUBTILE"`)
     * **seconds**: how long to show this project
     * **clock_hz**: project clock, overriding the shuttle's -- useful for VGA designs that list no clock
     * **ui_in**, **uio_oe_pico**, **uio_in**: input values to set (0-255)

The project's own [config.ini](config.md) section, if any, is applied first, as whenever a project is enabled; the values above are applied on top of it.

Projects that aren't on the detected chip are skipped, as are projects that refuse to be enabled because of their danger level.  Invalid entries or values are ignored with a warning in the log.  Unknown keys are ignored too, so the file can carry extra information for other tools.

## Notes

 * The time per project counts from when the project has finished loading, so on the FPGA breakout (where loading a bitstream takes a second or so) each step is a little longer than `seconds`.
 * The REPL stays usable while the demo runs; it pauses briefly at each switch.
 * `ttboard/demo.py` only uses the public SDK API, so the same module can be run on SDK releases that don't include it.
