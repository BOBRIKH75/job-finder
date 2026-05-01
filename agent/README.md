# AI Job Application Agent

Self-learning AI agent that finds, filters, and applies to C2C Java jobs autonomously.

## Architecture

```
Discover (Dice MCP / jobspy) → Filter (ghost + skill match) → Apply (browser-use + Ollama) → Email (IMAP + Resend) → Learn (SQLite memory)
```

## Quick Start

```bash
./setup.sh                    # install everything
python3 agent.py --stats      # show dashboard
python3 agent.py --dry-run    # find + filter only
python3 agent.py              # full pipeline
```

## Modules

| Module | Purpose |
|--------|---------|
| `src/memory.py` | SQLite storage — applications, recruiters, patterns, audit log |
| `src/ghost_filter.py` | Ghost job detection — 9 signals, scores 0-100 |
| `src/ats_detector.py` | ATS identification — 11 systems, difficulty rating |
| `src/human_simulator.py` | Human behavior — Bézier mouse, variable typing |
| `src/email_handler.py` | IMAP read, outreach, follow-ups, throttling |
| `src/form_filler.py` | Form automation — field mapping, honeypot detection |
| `src/job_scout.py` | Job search, skill matching, rate extraction |
| `src/ollama_client.py` | Local LLM — cover letters, question answering |

## Self-Learning

- **Week 1-2**: Agent applies, you review first 10 applications
- **Week 3+**: Agent handles 80%+ alone, asks for edge cases only
- Ghost scores, ATS patterns, recruiter quality all improve over time

## Requirements

- Python 3.11+
- Ollama (brew install ollama)
- Chrome with `--remote-debugging-port=9222` for browser automation
