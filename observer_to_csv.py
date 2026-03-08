#!/usr/bin/env python3
"""
REXY OBSERVABILITY v1 → CSV ANALYSIS TOOL
Pure post-processing | Rexy-agnostic | Privacy-safe
"""
import json
import csv
from datetime import datetime
from typing import Dict, Any
import os

LOG_FILE = "logs/rexy_observer.log"
CSV_FILE = "rexy_observer.csv"

CSV_HEADERS = [
    "timestamp", "event_type", "chosen_intent", "intent_confidence", "candidate_intents",
    "safety_stage", "safety_rule", "safety_result", "risk_level", 
    "execution_status", "latency_ms", "output_summary", "uncertainty_reason", "user_input_hash"
]

def parse_event(entry: Dict[str, Any]) -> list:
    """Extract fields for CSV row. Blank if N/A."""
    event_type = entry.get("event_type", "")
    payload = entry.get("payload", {})
    
    row = ["" for _ in CSV_HEADERS]
    
    # Common fields
    row[0] = entry.get("timestamp", "")  # timestamp
    row[1] = event_type                   # event_type
    row[12] = payload.get("user_hash", "") # user_input_hash
    
    # INTENT_SELECTED
    if event_type == "INTENT_SELECTED":
        row[2] = payload.get("intent", "")           # chosen_intent
        row[3] = str(payload.get("confidence", ""))  # intent_confidence
    
    # SAFETY_CHECK  
    elif event_type == "SAFETY_CHECK":
        row[6] = "verification"                      # safety_stage
        row[7] = payload.get("decision", "")         # safety_result
        row[8] = payload.get("risk_level", "")       # risk_level
    
    # EXECUTION_RESULT
    elif event_type == "EXECUTION_RESULT":
        row[9] = "completed"                         # execution_status
        row[11] = payload.get("reply_preview", "")   # output_summary
    
    # DECISION_NOTE
    elif event_type == "DECISION_NOTE":
        row[6] = "decision"                          # safety_stage
        row[7] = payload.get("decision", "")         # safety_result
    
    # UNCERTAINTY_FLAG
    elif event_type == "UNCERTAINTY_FLAG":
        row[13] = payload.get("reason", "")          # uncertainty_reason
        row[3] = str(payload.get("confidence", ""))  # intent_confidence
    
    return row

def analyze_logs():  # sourcery skip: extract-method, remove-redundant-fstring
    """Convert JSONL → CSV."""
    if not os.path.exists(LOG_FILE):
        print(f"❌ {LOG_FILE} not found. Run Rexy first.")
        return
    
    events = []
    
    # Parse log file
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                    events.append(parse_event(entry))
                except json.JSONDecodeError as e:
                    print(f"⚠️  Skipping malformed line {line_num}: {e}")
                    continue
    except FileNotFoundError:
        print(f"❌ {LOG_FILE} not found.")
        return
    
    # Write CSV
    try:
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
            writer.writerows(events)
        
        print(f"✅ {len(events)} events → {CSV_FILE}")
        print(f"📊 Breakdown:")
        intent_counts = {}
        for event in events:
            if event[2]:  # chosen_intent
                intent_counts[event[2]] = intent_counts.get(event[2], 0) + 1
        for intent, count in intent_counts.items():
            print(f"   {intent}: {count}")
            
    except Exception as e:
        print(f"❌ CSV write failed: {e}")

if __name__ == "__main__":
    print("🔍 REXY OBSERVER → CSV ANALYSIS")
    analyze_logs()
