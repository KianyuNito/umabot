# umabot

Automation for the game Umamusume: Pretty Derby. Windows only.

## Requirements

- Windows
- [uv](https://docs.astral.sh/uv/getting-started/installation/) to manage Python and dependencies
- The game running on screen

## Running from source

```
uv sync
uv run python umabotQT.py
```

`uv sync` installs Python 3.13 and the libraries listed in `pyproject.toml`. You only need to run it once, or again after dependencies change.

## Skills

The skill list is included in `skills.db`. To update it with your own scan, run from source:

    uv run python skill_scanner.py scan

The game must be open on the skill-learn screen. See `python skill_scanner.py -h` for other commands.

## Building the exe

_To be added after build.bat is updated for uv._

## Project structure

- `umabotQT.py`: the app window and entry point
- `engine.py`: automation logic
- `vision.py`, `window.py`: screen capture and image matching
- `templates/`: screen markers used for image matching (see NOTICE)
- `fonts/`: Nunito font (SIL OFL 1.1, see `fonts/OFL.txt`)
- `skill_scanner.py`, `skill_planner.py`, `skill_plan_step.py`: skill scanning and planning

## Disclaimer

This tool automates clicks in the game. Automation may violate the game's terms of service, and you use it at your own risk. This project is not affiliated with or endorsed by Cygames, Inc.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE). Images and other third-party material are covered separately in [NOTICE.txt](NOTICE.txt).