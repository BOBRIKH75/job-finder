#!/usr/bin/env python3
"""
CV Keyword Matcher — Paste a job description, see what matches your CV
and what's missing. Tailor your CV before applying.
Run: python3 ~/Downloads/CV/keyword_matcher.py
No AI needed — just Python.
"""
import re

MY_SKILLS = {
    'java','java 17','core java','spring boot','spring mvc','spring data','spring security',
    'spring aop','spring cloud','spring','microservices','microservice','rest','restful',
    'restful apis','rest api','api','apis','kafka','apache kafka','kubernetes','docker',
    'aws','aws cloud','amazon web services','postgresql','postgres','mongodb','cassandra',
    'oracle','sql','mysql','nosql','redis','graphql','hibernate','jpa','maven','gradle',
    'jenkins','ci/cd','git','github','jira','confluence','junit','junit 5','mockito',
    'selenium','cypress','cucumber','tdd','bdd','test-driven development','agile','scrum',
    'oauth2','openid','jwt','keycloak','spring security','angular','react','javascript',
    'typescript','html','css','bootstrap','thymeleaf','json','swagger','postman','open api',
    'splunk','datadog','slf4j','oop','object-oriented','solid','clean code','event-driven',
    'api gateway','web services','integration testing','unit testing','debugging','tomcat',
    'linux','terraform','lambda','elasticsearch','kibana','rabbitmq','devops','yaml','xml',
    'design patterns','multithreading','data structures','algorithms','dependency injection',
    'soap','automated tests','prompt engineering','copilot','amazon q','kiro',
    'c2c','corp-to-corp','green card',
}

NOISE = {
    'the','and','with','for','our','you','will','are','this','that','have','from','your',
    'can','all','been','has','was','were','they','their','into','also','more','than','other',
    'about','would','which','when','what','who','how','not','but','its','may','each','per',
    'new','one','two','use','used','work','team','role','must','able','year','years','plus',
    'strong','experience','including','working','using','such','well','good','best','high',
    'looking','join','build','help','make','take','lead','need','like','etc','ability',
    'required','preferred','minimum','senior','junior','level','position','job','company',
    'client','clients','business','develop','developing','development','design','designing',
    'implement','implementing','manage','managing','support','provide','ensure','create',
    'maintain','collaborate','communicate','drive','deliver','responsible','opportunity',
    'environment','solutions','system','application','applications','software','technology',
    'technical','skills','knowledge','across','within','based','related','complex','multiple',
    'various','key','core','day','full','time','part','remote','hybrid','onsite','salary',
    'benefits','equal','employer','candidate','qualifications','requirements','description',
}

def extract(text):
    """Extract tech keywords from job text using substring matching.
    Handles multi-word terms like 'Spring Boot', 'Apache Kafka', 'REST API'."""
    text_lower = text.lower()
    # Direct substring match for all known skills (handles multi-word)
    found_skills = {skill for skill in MY_SKILLS if skill in text_lower}

    # Also extract single-word tokens for gap detection
    words = set(re.findall(r'[a-z][a-z0-9/.#+\-]{1,30}', text_lower))
    # Add 2-word and 3-word phrases for gap detection
    tokens = re.findall(r'[a-z][a-z0-9/.#+\-]*', text_lower)
    for i in range(len(tokens) - 1):
        pair = tokens[i] + ' ' + tokens[i + 1]
        words.add(pair)
    for i in range(len(tokens) - 2):
        triple = tokens[i] + ' ' + tokens[i + 1] + ' ' + tokens[i + 2]
        words.add(triple)

    return words | found_skills

def match(job_text):
    jd = extract(job_text)
    matched = MY_SKILLS & jd
    # Only show single-word gaps that look like real tech terms
    missing = set()
    for k in (jd - MY_SKILLS):
        if k in NOISE or len(k) < 4 or k.endswith('.') or ' ' in k:
            continue
        missing.add(k)
    return matched, missing

if __name__ == '__main__':
    print('='*55)
    print('  CV Keyword Matcher — Bob Rikh')
    print('  Paste the job description below.')
    print('  Type END on a new line when done.')
    print('='*55)
    lines = []
    while True:
        line = input()
        if line.strip().upper() == 'END':
            break
        lines.append(line)

    matched, missing = match('\n'.join(lines))

    print(f'\n✅ MATCHED ({len(matched)} keywords already in your CV):')
    for k in sorted(matched):
        print(f'   ✓ {k}')

    print(f'\n⚠️  POTENTIAL GAPS ({len(missing)} keywords from job posting):')
    for k in sorted(missing):
        print(f'   ✗ {k}')

    pct = int(len(matched) / max(len(matched) + len(missing), 1) * 100)
    print(f'\n📊 MATCH SCORE: {pct}%')
    if pct >= 80:
        print('   → Strong match! Apply now.')
    elif pct >= 60:
        print('   → Good match. Add a few missing keywords to your bullets before applying.')
    else:
        print('   → Weak match. Consider adding more of the missing keywords or skip this role.')

    print('\n💡 TIP: Add missing keywords to your CV bullet points using')
    print('   the EXACT phrases from the job posting before you apply.')
