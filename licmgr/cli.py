"""licmgr — interactive TUI CLI entry point.

Running `licmgr` launches the full interactive TUI.
For non-interactive scripting use the Poetry plugin: `poetry licmgr <command>`.
"""

from licmgr.tui import main

if __name__ == "__main__":
    main()
