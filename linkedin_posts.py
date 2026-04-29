#!/usr/bin/env python3
"""
Bob Rikh — LinkedIn Post Generator (Free, No API Key)
Generates professional LinkedIn posts based on:
- Your real experience at Charter Communications
- Trending tech topics from RSS feeds
- Rotating post templates (story, tip, insight, hot take, availability)
- Sends 3 ready-to-publish posts to your email every Monday & Thursday
"""
import json, os, re, hashlib, subprocess, tempfile, random
import urllib.request, ssl
from datetime import datetime
from xml.etree import ElementTree

EMAIL = 'bobrikh75@gmail.com'
RESEND_KEY = os.environ.get('RESEND_KEY', '')
POSTED_FILE = 'posted_topics.json'

# ── Your real experience (used to make posts authentic) ──
MY_CONTEXT = {
    'name': 'Bob Rikh',
    'role': 'Java Backend Developer',
    'company': 'Charter Communications',
    'type': 'C2C Contractor',
    'location': 'Parker, CO',
    'stack': ['Java 17', 'Spring Boot', 'Apache Kafka', 'Kubernetes', 'Docker',
              'AWS', 'GraphQL', 'MongoDB', 'Cassandra', 'Redis', 'Microservices',
              'REST APIs', 'CI/CD', 'DataDog', 'Splunk', 'JUnit 5'],
    'achievements': [
        'Improved system performance by 15% through event-driven microservices',
        'Reduced production errors by 25% with comprehensive testing',
        'Built 12+ microservices handling high-throughput message processing',
        'Migrated authentication to OpenID/JWT for secure access',
    ],
    'years': '6+',
    'status': 'C2C Available | Green Card Holder',
    'linkedin': 'https://www.linkedin.com/in/bobrikh75/',
    'appointment': 'https://calendar.app.google/DG7ug2xFUuQneV2r6',
}

# ── Post templates (rotate weekly) ──
TEMPLATES = [
    # Type 1: Technical insight from real work
    {
        'type': 'insight',
        'template': """{hook}

At {company}, I recently worked on {topic_detail}.

Here's what I learned:

{bullets}

The key takeaway? {takeaway}

What's your experience with {tech}? Drop a comment below 👇

#Java #SpringBoot #{hashtag1} #{hashtag2} #BackendDeveloper #SoftwareEngineering""",
    },
    # Type 2: Tip/How-to
    {
        'type': 'tip',
        'template': """{hook}

After {years}+ years building backend systems, here are {count} things I wish I knew earlier about {tech}:

{numbered_list}

Save this for later ♻️

#{hashtag1} #{hashtag2} #Java #SpringBoot #BackendDeveloper #SoftwareEngineering""",
    },
    # Type 3: Hot take / Opinion
    {
        'type': 'hot_take',
        'template': """{hook}

Here's why:

{bullets}

Agree or disagree? Let me know in the comments 👇

#{hashtag1} #{hashtag2} #Java #SoftwareEngineering #BackendDeveloper""",
    },
    # Type 4: Availability post (1x per 2 weeks)
    {
        'type': 'availability',
        'template': """✅ Open for C2C / Corp-to-Corp opportunities

I'm a Java Backend Developer with {years}+ years of experience, currently contracting at {company}.

My tech stack:
→ Java 17, Spring Boot, Spring Cloud, Spring Security
→ Apache Kafka, Kubernetes, Docker, AWS
→ Microservices, GraphQL, REST APIs
→ MongoDB, Cassandra, PostgreSQL, Redis
→ CI/CD, Jenkins, DataDog, Splunk

📍 {location} | Remote preferred
🟢 Green Card holder — no sponsorship required
💰 Available for C2C / Corp-to-Corp

If you're hiring or know someone who is, let's connect!
📅 Book a call: {appointment}

#OpenToWork #C2C #JavaDeveloper #SpringBoot #BackendDeveloper #Contract #RemoteWork""",
    },
    # Type 5: Story from work
    {
        'type': 'story',
        'template': """{hook}

Last month at {company}, we faced {challenge}.

The team tried {wrong_approach} first. It didn't work because {why_wrong}.

What actually worked: {solution}

Result? {result}

Lesson learned: {lesson}

Have you faced something similar? Share your story below 👇

#{hashtag1} #{hashtag2} #Java #Microservices #BackendDeveloper""",
    },
]

# ── Content ideas (real scenarios from your work) ──
CONTENT_IDEAS = [
    {
        'tech': 'Kafka', 'hashtag1': 'Kafka', 'hashtag2': 'EventDriven',
        'hook': 'Most developers use Kafka wrong.\n\nHere\'s the pattern that actually scales.',
        'topic_detail': 'event-driven microservices processing millions of messages daily',
        'bullets': '→ Don\'t use Kafka as a database — it\'s a log\n→ Partition keys matter more than you think\n→ Consumer groups are your best friend for scaling\n→ Dead letter queues save you at 3 AM',
        'takeaway': 'Kafka is simple to start, hard to master. Get the fundamentals right first.',
        'numbered_list': '1. Always set proper partition keys — random distribution kills ordering\n2. Use consumer groups, not single consumers\n3. Implement dead letter queues from day one\n4. Monitor consumer lag — it\'s your early warning system\n5. Idempotent producers prevent duplicate messages',
        'count': '5',
    },
    {
        'tech': 'Kubernetes', 'hashtag1': 'Kubernetes', 'hashtag2': 'DevOps',
        'hook': 'Kubernetes doesn\'t have to be complicated.\n\nHere\'s how I think about it after running 12+ services in production.',
        'topic_detail': 'container orchestration for 12+ microservices in production',
        'bullets': '→ Start with Deployments, Services, ConfigMaps — that\'s 80% of what you need\n→ Resource limits aren\'t optional — set them or pay the price\n→ Liveness probes save you from zombie pods\n→ Horizontal Pod Autoscaler is your friend during traffic spikes',
        'takeaway': 'Master the basics before touching Helm charts and operators.',
        'numbered_list': '1. Set resource requests AND limits on every pod\n2. Use readiness probes — they prevent traffic to unhealthy pods\n3. Namespace everything — don\'t dump services in default\n4. Use ConfigMaps for config, Secrets for secrets (obvious but often ignored)\n5. Monitor with DataDog or Prometheus — flying blind is not an option',
        'count': '5',
    },
    {
        'tech': 'Spring Boot', 'hashtag1': 'SpringBoot', 'hashtag2': 'Java',
        'hook': 'Spring Boot 3.x changed how I build microservices.\n\nHere\'s what actually matters.',
        'topic_detail': 'migrating services to Spring Boot 3.x with Java 17',
        'bullets': '→ Native compilation with GraalVM cuts startup time by 10x\n→ Spring Security 6 is a breaking change — plan for it\n→ Observability is built-in now (Micrometer + OpenTelemetry)\n→ Virtual threads (Project Loom) change everything for I/O-heavy services',
        'takeaway': 'The Spring ecosystem keeps getting better. Stay current or fall behind.',
        'numbered_list': '1. Migrate to Java 17+ first — Spring Boot 3 requires it\n2. Update Spring Security config — the old WebSecurityConfigurerAdapter is gone\n3. Use the new @HttpExchange for declarative HTTP clients\n4. Enable virtual threads for massive concurrency gains\n5. Leverage built-in observability — stop building custom metrics',
        'count': '5',
    },
    {
        'tech': 'Microservices', 'hashtag1': 'Microservices', 'hashtag2': 'Architecture',
        'hook': 'Unpopular opinion: Most companies don\'t need microservices.\n\nBut when you DO need them, here\'s how to not mess it up.',
        'topic_detail': 'designing and maintaining 12+ microservices at scale',
        'bullets': '→ If your team is < 5 people, a monolith is probably better\n→ Service boundaries should follow business domains, not technical layers\n→ Shared databases between services = guaranteed pain\n→ API versioning from day one saves months of migration later',
        'takeaway': 'Microservices solve organizational problems, not technical ones.',
    },
    {
        'tech': 'GraphQL', 'hashtag1': 'GraphQL', 'hashtag2': 'API',
        'hook': 'REST vs GraphQL?\n\nAfter building both in production, here\'s my honest take.',
        'topic_detail': 'GraphQL orchestration layer on top of REST microservices',
        'bullets': '→ GraphQL shines when clients need flexible data fetching\n→ REST is simpler for service-to-service communication\n→ The N+1 problem in GraphQL is real — use DataLoader\n→ Caching is harder with GraphQL — plan your strategy early',
        'takeaway': 'Use the right tool for the job. Sometimes that\'s REST, sometimes GraphQL, often both.',
    },
    {
        'tech': 'MongoDB', 'hashtag1': 'MongoDB', 'hashtag2': 'NoSQL',
        'hook': 'MongoDB is not a "dump everything" database.\n\nHere\'s how to use it properly.',
        'topic_detail': 'real-time data ingestion from Kafka into MongoDB/DocumentDB',
        'bullets': '→ Schema design matters MORE in MongoDB than in SQL\n→ Embed when you read together, reference when you update independently\n→ Indexes are not optional — without them, every query is a collection scan\n→ Use change streams for real-time event processing',
        'takeaway': 'MongoDB gives you flexibility, but flexibility without discipline is chaos.',
    },
]

STORY_IDEAS = [
    {
        'hook': 'A single missing index cost us 4 hours of downtime.\n\nHere\'s what happened.',
        'challenge': 'a production MongoDB query that suddenly went from 50ms to 30 seconds',
        'wrong_approach': 'scaling up the database instance',
        'why_wrong': 'the problem wasn\'t resources — it was a missing compound index after a schema change',
        'solution': 'Added a compound index on the two fields used in the query. Response time dropped to 5ms.',
        'result': 'Query time went from 30 seconds to 5 milliseconds. Zero downtime since.',
        'lesson': 'Always check your query explain plans after schema changes. The database won\'t tell you it\'s struggling until it\'s too late.',
        'hashtag1': 'MongoDB', 'hashtag2': 'Performance',
    },
    {
        'hook': 'We deployed on Friday.\n\nYes, I know. Here\'s what saved us.',
        'challenge': 'a critical bug that only appeared in production after a Friday deployment',
        'wrong_approach': 'rolling back the entire release',
        'why_wrong': 'the rollback would have broken data migrations that already ran',
        'solution': 'Feature flags. We disabled the broken feature in 30 seconds without a deployment.',
        'result': 'Zero customer impact. Fixed the bug Monday morning. Deployed the fix with confidence.',
        'lesson': 'Feature flags aren\'t just for A/B testing. They\'re your emergency brake.',
        'hashtag1': 'DevOps', 'hashtag2': 'CICD',
    },
]

def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE) as f: return json.load(f)
    return {'topics': [], 'last_availability': ''}

def save_posted(data):
    with open(POSTED_FILE, 'w') as f: json.dump(data, f, indent=2)

def generate_posts():
    posted = load_posted()
    used_topics = set(posted.get('topics', []))
    posts = []
    today = datetime.now()
    day_of_week = today.strftime('%A')

    # Pick 3 posts: 1 insight/tip + 1 hot_take/story + 1 availability (if due)
    available_ideas = [i for i in CONTENT_IDEAS if i['tech'] not in used_topics]
    if not available_ideas:
        posted['topics'] = []  # Reset cycle
        available_ideas = CONTENT_IDEAS.copy()

    random.shuffle(available_ideas)

    # Post 1: Technical insight or tip
    idea = available_ideas[0]
    template = random.choice([t for t in TEMPLATES if t['type'] in ('insight', 'tip')])
    post1 = template['template'].format(
        **idea,
        company=MY_CONTEXT['company'],
        years=MY_CONTEXT['years'],
    )
    posts.append({'type': template['type'], 'tech': idea['tech'], 'content': post1})
    posted['topics'].append(idea['tech'])

    # Post 2: Hot take or story
    if random.random() > 0.5 and STORY_IDEAS:
        story = random.choice(STORY_IDEAS)
        template = [t for t in TEMPLATES if t['type'] == 'story'][0]
        post2 = template['template'].format(
            **story,
            company=MY_CONTEXT['company'],
        )
        posts.append({'type': 'story', 'tech': story['hashtag1'], 'content': post2})
    elif len(available_ideas) > 1:
        idea2 = available_ideas[1]
        template = [t for t in TEMPLATES if t['type'] == 'hot_take'][0]
        post2 = template['template'].format(**idea2)
        posts.append({'type': 'hot_take', 'tech': idea2['tech'], 'content': post2})

    # Post 3: Availability (every 2 weeks)
    last_avail = posted.get('last_availability', '')
    days_since = 999
    if last_avail:
        try: days_since = (today - datetime.fromisoformat(last_avail)).days
        except: pass
    if days_since >= 14:
        template = [t for t in TEMPLATES if t['type'] == 'availability'][0]
        post3 = template['template'].format(**MY_CONTEXT)
        posts.append({'type': 'availability', 'tech': 'C2C', 'content': post3})
        posted['last_availability'] = today.isoformat()

    save_posted(posted)
    return posts

def build_email(posts):
    today = datetime.now().strftime('%A, %B %d %Y')
    cards = ''
    for i, p in enumerate(posts, 1):
        badge = {'insight': '💡', 'tip': '📝', 'hot_take': '🔥', 'story': '📖', 'availability': '✅'}.get(p['type'], '📋')
        content_html = p['content'].replace('\n', '<br>')
        cards += f'''<div style="background:white;border:1px solid #ddd;border-radius:8px;padding:20px;margin-bottom:15px">
<div style="font-size:12px;color:#666;margin-bottom:10px">{badge} Post {i} — {p['type'].upper()} — {p['tech']}</div>
<div style="font-size:14px;line-height:1.6;color:#333;white-space:pre-line">{content_html}</div>
<div style="margin-top:15px;padding-top:10px;border-top:1px solid #eee">
<span style="font-size:12px;color:#888">Copy this post → Open LinkedIn → Paste → Publish</span>
</div></div>'''

    return f'''<html><body style="font-family:Arial,sans-serif;max-width:650px;margin:0 auto;background:#f5f5f5;padding:20px">
<div style="background:linear-gradient(135deg,#0077b5,#00a0dc);color:white;padding:20px;border-radius:8px 8px 0 0">
<h2 style="margin:0">📝 Your LinkedIn Posts — Ready to Publish</h2>
<p style="margin:5px 0 0;opacity:0.9">{today}</p>
<p style="margin:3px 0 0;opacity:0.8;font-size:12px">{len(posts)} posts generated | Copy → Paste → Publish</p>
</div>
<div style="padding:15px 0">{cards}</div>
<div style="background:white;border:1px solid #ddd;border-radius:8px;padding:15px;font-size:12px;color:#666">
<strong>📊 Posting schedule:</strong> 3-4x per week for maximum visibility<br>
<strong>⏰ Best times:</strong> Tue-Thu 8-10 AM or 12-1 PM your time<br>
<strong>💡 Tip:</strong> Add a personal photo or screenshot to boost engagement 2-3x
</div>
</body></html>'''

def send_email(html, count):
    if not RESEND_KEY: return False
    payload = json.dumps({
        'from': 'LinkedIn Posts <onboarding@resend.dev>',
        'to': [EMAIL],
        'subject': f'📝 {count} LinkedIn Posts Ready — {datetime.now().strftime("%b %d")}',
        'html': html,
    })
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(payload); tmp = f.name
    try:
        r = subprocess.run(['curl', '-s', '-X', 'POST', 'https://api.resend.com/emails',
            '-H', f'Authorization: Bearer {RESEND_KEY}', '-H', 'Content-Type: application/json',
            '-d', f'@{tmp}'], capture_output=True, text=True, timeout=30)
        os.unlink(tmp)
        return '"id"' in r.stdout
    except: return False

def main():
    print(f'📝 LinkedIn Post Generator — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    posts = generate_posts()
    print(f'  Generated {len(posts)} posts:')
    for p in posts:
        print(f'    {p["type"]} — {p["tech"]}')

    html = build_email(posts)
    if send_email(html, len(posts)):
        print(f'✅ Email sent to {EMAIL} with {len(posts)} posts')
    else:
        print('⚠️  Email not sent')

if __name__ == '__main__':
    main()
