# Greenhouse Application Form — CONFIRMED WORKING

> Tested and SUBMITTED 2026-08-17 on Thoughtworks job (token=8127765)
> Result: "Thank you! View more jobs at Thoughtworks" — APPLICATION ACCEPTED

## URL Format (CRITICAL)

```
https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}
```

Do NOT use: `job-boards.greenhouse.io/{company}/jobs/{id}` (redirects → iframe → broken)

## Working Playwright Code (tested, submitted successfully)

```python
from playwright.sync_api import sync_playwright

page.goto("https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}")
page.wait_for_selector("#first_name", timeout=15000)

# Text fields - fill() works fine
page.fill("#first_name", "Bob")
page.fill("#last_name", "Rikh")
page.fill("#email", "bobrikh75@gmail.com")
page.fill("#phone", "3472685917")

# Country (React Select) - click + type + click option
page.click("#country")
page.type("#country", "United States")
page.wait_for_selector("[class*=select__option]", timeout=5000)
page.click("[class*=select__option]:has-text('United States')")

# Location (React Select ASYNC) - click + type + WAIT for API + click option
page.click("#candidate-location")
page.type("#candidate-location", "Parker")
page.wait_for_selector("[class*=select__option]", timeout=10000)  # needs 3-5s
page.click("[class*=select__option]:has-text('Parker, Colorado')")

# Resume
page.set_input_files("#resume", "/path/to/resume.pdf")

# Custom questions (text)
page.fill("#question_*", "Parker")    # City
page.fill("#question_*", "Colorado")  # State
page.fill("#question_*", "United States")  # Country
page.fill("#question_*", "Online Job Board")  # How hear

# "Worked for TW" React Select dropdown → No
page.click("#question_68574540")  # or closest select__control
page.click("[class*=select__option]:has-text('No')")

# Acknowledged checkbox
page.click("input[type=checkbox]")

# Consent React Select → Yes
page.click("#question_68574542")  # or closest select__control
page.click("[class*=select__option]:has-text('Yes')")

# SUBMIT
page.click("button:has-text('Submit application')")
```

## Key Learnings

1. **Use embed URL** — direct form, no iframe, no "Apply now" click needed
2. **page.type() for React Select** — fires real keydown/input events that trigger async search
3. **page.click() for options** — real mouse click that React Select responds to
4. **wait_for_selector on options** — Location is ASYNC (3-5s wait for API)
5. **page.fill() for text inputs** — fast, works for non-React fields
6. **set_input_files for resume** — bypasses file dialog entirely
7. **Question IDs are job-specific** — match by label text in production code

## SMART_ANSWERS

```python
"worked for": "No",
"ever worked": "No",
"recording": "Yes",
"interview recording": "Yes",
"consent": "Yes",
"privacy": "Yes",
"acknowledge": "Yes",  # checkbox
"hear about": "Online Job Board",
```

## What DOESN'T Work (for future reference)

- ❌ CDP `Input.dispatchMouseEvent` — React Select ignores it for async selects
- ❌ `nativeInputValueSetter` — React doesn't see the change, no API call triggered
- ❌ JS `.click()` on options — React Select uses internal event handling
- ❌ ArrowDown + Enter via CDP — doesn't highlight options in async React Select
- ✅ Only Playwright's real `.type()` + `.click()` works (same as human)
