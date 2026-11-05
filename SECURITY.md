# Security policy

## Supported versions

Only the latest release (currently 0.1.x, beta) receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Use GitHub's private reporting instead:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability** and describe the problem.

Include what you found and why it matters, steps to reproduce it (Windows version, Python version, Daryafter
version), and anything you already tried. If you do not see the button, open a normal issue that says only
that you want to report a security problem, **without details**, and a private channel will be arranged.

This is a hobby project maintained by one person, so replies are best-effort, but reports are taken seriously.

## What is *not* a vulnerability

The app lock is a **screen lock**, not encryption. It hides the window and slows down guessing, but the download
list, settings and downloaded files are not encrypted, and someone with access to your Windows account can read
them. This is documented behaviour. A forgotten password cannot be recovered.
