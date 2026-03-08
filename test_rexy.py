"""
REXY TEST HARNESS v4.0
Tests IntentDetector in isolation — no full pipeline, no WebSocket needed.

Usage:
    python test_rexy.py

Each test case runs the message through IntentDetector only
and checks if the returned intent matches the expected one.
Prints PASS / FAIL per case, then a summary.
"""

import sys
import os

# Make sure we can import from the rexy directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import IntentDetector

# ─────────────────────────────────────────────
# TEST CASES
# Format: (input_message, expected_intent)
# ─────────────────────────────────────────────
TEST_CASES = [
    # Greetings
    ("hello rexy",                          "GREET"),
    ("hey, what's up?",                     "GREET"),
    ("good morning",                        "GREET"),

    # Time
    ("what time is it",                     "GET_TIME"),
    ("tell me the current time",            "GET_TIME"),

    # Calculator — keyword activation
    ("calc 10+5",                           "CALCULATOR"),
    ("calculate 50-13",                     "CALCULATOR"),
    ("it's time to calculate 5*78",         "CALCULATOR"),

    # Calculator — math expression (pre-check, no keyword)
    ("10 + 25",                             "CALCULATOR"),
    ("100 / 4",                             "CALCULATOR"),
    ("3 * 7",                               "CALCULATOR"),

    # Files
    ("list my files",                       "LIST_FILES"),
    ("show me the files in this folder",    "LIST_FILES"),

    # Emotion support
    ("i'm feeling sad today",               "EMOTION_SUPPORT"),
    ("i'm really anxious about my exams",   "EMOTION_SUPPORT"),

    # Advisor (boredom)
    ("i'm so bored, i have nothing to do",  "ADVISOR"),
    ("suggest something fun",               "ADVISOR"),

    # Music
    ("play some music",                     "MUSIC"),
    ("i want to listen to chill songs",     "MUSIC"),

    # Reset
    ("reset",                               "RESET"),
    ("clear everything and start over",     "RESET"),

    # Chat (general knowledge fallback)
    ("what is the capital of france",       "CHAT"),
    ("who invented electricity",            "CHAT"),
    ("explain how gravity works",           "CHAT"),

    # ── WEATHER ──
    ("weather in Ahmedabad",                    "WEATHER"),
    ("what's the temperature in London",        "WEATHER"),
    ("is it raining in Berlin",                 "WEATHER"),
    ("how's the weather today in Tokyo",        "WEATHER"),

    # ── WEB SEARCH ──
    ("search who is the president of france",   "WEB_SEARCH"),
    ("search what is quantum computing",        "WEB_SEARCH"),
    ("look up Nikola Tesla",                    "WEB_SEARCH"),
    ("google latest AI news",                   "WEB_SEARCH"),

    # ── MEMORY ──
    ("remember that my exam is on March 20",    "MEMORY"),
    ("what do you remember about my exam",      "MEMORY"),
    ("forget about my exam",                    "MEMORY"),
    ("don't forget my sister's birthday",       "MEMORY"),

    # ── SYSTEM INFO ──
    ("cpu usage",                               "SYSTEM_INFO"),
    ("check battery",                           "SYSTEM_INFO"),
    ("how much ram is being used",              "SYSTEM_INFO"),
    ("storage usage",                           "SYSTEM_INFO"),
    ("how long has my pc been on",              "SYSTEM_INFO"),

    # ── FILE READ ──
    ("read notes.txt",                          "FILE_READ"),
    ("open my resume.docx",                     "FILE_READ"),
    ("show me inbox files",                     "FILE_READ"),

    # ── EDGE CASES ──
    ("memory usage",                            "SYSTEM_INFO"),  # not MEMORY
    ("ram usage",                               "SYSTEM_INFO"),  # not MEMORY
    ("what time is it in london",               "CHAT"),         # not GET_TIME
    ("when was einstein born",                  "CHAT"),         # not GET_TIME
    ("what is the capital of france",           "CHAT"),         # not WEB_SEARCH
    ]

# ─────────────────────────────────────────────
# TEST RUNNER
# ─────────────────────────────────────────────
def run_tests():
    """
    Run all test cases through IntentDetector.
    Print PASS or FAIL for each, then a final summary.
    """
    print("\n" + "=" * 60)
    print("  REXY TEST HARNESS v4.0 — IntentDetector")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0
    failures = []

    detector = IntentDetector()

    for i, (message, expected_intent) in enumerate(TEST_CASES, start=1):
        try:
            result = detector.detect(message, history=[])
            actual_intent = result.get("intent", "UNKNOWN")
            confidence    = result.get("confidence", 0.0)
            reliability   = result.get("reliability", "?")

            if actual_intent == expected_intent:
                status = "✅ PASS"
                passed += 1
            else:
                status = "❌ FAIL"
                failed += 1
                failures.append({
                    "case":     i,
                    "message":  message,
                    "expected": expected_intent,
                    "actual":   actual_intent,
                    "confidence": confidence
                })

            print(
                f"  [{i:02d}] {status} | "
                f"'{message[:40]:<40}' | "
                f"Expected: {expected_intent:<15} | "
                f"Got: {actual_intent:<15} | "
                f"Conf: {confidence:.2f} [{reliability}]"
            )

        except Exception as e:
            failed += 1
            print(f"  [{i:02d}] 💥 ERROR | '{message[:40]}' → {e}")
            failures.append({"case": i, "message": message, "error": str(e)})

    # Summary
    total = passed + failed
    print("\n" + "─" * 60)
    print(f"  RESULTS: {passed}/{total} passed")

    if failures:
        print("\n  FAILURES:")
        for f in failures:
            if "error" in f:
                print(f"    Case {f['case']:02d}: '{f['message']}' → ERROR: {f['error']}")
            else:
                print(
                    f"    Case {f['case']:02d}: '{f['message']}' "
                    f"→ Expected '{f['expected']}', got '{f['actual']}' "
                    f"(conf: {f['confidence']:.2f})"
                )
    else:
        print("\n  🎉 All tests passed!")

    print("─" * 60 + "\n")

    # Exit with error code if any tests failed (useful for CI later)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run_tests()
