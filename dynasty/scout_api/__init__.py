"""Scout API: the NAS-side HTTP surface the automated daily-scout cloud
routine calls (see .claude/PROJECT_PLAN_DYNASTY.md's SC-11).

Currently a proof-of-concept slice only (`/health`, `/ping`) proving the
cloud-routine -> NAS network path and auth work end to end - real
findings-store endpoints land once SC-2's persistence exists. A separate
deployable image from `dynasty/streamlit_app.py` (own Dockerfile, own
VERSION, own minimal requirements.txt), not a Streamlit page - the two
share no runtime process, only this repo.
"""
