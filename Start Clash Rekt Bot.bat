@echo off
title Clash Rekt Bot
rem Double-click to start Clash Rekt Bot. The first run sets everything up by itself.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\bootstrap.ps1" %*
