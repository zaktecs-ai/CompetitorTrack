"""CompetitorTrack API and scheduler.

The `api` and `scheduler` services run from the same image and share this
package; only their entrypoints differ (`app.main` vs `app.scheduler`).
"""
