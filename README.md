# 🔍 Cloud C2C Job Finder

Automated daily job search. Runs on GitHub Actions (free), emails you ranked C2C Java jobs.

## Setup (5 minutes, one time)

### 1. Create GitHub repo
- Go to https://github.com/new
- Name: `job-finder` (make it **PRIVATE**)
- Click "Create repository"

### 2. Push these files
```bash
cd ~/Downloads/CV/cloud-job-finder
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/job-finder.git
git push -u origin main
```

### 3. Add secrets (your email + app password)
- In your repo → **Settings** → **Secrets and variables** → **Actions**
- Add secret: `EMAIL` = `bobrikh75@gmail.com`
- Add secret: `APP_PASSWORD` = your 16-char Gmail App Password

### 4. Get Gmail App Password
1. https://myaccount.google.com/security → enable 2-Step Verification
2. https://myaccount.google.com/apppasswords → create for "Mail"
3. Copy the 16-character password

### 5. Test it
- Go to **Actions** tab → **Daily C2C Job Search** → **Run workflow**
- Check your email in ~2 minutes

## How it works
- Runs daily at **9:30 AM Colorado time**
- Searches **Indeed + ZipRecruiter + Google** with 5 targeted queries
- Scores each job **0-100%** against your 109 CV skills
- Tags **[C2C]** jobs automatically
- Emails you a **ranked list** with Apply buttons
- Tracks seen jobs so you only get **new ones**

## Update search keywords
Edit `SEARCHES` in `find_jobs.py`, push to GitHub. Next run uses new keywords.

## Files
```
find_jobs.py                    # The job finder script
.github/workflows/daily-jobs.yml # GitHub Actions schedule
```
