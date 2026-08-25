"""
ACSA GBP compliance guardrail — fail-closed.
Encodes the LOCKED rules in GBP-POSTS-COMPLIANCE-RULES.md (7 Aug 2026).
A post is only allowed if check() returns an empty list of violations.
"""
import re

ALLOWED_HOST = "https://acsamelbourne.com.au/"
ALLOWED_CTA = {"LEARN_MORE", "SIGN_UP", "BOOK", "ORDER", "SHOP"}  # never CALL (no phone)
ALLOWED_TYPES = {"Update", "Offer", "Event"}
CAPS_WHITELIST = {"ACSA", "WWCC"}

BANNED_PHRASES = [
    "spots are filling", "spots filling", "limited spot", "limited time", "limited",
    "hurry", "last chance", "act now", "don't miss", "dont miss",
    "guaranteed", "guarantee", "best price", "lowest price", "cheapest",
    "sale", "deal", "discount", "% off", "percent off", "off rrp",
    "#1", "number one", "book now before", "while stocks last", "ends soon",
    "offer ends", "today only", "special offer",
]

def _label_to_action(label):
    m = {"learn more": "LEARN_MORE", "sign up": "SIGN_UP", "book": "BOOK",
         "order online": "ORDER", "shop": "SHOP"}
    return m.get((label or "").strip().lower())

def check(copy, button_label, button_url, post_type="Update"):
    v = []
    text = copy or ""
    low = text.lower()

    # 1. button link must be acsamelbourne.com.au (no redirects/shorteners)
    url = (button_url or "").strip()
    if not url.lower().startswith(ALLOWED_HOST):
        v.append(f"button link must start with {ALLOWED_HOST} (got: {url or 'empty'})")
    for bad in ("sparkpages", "bit.ly", "tinyurl", "linktr", "rebrand.ly", "goo.gl", "t.co"):
        if bad in url.lower():
            v.append(f"button link contains banned redirect/shortener: {bad}")

    # 2. no phone numbers in body
    if re.search(r'\b(1800|1300|13\d{2})\b', text): v.append("phone-like number (1800/1300/13xx) in body")
    if re.search(r'\b0\d{3}[\s-]?\d{3}[\s-]?\d{3}\b', text): v.append("mobile number in body")
    if re.search(r'\+?61[\s-]?\d', text): v.append("+61 phone number in body")
    if re.search(r'\d{6,}', text): v.append("long digit run (looks like a phone number) in body")

    # 3. no URLs typed in body
    if re.search(r'https?://', low) or "www." in low: v.append("URL in body text")
    if re.search(r'\b[\w.-]+\.(com|au|net|io|org|co)\b', low): v.append("domain name in body text")

    # 4. no prices
    if "$" in text: v.append("price symbol ($) in body")
    if re.search(r'\b(aud|usd)\b', low): v.append("currency code in body")
    if re.search(r'\b\d+\s?(dollars|bucks)\b', low): v.append("price word in body")

    # 5. no urgency / hard-sell
    for p in BANNED_PHRASES:
        if p in low: v.append(f"banned urgency/hard-sell phrase: '{p}'")

    # 6. no ALL CAPS words (len>=4), max 1 emoji
    for tok in re.findall(r'\b[A-Za-z]{4,}\b', text):
        if tok.isupper() and tok not in CAPS_WHITELIST:
            v.append(f"ALL-CAPS word: {tok}")
    emojis = re.findall(r'[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF]', text)
    if len(emojis) > 1: v.append(f"too many emojis ({len(emojis)}; max 1)")

    # 7. post type + CTA
    if post_type not in ALLOWED_TYPES: v.append(f"post type must be one of {ALLOWED_TYPES}")
    if _label_to_action(button_label) is None:
        v.append(f"button label '{button_label}' not a valid GBP CTA")

    # 10. basic sanity
    if len(text.strip()) < 40: v.append("copy too short")
    if len(text) > 1450: v.append("copy over GBP 1500-char limit (leave margin)")

    return v

if __name__ == "__main__":
    # self-test
    ok = check("Our next 2-Week Beginner Course starts Monday 7 September at ACSA in Thornbury. Four coached Muay Thai sessions across two weeks, Mondays and Thursdays 7-8pm. No experience needed.",
               "Sign up", "https://acsamelbourne.com.au/muay-thai-beginner-course/")
    bad = check("Beginner Course only $97! Spots are filling fast, call 1800 736 888. www.sparkpages.io",
                "Sign up", "https://sparkpages.io/?i=x")
    print("clean ->", ok)
    print("dirty ->", bad)
