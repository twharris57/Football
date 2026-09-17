"""Scout API: the NAS-side outbound sync for the automated daily-scout
feature (see .claude/PROJECT_PLAN_DYNASTY.md's "Automated daily scout"
section).

The cloud routine has no persistent disk of its own between nightly runs,
so it keeps its real state (findings, dedup log, last-run status) in a
dedicated `scout-data` git branch on this repo instead. This package pulls
that branch's content down and mirrors it into local SQLite, which
`dynasty/streamlit_app.py` can then query like any other local data.

Originally an inbound FastAPI server (an early proof-of-concept slice,
`/health`/`/ping`) the cloud routine would call directly - retired after
two nights of live debugging proved this network's inbound path from the
cloud sandbox to this NAS cannot work (see PROJECT_PLAN_DYNASTY.md's "Why
the inbound design was abandoned"). A separate deployable image from
`dynasty/streamlit_app.py` (own Dockerfile, own VERSION, own minimal
requirements.txt), not a Streamlit page - the two share no runtime
process, only this repo. Unlike the retired server, this is a script run
to completion on a schedule (Synology Task Scheduler), not a long-running
service.
"""
