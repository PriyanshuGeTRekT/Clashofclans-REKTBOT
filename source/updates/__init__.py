# updates/ - the app updates itself from GitHub releases.
#
#   client.py   asks GitHub for the newest release, downloads and checks its update package
#   engine.py   installs it after the app has closed, opens the new version, and goes back to the
#               previous one if the new one does not start (standard library only)
# The package is made by tools/build_update.py and attached to each release by the
# "Build installers" workflow (.github/workflows/build-installers.yml).
