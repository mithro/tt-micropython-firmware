# Demo mode

Demo mode cycles through a fixed sequence of projects on its own, for instance to leave a board with a VGA Pmod and a screen running at a booth with no computer attached.  It can also play a fixed script of inputs to each project, so a game plays itself.

## Turning it on

 * Set `demo = yes` in the `[DEFAULT]` section of [config.ini](config.md) and the demo runs on every boot.
 * **Hold the project reset (RST) button while plugging in power** to flip that setting for one boot: the demo runs on a board that normally doesn't, and is skipped on one that normally does.  The LED blinks while the button is held; let go and the board carries on booting.

The sequence shown is `/demo.json` if that file exists, otherwise the one bundled with the firmware for the detected chip, `/shuttles/<shuttle>.demo.json`.  The bundled ones live in this repo's [demos](demos/) directory, and the release build checks each against its shuttle's index.

From the REPL, the demo is available as `tt.demo`:

```
>>> tt.demo
<DemoRunner running, 3 projects: 907, 260, 674>
>>> tt.demo.next()     # switch now
>>> tt.demo.stop()
>>> tt.demo.start()    # starts again from the first project
>>> tt.demo.errors     # what was wrong, if the sequence was invalid
```

Enabling any project yourself -- `tt.shuttle.tt_um_whatever.enable()` or selecting one in the commander app -- stops the demo, so it never switches away from your choice.

## The sequence file

`/demo.json` and the bundled `/shuttles/<shuttle>.demo.json` files have the same format, and every field is required:

```
{
  "version": 1,
  "shuttle": "ttsky25a",
  "projects": [
    {"address": 907, "subtile": 0, "duration_ms": 15000, "clock_hz": 25175000,
     "ui_in": 0, "steps": []},
    {"address": 260, "subtile": 0, "duration_ms": 30000, "clock_hz": 25000000,
     "ui_in": 7, "steps": [{"set": 6}, {"wait_ms": 40}, {"set": 7}, {"wait_ms": 250}]}
  ]
}
```

 * **version**: 1.
 * **shuttle**: the chip the sequence is for; it must match the chip ROM (`tt.shuttle.run`, e.g. `tt09`, `ttsky25a`; `FPGA` on the FPGA breakout).
 * **projects**: shown in order, then from the start again.  Each one has:
   * **address**, **subtile**: the project's `address` and `subtile_addr` in the [shuttle index](https://index.tinytapeout.com/) (`subtile` is 0 for normal projects).  Projects are only identified this way -- names can differ on the board (Wokwi projects are renamed).
   * **duration_ms**: how long to show it, in milliseconds.
   * **clock_hz**: the project clock, or 0 for none.
   * **ui_in**: the input value (0-255) set once the project is enabled.
   * **steps**: inputs to play, see below; `[]` for none.

The project's own [config.ini](config.md) section, if any, is applied first, as whenever a project is enabled; the values above are applied on top of it.

### steps

Run in order.  Each step has exactly one key: `{"set": N}` writes `ui_in` (0-255) at once, `{"gamepad": [...]}` sets the buttons held on an emulated Gamepad Pmod (below), `{"wait_ms": N}` waits.  When the steps run out the project is reset and they start again from the first step -- `ui_in` is not set again, so begin with a `set` if the starting value matters.  This repeats until the project's time is up.  A project with no steps is never reset while shown.

### Gamepad Pmod emulation

Designs that read the [Gamepad Pmod](https://github.com/psychogenic/gamepad-pmod) (latch on `ui_in[4]`, clock on `ui_in[5]`, data on `ui_in[6]`) can be played with no Pmod plugged in: the board sends the design what the Pmod would.

```
{"gamepad": [{"buttons": ["start"]}]}                   one controller, holding Start
{"gamepad": [{"buttons": ["a"]}, {"buttons": ["left"]}]}  two controllers
{"gamepad": [{"buttons": []}]}                          one controller, nothing pressed
{"gamepad": []}                                         no controllers plugged in
```

 * The list is the controllers plugged into the Pmod, player 1 first: 0, 1 or 2 of them.  Player 1 is the one a design's `gamepad_pmod_single` reads (index 0 of `gamepad_pmod_dual`).
 * `buttons` names the buttons held, each once, in the order the Pmod sends them: `b`, `y`, `select`, `start`, `up`, `down`, `left`, `right`, `a`, `x`, `l`, `r`.  All twelve at once can't be sent (it reads as "no controller").
 * The buttons stay held until the next `gamepad` step.  Until the first one the design sees no controllers.
 * Like the Pmod, the board sends a report of 24 bits (an empty socket sends twelve 1s; player 1 is sent last, LSB first), data then clock high then clock low for each bit, then a latch pulse, and leaves the three lines low.  It sends one report at each `gamepad` step and again after the reset at the end of the steps (which clears the design's copy).  The real Pmod also repeats its report every second; nothing else on the board would make the design forget it, so the board doesn't.
 * The board writes the levels with `ui_in` writes from Python, so each level lasts some microseconds: much slower than the design clock, which the designs' synchronizers need.
 * In a project with `gamepad` steps, `ui_in` and every `set` must keep bits 4..6 (0x70) clear: those are the gamepad's.  It must also have a clock (`clock_hz` > 0): the design reads the gamepad on its clock.

## Errors

A sequence is shown completely or not at all.  If it can't be read, isn't valid JSON, is for a different chip, is missing a field or has one of the wrong type, has an unknown field, names a project that isn't on the chip (or isn't marked safe), or has a bad step, then the demo doesn't start:

 * every problem is logged, to the console and `boot.log`, and is listed in `tt.demo.errors`;
 * the 7-segment display blinks **E**, and so does the LED next to the RP2350.  (The display is driven by the chip, so the board enables the factory test design and holds it in reset, which passes `ui_in` straight to the display.)

Enabling any project by hand clears the display.

## Notes

 * The time per project counts from when the project has finished loading, so on the FPGA breakout (where loading a bitstream takes a second or so) each step is a little longer than `duration_ms`.
 * `ui_in` values only reach the project when the board drives the inputs (mode `ASIC_RP_CONTROL`, and no `ui_in` DIP switch on).
 * The REPL stays usable while the demo runs; it pauses briefly at each switch.
 * `ttboard/demo.py` only uses the public SDK API, so the same module can be run on SDK releases that don't include it.
