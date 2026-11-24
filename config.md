# TT demo board configuration

A *config.ini* file, in the filesystem root, specifies default behaviour and, optionally, project-specific settings. 

### Automatic Load and Default Config

The [config.ini](src/config.ini) file has a **DEFAULT** section that may be used to specify the demo board mode, default project to enable and other things

```
[DEFAULT]
# project: project to load by default
project = tt_um_factory_test

# start in reset (bool)
start_in_reset = no

# mode can be any of
#  - SAFE: all RP2040 pins inputs
#  - ASIC_RP_CONTROL: TT inputs,nrst and clock driven, outputs monitored
#  - ASIC_MANUAL_INPUTS: basically same as safe, but intent is clear
mode = ASIC_RP_CONTROL

# log_level can be one of
#  - DEBUG
#  - INFO
#  - WARN
#  - ERROR
log_level = INFO


# default RP2040 system clock
rp_clock_frequency = 125e6

```

Each project on the shuttle may have it's own section as well, with additional attributes.  All attributes are optional.
See the config section, below, for details.

## Configuration

A `config.ini` file may be used to setup defaults (e.g. default mode or project to load on boot) as well as specific configuration to apply when loading a project in particular.  See the included `config.ini` for samples with commentary.

Projects may use their own sections in this file to do preliminary setup, like configure clocking, direction and state of bidir pins, etc.

If you're connected to the REPL, the configuration can be probed just by looking at the repr string or printing the object out


```
>>> tt.user_config
<UserConfig config.ini, default project: tt_um_factory_test>
>>> 
>>> print(tt.user_config)
UserConfig config.ini, Defaults:
project: tt_um_factory_test
mode: ASIC_RP_CONTROL
tt_um_psychogenic_neptuneproportional
  clock_frequency: 4000
  mode: ASIC_RP_CONTROL
  ui_in: 200
tt_um_urish_simon
  clock_frequency: 50000
  mode: ASIC_MANUAL_INPUTS
...

```


If any override sections are present in the file, sections will show you which are there, and these are present as 
attributes you can just looking at to see summary info, or print out to see everything the section actually does. 

```
>>> tt.user_config.sections
['tt_um_factory_test', 'tt_um_urish_simon', 'tt_um_psychogenic_neptuneproportional', 'tt_um_test', 'tt_um_loopback', 'tt_um_vga_clock', 'tt_um_algofoogle_solo_squash']
>>> 
>>> tt.user_config.tt_um_urish_simon
<UserProjectConfig tt_um_urish_simon, 50000Hz, mode: ASIC_MANUAL_INPUTS>
>>>
>>> tt.user_config.tt_um_psychogenic_neptuneproportional
<UserProjectConfig tt_um_psychogenic_neptuneproportional, 4000Hz, mode: ASIC_RP_CONTROL>
>>>
>>> print(tt.user_config.tt_um_vga_clock)
tt_um_vga_clock
  clock_frequency: 3.15e+07
  mode: ASIC_RP_CONTROL
  rp_clock_frequency: 1.26e+08

```


### Sections and Values

This is *similar* to, but not the same (because hand-crufted) as the python config parser.

Sections are simply name `[SECTION]`.

Values are 

```
key = value
```

Where the value may be

   * a string
   * a numerical value (an int, float, 0xnn or 0bnnnnnnnn representation)
   * a boolean (true, false, yes, no)
   * a comment (a line beginning with #)


### System Defaults

System-wide default settings supported are

project: (string) name of project to load on boot, e.g. *tt_um_loopback*, or a comma-separated list of projects to cycle through (see below)

switch_interval: (number) seconds to show each project when several are listed in *project*; defaults to 15, 0 loads only the first

mode: (string) ASIC_RP_CONTROL, ASIC_MANUAL_INPUTS (to use the on-board switches/buttons), or SAFE 

start_in_reset: (bool) whether projects should have their nRESET pin held low when enabled

rp_clock_frequency: system clock frequency


### Cycling through several projects

List more than one project to have the board switch between them on its own, e.g. to leave a set of VGA demos running on a screen:

```
[DEFAULT]
project = tt_um_vga_clock, tt_um_algofoogle_solo_squash, tt_um_factory_test
switch_interval = 30
```

On boot the first project in the list is enabled, then every *switch_interval* seconds the next one is (wrapping around to the start).  Each project's own section, if any, is applied as usual whenever it's enabled, so clocks and inputs can be set per project.

 * Names that aren't on the detected shuttle are skipped, so one list can cover chips from several shuttles.
 * Projects that refuse to enable (e.g. because of their danger level) are skipped.
 * Enabling a project yourself, from the REPL or the commander app, stops the cycling.

From the REPL, the rotation is available as `tt.project_rotation` (`None` if only one project is configured):

```
>>> tt.project_rotation
<ProjectRotation running, every 30s: tt_um_vga_clock, tt_um_algofoogle_solo_squash, tt_um_factory_test>
>>> tt.project_rotation.next()   # switch now
>>> tt.project_rotation.stop()
>>> tt.project_rotation.start()
```


### Project-specific

Some values may be auto-configured when enabling a project, by having them specified in their own section.
The section name is 

```
[PROJECT_NAME]
```

as specified in the shuttle, for instance

```
[tt_um_psychogenic_neptuneproportional]

```

Values that may be set are
 * clock_frequency: Frequency, in Hz, to auto-clock on project clock pin (ignored if in ASIC_MANUAL_INPUTS)
 * rp_clock_frequency: system clock frequency -- useful if you need precision for your project clock PWM
 * ui_in: value to set for inputs on startup (ignored if in ASIC_MANUAL_INPUTS)
 * uio_oe_pico: bidirectional pin direction, bits set to 1 are driven by RP2040
 * uio_in: actual value to set on bidirectional pins (only applies to outputs)
 * mode: tt mode to set for this project


Values unspecified in a configuration are left as-is on project enable().

Project auto-clocking is stopped by default when a project is loaded.  If the clock_frequency is set, then 
it will be setup accordingly (*after* the rp_clock_frequency has been configured if that's present).

Bi-directional pins (uio*) are reset to inputs when enabling another project.


