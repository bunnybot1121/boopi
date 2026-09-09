#!/usr/bin/env python3
"""
===============================================================================
BUPI DATA-CENTRIC MISSION & SENSOR QUERY CLI
===============================================================================
Accepts ANY natural language instruction, dynamically compiles it into an
executable robotic agent mission, executes closed-loop sensing and actuation,
and outputs the exact data (distances, headings, bearings, and raw sensors).

Zero UI overhead. Pure real-time robotic telemetry and data reporting.

Usage:
    python scripts/query_bupi.py "walk until an obstacle comes in front of you"
    python scripts/query_bupi.py "BUPI, are there any humans in the room?"
    python scripts/query_bupi.py "turn 90 degrees to the right"
    python scripts/query_bupi.py "stay still and alert me if anything moves"
    python scripts/query_bupi.py  # (Interactive prompt mode)
===============================================================================
"""

import os
import sys
import json
import time

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from agents.autonomous_goal_agent import goal_agent
from planner.instruction_decomposer import InstructionDecomposer

def run_instruction(instruction: str, format_json: bool = False):
    print("\n" + "=" * 70)
    print(f"🤖 BUPI COMMAND INPUT: \"{instruction}\"")
    print("=" * 70)

    # 1. Show Dynamic Decomposition
    decomposer = InstructionDecomposer()
    plan = decomposer.decompose(instruction)
    print(f"\n📋 [DYNAMIC MISSION COMPILATION]")
    print(f"  • Goal Name:          {plan.goal_name}")
    print(f"  • Policy Class:       {plan.policy_type.value}")
    print(f"  • Primary Action:     {plan.primary_action} @ {plan.speed_percent}% speed")
    print(f"  • Stopping Condition: {plan.stop_condition.description} ({plan.stop_condition.sensor} {plan.stop_condition.operator} {plan.stop_condition.threshold})")
    print(f"  • Active Sensors:     {', '.join(plan.sample_sensors)}")
    print(f"  • Timeout Window:     {plan.timeout_seconds:.1f}s")
    print("\n⚙️  [EXECUTING CLOSED-LOOP ACTUATOR & SENSOR LOOP] ...")

    # 2. Execute closed-loop mission
    start_ts = time.time()
    findings = goal_agent.run_mission_sync(instruction)
    elapsed = round(time.time() - start_ts, 2)

    # 3. Output Data Results
    print("\n" + "=" * 70)
    print("📊 [ACTUAL MISSION DATA & TELEMETRY REPORT]")
    print("=" * 70)
    print(f"  • Status:             {findings.get('status')}")
    print(f"  • Execution Duration: {findings.get('duration_seconds', elapsed)}s")

    # If obstacle / distance data present
    if "final_distance_cm" in findings:
        dist_cm = findings["final_distance_cm"]
        dist_m = findings.get("final_distance_m", round(dist_cm / 100.0, 2))
        print(f"  • Obstacle Distance:  {dist_cm:.1f} cm ({dist_m:.2f} meters)")
    if "distance_ahead_cm" in findings:
        print(f"  • Forward Clearance:  {findings['distance_ahead_cm']:.1f} cm")

    # If spatial presence localization present
    if "target_detected" in findings:
        detected = findings["target_detected"]
        print(f"  • Target Detected:    {'YES (Possible Human Presence)' if detected else 'NO (Area Clear)'}")
        if "people_count" in findings:
            print(f"  • People Count:       {findings['people_count']} distinct target(s)")
        if detected:
            print(f"  • Primary Distance:   {findings.get('distance_m')} m ({findings.get('distance_cm')} cm)")
            print(f"  • Relative Bearing:   {findings.get('relative_bearing_deg'):+.1f}° ({findings.get('direction_description')})")
            print(f"  • Absolute Heading:   {findings.get('absolute_heading_deg'):.1f}°")
            print(f"  • Confidence:         {findings.get('confidence')}")
            if findings.get("targets") and len(findings["targets"]) > 1:
                print(f"  • Multi-Target Clusters:")
                for t in findings["targets"]:
                    print(f"      - Target #{t['target_id']}: {t['distance_m']}m @ {t['relative_bearing_deg']:+.0f}° heading {t['absolute_heading_deg']:.0f}° ({t['direction_description']})")

    # Heading data
    if "heading_deg" in findings:
        print(f"  • Current Heading:    {findings['heading_deg']:.1f}°")
    elif "final_heading_deg" in findings:
        print(f"  • Final Heading:      {findings['final_heading_deg']:.1f}° (Rotated {findings.get('total_turned_deg', 0):.1f}°)")

    # Verbal Debrief
    print("\n🗣️  [VERBAL DEBRIEF]")
    verbal = findings.get("verbal_report") or findings.get("summary") or "Mission completed."
    print(f"  \"{verbal}\"")

    # Raw JSON Output
    print("\n📦 [STRUCTURED JSON DATA PAYLOAD]")
    clean_json = {k: v for k, v in findings.items() if k not in ["report_markdown", "scan_profile"]}
    print(json.dumps(clean_json, indent=2, ensure_ascii=False))

    if "scan_profile" in findings and findings["scan_profile"]:
        print(f"\n📡 [360° SENSOR SWEEP PROFILE] ({len(findings['scan_profile'])} sector samples recorded):")
        # Print a concise preview of scan points
        for sample in findings["scan_profile"][::max(1, len(findings["scan_profile"]) // 8)]:
            print(f"   Heading: {sample['heading_deg']:>5.1f}° | Bearing: {sample['relative_bearing_deg']:>+6.1f}° | Dist: {sample['distance_cm']:>5.1f}cm | PIR: {sample['pir_value']} | Level: {sample['epistemic_level']}")

    print("=" * 70 + "\n")
    return findings

def main():
    if len(sys.argv) > 1:
        instruction = " ".join(sys.argv[1:])
        run_instruction(instruction)
    else:
        print("=" * 70)
        print("🤖 BUPI INTERACTIVE DATA MISSION RUNNER")
        print("Type any natural language command (e.g. 'walk until an obstacle comes in front of you')")
        print("Type 'exit' or 'quit' to quit.")
        print("=" * 70)
        while True:
            try:
                cmd = input("\nBUPI > ").strip()
                if not cmd:
                    continue
                if cmd.lower() in ["exit", "quit", "q"]:
                    print("Exiting BUPI Mission Runner.")
                    break
                run_instruction(cmd)
            except (KeyboardInterrupt, EOFError):
                print("\nExiting.")
                break

if __name__ == "__main__":
    main()
