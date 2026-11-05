# Contributing to Daryafter

Thanks for helping! This is a small project, so keep changes focused and small.

## Reporting a bug

Open an [issue](https://github.com/RezaMarozi/daryafter/issues) with:

- Windows version, Python version (`python --version`) and Daryafter version (More > About),
- what you did, what you expected and what happened,
- the error shown by `.venv\Scripts\python -m daryafter` in a Command Prompt, if there is one.

The log file is `%APPDATA%\Daryafter\daryafter.log`. **It may contain links you downloaded; remove anything
private before posting it.**

## Running the tests

    python -m unittest discover -s tests -t .
    python -m tests.ui_smoke

Please add or update a test for any change in `daryafter/core` (the engine has no Qt code and is easy to test).

## Code layout

`daryafter/core` is the download engine (no Qt). `daryafter/ui` is the PySide6 interface and only talks to the
engine through `EngineService`. See the README for what each part does.

## Translations

Interface texts go through `tr("English text")`. To add a language, create `daryafter/locales/<code>.json`
mapping the English text to its translation.

## Pull requests

- One change per pull request, with a short description of what and why.
- Make sure all tests pass.
- By contributing you agree that your contribution is released under the project's MIT license.
