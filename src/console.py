"""Console helpers shared by the command-line entry points."""

from __future__ import annotations

import sys

__all__ = ["safe_console"]


def safe_console() -> None:
    """Stop a cp1252 Windows console from crashing on non-ASCII output.

    Blob names and municipality names carry diacritics (Súdwest-Fryslân), and
    a UnicodeEncodeError raised while printing an error message hides the error
    it was trying to report. Unencodable characters are replaced instead.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a reconfigurable text stream
            pass
