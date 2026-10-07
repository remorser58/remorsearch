"""Surface drivers that turn a real surface (or an annotation) into ergo-snapshot.v1.

The web driver is Node.js (drivers/web/ergo_drive.mjs). The Python drivers here
parse Android uiautomator dumps and vision/human annotations; they build adb
argv lists but this repository's tests never execute a live device.
"""
from __future__ import annotations
