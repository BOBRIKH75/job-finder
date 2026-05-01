"""
PATCH FOR job-finder/find_jobs.py
Add these 2 lines at the end of the main() function, right before the outreach section.

Find this line:
    html = build_email(df, len(all_jobs), learned)

Add BEFORE it:
    # ── Export for ai-job-agent ecosystem ──
    from bridge import export_jobs_for_agent
    n_exported = export_jobs_for_agent(df)
    print(f'📤 Exported {n_exported} jobs for ai-job-agent')

Then copy bridge.py to the job-finder repo:
    cp ~/Downloads/CV/ai-job-agent/src/bridge.py ~/Downloads/CV/cloud-job-finder/bridge.py

And add found_jobs.json to the git commit in the GitHub Actions workflow:
    git add found_jobs.json
    git commit -m "Export jobs for ai-job-agent"
    git push
"""
