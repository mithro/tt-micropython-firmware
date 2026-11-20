# Bundled demo sequences

Each `<shuttle>.demo.json` here is copied into the firmware as `/shuttles/<shuttle>.demo.json`, next to that chip's project index.  It is the demo sequence shown when demo mode is on and the board has no `/demo.json` of its own -- see [demo.md](../demo.md) for the format.

The release build checks every file against the shuttle's index from [index.tinytapeout.com](https://index.tinytapeout.com/) with `bin/check_demo_sequences.py`, using the same validation the board runs, and fails if any project is missing, not marked safe, or otherwise invalid.  `test/test_demo_sequences.py` checks the files are well formed.
