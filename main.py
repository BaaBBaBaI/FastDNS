#!/usr/bin/env python3
"""FastDNS — Entry point for Ubuntu Linux and Windows."""

from __future__ import annotations

import sys

from fastdns.cli import main


if __name__ == "__main__":
    sys.exit(main())
