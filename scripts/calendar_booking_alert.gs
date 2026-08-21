/**
 * calendar_booking_alert.gs
 *
 * Runs every 5 minutes. When Google Calendar sends a "new booking" email,
 * this script pushes an urgent notification to ntfy.sh → iPhone ntfy app.
 *
 * Setup:
 * 1. script.google.com → New project → paste this file
 * 2. Edit NTFY_TOPIC to your private topic name
 * 3. Run → setTrigger() once to install the 5-minute trigger
 * 4. Authorize when prompted (needs Gmail read access)
 */

const NTFY_TOPIC = 'bobrikh75-cal-alerts-7x9q'; // CHANGE THIS — pick something unique/private
const ALREADY_NOTIFIED_LABEL = 'cal-notified';   // Gmail label to avoid double-alerts

function checkNewBookings() {
  // Google Calendar sends booking notifications from this address
  const search = [
    'from:calendar-notification@google.com',
    'subject:("New appointment" OR "appointment booked" OR "booking confirmed")',
    'is:unread',
    '-label:' + ALREADY_NOTIFIED_LABEL,
  ].join(' ');

  const threads = GmailApp.search(search, 0, 10);
  if (threads.length === 0) return;

  // Get or create the "already notified" label
  let label = GmailApp.getUserLabelByName(ALREADY_NOTIFIED_LABEL);
  if (!label) label = GmailApp.createLabel(ALREADY_NOTIFIED_LABEL);

  threads.forEach(thread => {
    const msg = thread.getMessages()[0];
    const subject = msg.getSubject();
    const snippet = msg.getPlainBody()
      .replace(/\s+/g, ' ')
      .substring(0, 200)
      .trim();

    _pushAlert(subject, snippet);

    // Tag + mark read so we don't alert twice
    thread.addLabel(label);
    thread.markRead();
  });
}

function _pushAlert(title, body) {
  const url = `https://ntfy.sh/${NTFY_TOPIC}`;
  try {
    UrlFetchApp.fetch(url, {
      method: 'post',
      headers: {
        'Title': '📅 ' + title,
        'Priority': 'urgent',    // shows as high-priority on iPhone
        'Tags': 'calendar,tada', // ntfy renders these as emoji
      },
      payload: body,
      muteHttpExceptions: true,
    });
  } catch (e) {
    Logger.log('ntfy push failed: ' + e.message);
  }
}

/** Run this ONCE to install the 5-minute trigger. */
function setTrigger() {
  // Remove any existing triggers for this function first
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'checkNewBookings')
    .forEach(t => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('checkNewBookings')
    .timeBased()
    .everyMinutes(5)
    .create();

  Logger.log('Trigger set: checkNewBookings runs every 5 minutes');
}

/** Test: manually push an alert to verify ntfy is working. */
function testAlert() {
  _pushAlert(
    'Test — recruiter booked a call!',
    'This is a test. If you see this on your iPhone, ntfy is working.'
  );
  Logger.log('Test alert sent to ntfy topic: ' + NTFY_TOPIC);
}
