"""
BUPI Room Scanner & Spatial Target Triangulator
===============================================
Executes an autonomous rotational scan to map room obstacles and localize
possible warm moving human targets by correlating PIR thermal flux with
HC-SR04 ultrasonic echo reflections across 360 degrees.
"""

import math
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class ScanSectorSample:
    heading_deg: float
    relative_bearing_deg: float
    distance_cm: float
    pir_value: int
    is_warm_motion: bool
    epistemic_level: str

@dataclass
class DetectedTarget:
    target_id: int
    distance_m: float
    distance_cm: float
    relative_bearing_deg: float
    absolute_heading_deg: float
    direction_description: str
    confidence: str
    sample_count: int

@dataclass
class RoomScanReport:
    target_detected: bool
    distance_m: Optional[float]
    distance_cm: Optional[float]
    relative_bearing_deg: Optional[float]
    absolute_heading_deg: Optional[float]
    direction_description: str
    confidence: str
    verbal_report: str
    total_samples: int
    duration_seconds: float
    scan_profile: List[Dict[str, Any]]
    epistemic_ladder: Dict[str, str]
    people_count: int = 0
    targets: List[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("targets") is None:
            d["targets"] = []
        return d


class RoomScanner:
    def __init__(
        self,
        min_human_dist_cm: float = 20.0,
        max_human_dist_cm: float = 250.0
    ):
        self.min_dist = min_human_dist_cm
        self.max_dist = max_human_dist_cm
        self.samples: List[ScanSectorSample] = []
        self.start_heading_deg: float = 0.0

    def reset(self, initial_heading_deg: float = 0.0):
        self.samples.clear()
        self.start_heading_deg = initial_heading_deg

    def record_sample(
        self,
        heading_deg: float,
        distance_cm: float,
        pir_value: int
    ) -> ScanSectorSample:
        """
        Records a single angular sample during the scan sweep.
        """
        # Calculate relative bearing from start heading (-180 to +180)
        rel_bearing = (heading_deg - self.start_heading_deg + 180.0) % 360.0 - 180.0

        is_warm = (pir_value == 1)
        has_echo = (self.min_dist <= distance_cm <= self.max_dist)

        if is_warm and has_echo:
            epistemic = "POSSIBLE_HUMAN_CORRIDOR"
        elif is_warm and not has_echo:
            epistemic = "THERMAL_FLUX_OFF_AXIS"
        elif not is_warm and distance_cm < 100.0:
            epistemic = "INANIMATE_OBSTACLE"
        else:
            epistemic = "CLEAR_SPACE"

        sample = ScanSectorSample(
            heading_deg=round(heading_deg, 1),
            relative_bearing_deg=round(rel_bearing, 1),
            distance_cm=round(distance_cm, 1),
            pir_value=pir_value,
            is_warm_motion=is_warm,
            epistemic_level=epistemic
        )
        self.samples.append(sample)
        return sample

    def analyze_scan(self, duration_seconds: float = 0.0, is_count_query: bool = False) -> RoomScanReport:
        """
        Synthesizes all recorded angular samples into clustered spatial targets
        to pinpoint human presence, relative bearings, and distinct headcount.
        """
        if not self.samples:
            return RoomScanReport(
                target_detected=False,
                distance_m=None,
                distance_cm=None,
                relative_bearing_deg=None,
                absolute_heading_deg=None,
                direction_description="No scan samples recorded.",
                confidence="NONE",
                verbal_report="Scan aborted: No sensor samples gathered.",
                total_samples=0,
                duration_seconds=duration_seconds,
                scan_profile=[],
                epistemic_ladder={
                    "observation": "No data",
                    "measurement": "None",
                    "interpretation": "Incomplete scan",
                    "inference": "Unknown",
                    "decision": "HOLD",
                    "action": "STOP",
                    "report": "Scan incomplete"
                },
                people_count=0,
                targets=[]
            )

        # Find candidates where both PIR detected thermal flux and Ultrasonic reflected echo
        positive_candidates = [
            s for s in self.samples
            if s.is_warm_motion and (self.min_dist <= s.distance_cm <= self.max_dist)
        ]

        if positive_candidates:
            # 1. Sort candidates by heading angle (0 to 360)
            sorted_candidates = sorted(positive_candidates, key=lambda s: s.heading_deg)
            raw_clusters: List[List[ScanSectorSample]] = []
            curr_cluster: List[ScanSectorSample] = [sorted_candidates[0]]

            # Group samples into raw angular sectors (gap <= 30 deg of clear space)
            for s in sorted_candidates[1:]:
                prev_h = curr_cluster[-1].heading_deg
                diff = (s.heading_deg - prev_h) % 360.0
                if diff <= 30.0:
                    curr_cluster.append(s)
                else:
                    raw_clusters.append(curr_cluster)
                    curr_cluster = [s]
            if curr_cluster:
                raw_clusters.append(curr_cluster)

            # 2. Circular wrap-around merge across 359° and 0°
            if len(raw_clusters) > 1:
                wrap_gap = (raw_clusters[0][0].heading_deg - raw_clusters[-1][-1].heading_deg) % 360.0
                if wrap_gap <= 30.0:
                    raw_clusters[0] = raw_clusters[-1] + raw_clusters[0]
                    raw_clusters.pop()

            # 3. Adjacent cluster consolidation (merge body/posture fragments with gap <= 20°)
            merged_clusters: List[List[ScanSectorSample]] = []
            ci = 0
            while ci < len(raw_clusters):
                c = raw_clusters[ci]
                while ci + 1 < len(raw_clusters):
                    gap = (raw_clusters[ci+1][0].heading_deg - c[-1].heading_deg) % 360.0
                    if gap <= 20.0:
                        c = c + raw_clusters[ci+1]
                        ci += 1
                    else:
                        break
                merged_clusters.append(c)
                ci += 1

            # 4. Filter out transient acoustic noise (require at least 2 contiguous/valid samples)
            detected_targets: List[Dict[str, Any]] = []
            for cl in merged_clusters:
                # Reject single-sample glitches/spikes
                if len(cl) < 2:
                    continue

                cl_by_dist = sorted(cl, key=lambda s: s.distance_cm)
                med_sample = cl_by_dist[len(cl_by_dist) // 2]
                headings = [s.heading_deg for s in cl]
                center_heading = headings[len(headings) // 2]

                dist_cm = med_sample.distance_cm
                dist_m = round(dist_cm / 100.0, 2)
                rel_bearing = med_sample.relative_bearing_deg

                if abs(rel_bearing) <= 15.0:
                    direction_str = f"Directly ahead (bearing {rel_bearing:+.0f}°)"
                    relative_text = "directly in front of you"
                elif rel_bearing > 15.0:
                    direction_str = f"{abs(rel_bearing):.0f}° to your right"
                    relative_text = f"approximately {abs(rel_bearing):.0f} degrees to your right"
                else:
                    direction_str = f"{abs(rel_bearing):.0f}° to your left"
                    relative_text = f"approximately {abs(rel_bearing):.0f} degrees to your left"

                conf = "HIGH" if len(cl) >= 4 else "MEDIUM"

                target_dict = {
                    "target_id": len(detected_targets) + 1,
                    "distance_m": dist_m,
                    "distance_cm": dist_cm,
                    "relative_bearing_deg": rel_bearing,
                    "absolute_heading_deg": center_heading,
                    "direction_description": direction_str,
                    "relative_text": relative_text,
                    "confidence": conf,
                    "sample_count": len(cl)
                }
                detected_targets.append(target_dict)

            # Fallback if all were single-sample noise but positive candidates exist
            if not detected_targets and positive_candidates:
                best_s = sorted(positive_candidates, key=lambda s: s.distance_cm)[0]
                detected_targets.append({
                    "target_id": 1,
                    "distance_m": round(best_s.distance_cm / 100.0, 2),
                    "distance_cm": best_s.distance_cm,
                    "relative_bearing_deg": best_s.relative_bearing_deg,
                    "absolute_heading_deg": best_s.heading_deg,
                    "direction_description": "Nearby target",
                    "relative_text": "in room",
                    "confidence": "LOW",
                    "sample_count": 1
                })

            people_count = len(detected_targets)
            primary_target = detected_targets[0]

            # Generate natural language verbal debrief
            if people_count == 1:
                p = primary_target
                if is_count_query:
                    verbal_report = (
                        f"Scan complete across 360 degrees. I found 1 person in the room, "
                        f"located approximately {p['distance_m']} meters away, {p['relative_text']} at heading {p['absolute_heading_deg']:.0f} degrees."
                    )
                else:
                    verbal_report = (
                        f"Scan complete. Possible human presence detected approximately {p['distance_m']} meters away, "
                        f"{p['relative_text']} at heading {p['absolute_heading_deg']:.0f} degrees."
                    )
            else:
                target_summaries = []
                for t in detected_targets:
                    target_summaries.append(
                        f"Person {t['target_id']} at {t['distance_m']} meters, {t['relative_text']}"
                    )
                summary_text = "; ".join(target_summaries)
                verbal_report = (
                    f"Scan complete across 360 degrees. I detected {people_count} distinct people in the room: {summary_text}."
                )

            ladder = {
                "observation": f"PIR=HIGH across {len(positive_candidates)} samples; {people_count} angular clusters identified",
                "measurement": f"Count={people_count}; Primary Target Distance={primary_target['distance_m']}m; Bearing={primary_target['relative_bearing_deg']:+.1f}°",
                "interpretation": f"{people_count} distinct warm moving thermal corridors detected via acoustic-IR triangulation",
                "inference": f"Estimated {people_count} human target(s) localized in environment",
                "decision": "STOP_AND_REPORT",
                "action": "EMIT_DATA_REPORT",
                "report": verbal_report
            }

            return RoomScanReport(
                target_detected=True,
                distance_m=primary_target["distance_m"],
                distance_cm=primary_target["distance_cm"],
                relative_bearing_deg=primary_target["relative_bearing_deg"],
                absolute_heading_deg=primary_target["absolute_heading_deg"],
                direction_description=primary_target["direction_description"],
                confidence="HIGH" if people_count >= 1 and primary_target["confidence"] == "HIGH" else "MEDIUM",
                verbal_report=verbal_report,
                total_samples=len(self.samples),
                duration_seconds=round(duration_seconds, 1),
                scan_profile=[asdict(s) for s in self.samples],
                epistemic_ladder=ladder,
                people_count=people_count,
                targets=detected_targets
            )

        else:
            # Check if PIR detected heat flux without direct acoustic echo
            pir_only = [s for s in self.samples if s.is_warm_motion]
            if pir_only:
                rel_bearing = pir_only[0].relative_bearing_deg
                verbal_report = (
                    f"Scan complete. Infrared thermal motion detected near bearing {rel_bearing:+.0f}°, "
                    "but outside acoustic reflection range. Estimated 0 confirmed people."
                )
                conf = "LOW"
            else:
                verbal_report = (
                    "Scan complete across 360 degrees. I found 0 people. No human presence or thermal motion detected in the room."
                    if is_count_query else
                    "Scan complete. No human presence or thermal motion detected across 360 degrees."
                )
                conf = "NONE"

            ladder = {
                "observation": f"360-degree sweep: PIR={len(pir_only)} triggers, Ultrasonic clear",
                "measurement": f"Total samples={len(self.samples)}; Sweep duration={duration_seconds:.1f}s",
                "interpretation": "Environment clear of warm targets within sensing corridor",
                "inference": "0 people verified in immediate room range",
                "decision": "REPORT_AND_STANDBY",
                "action": "STANDBY",
                "report": verbal_report
            }

            return RoomScanReport(
                target_detected=False,
                distance_m=None,
                distance_cm=None,
                relative_bearing_deg=None,
                absolute_heading_deg=None,
                direction_description="Area clear",
                confidence=conf,
                verbal_report=verbal_report,
                total_samples=len(self.samples),
                duration_seconds=round(duration_seconds, 1),
                scan_profile=[asdict(s) for s in self.samples],
                epistemic_ladder=ladder,
                people_count=0,
                targets=[]
            )

