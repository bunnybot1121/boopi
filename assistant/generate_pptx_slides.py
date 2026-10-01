"""
BUPI SIH Problem Statement 26201 — Presentation Deck Generator
Generates a 16:9 widescreen PowerPoint presentation (.pptx) based on the ground-truth technical audit.
"""

import sys
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_presentation():
    prs = Presentation()
    # 16:9 Widescreen dimensions
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Theme Colors
    BG_COLOR = RGBColor(15, 23, 42)        # Slate 900
    CARD_BG = RGBColor(30, 41, 59)         # Slate 800
    TEXT_MAIN = RGBColor(248, 250, 252)    # Slate 50
    TEXT_MUTED = RGBColor(148, 163, 184)   # Slate 400
    ACCENT_CYAN = RGBColor(14, 165, 233)   # Sky 500
    ACCENT_GREEN = RGBColor(34, 197, 94)   # Emerald 500
    ACCENT_AMBER = RGBColor(245, 158, 11)  # Amber 500
    BORDER_COLOR = RGBColor(51, 65, 85)    # Slate 700

    def apply_background(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_COLOR
        bg.line.fill.background()
        return bg

    def add_header(slide, title_text, category_text="SIH PROBLEM STATEMENT 26201 | GROUND-TRUTH ARCHITECTURE"):
        # Category Tag
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.4))
        tf_cat = cat_box.text_frame
        tf_cat.word_wrap = True
        p_cat = tf_cat.paragraphs[0]
        p_cat.text = category_text.upper()
        p_cat.font.size = Pt(10)
        p_cat.font.bold = True
        p_cat.font.color.rgb = ACCENT_CYAN

        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.7), Inches(0.8))
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.size = Pt(22)
        p.font.bold = True
        p.font.color.rgb = TEXT_MAIN

    def add_card(slide, left, top, width, height, title, body_bullets, accent=ACCENT_CYAN):
        # Card Background
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)

        # Card Text Frame
        tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.2), width - Inches(0.4), height - Inches(0.4))
        tf = tb.text_frame
        tf.word_wrap = True

        # Card Title
        p0 = tf.paragraphs[0]
        p0.text = title
        p0.font.size = Pt(14)
        p0.font.bold = True
        p0.font.color.rgb = accent

        # Card Bullets
        for item in body_bullets:
            p = tf.add_paragraph()
            p.text = f"• {item}"
            p.font.size = Pt(11)
            p.font.color.rgb = TEXT_MAIN
            p.space_after = Pt(4)

    # -------------------------------------------------------------
    # SLIDE 1: Title Slide
    # -------------------------------------------------------------
    s1 = prs.slides.add_slide(blank_layout)
    apply_background(s1)
    
    t_box = s1.shapes.add_textbox(Inches(1.0), Inches(1.8), Inches(11.3), Inches(3.0))
    tf1 = t_box.text_frame
    tf1.word_wrap = True
    
    p_tag = tf1.paragraphs[0]
    p_tag.text = "SMART INDIA HACKATHON 2026 | PROBLEM STATEMENT 26201"
    p_tag.font.size = Pt(13)
    p_tag.font.bold = True
    p_tag.font.color.rgb = ACCENT_CYAN
    p_tag.space_after = Pt(10)
    
    p_main = tf1.add_paragraph()
    p_main.text = "BUPI: Dual-Personality Autonomous Robotics\n& Intelligent Desktop Companion"
    p_main.font.size = Pt(32)
    p_main.font.bold = True
    p_main.font.color.rgb = TEXT_MAIN
    p_main.space_after = Pt(14)

    p_sub = tf1.add_paragraph()
    p_sub.text = "Ground-Truth Software Architecture, Edge Autonomy & Heterogeneous Swarm Audit"
    p_sub.font.size = Pt(16)
    p_sub.font.color.rgb = TEXT_MUTED

    # Highlights Bottom Row
    add_card(s1, Inches(1.0), Inches(5.0), Inches(3.5), Inches(1.8), "Mode 1: Desktop Companion", [
        "100% Electron Desktop UI",
        "Faster-Whisper Voice STT",
        "Edge-TTS & Google Gemini Brain"
    ], ACCENT_CYAN)

    add_card(s1, Inches(4.9), Inches(5.0), Inches(3.5), Inches(1.8), "Mode 2: Autonomous Robotics", [
        "100% Offline 3-Tier Intelligence",
        "20Hz Closed-Loop Goal Agent",
        "Dual ESP32 Swarm Coordination"
    ], ACCENT_GREEN)

    add_card(s1, Inches(8.8), Inches(5.0), Inches(3.5), Inches(1.8), "Extensible Hardware Engine", [
        "Dynamic C++ Firmware Ingestion",
        "SQLite FTS5 RAG & Auto-Flasher",
        "Bit-World Engine Digital Twin"
    ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 2: Problem Statement Trilemma
    # -------------------------------------------------------------
    s2 = prs.slides.add_slide(blank_layout)
    apply_background(s2)
    add_header(s2, "Engineering Realities: Solving the Edge Robotics Trilemma")

    add_card(s2, Inches(0.8), Inches(1.6), Inches(3.6), Inches(5.2), "1. Latency & Determinism", [
        "Problem: Cloud LLMs take 2-6s, making physical collision evasion impossible.",
        "BUPI Solution: 3-Tier Routing Architecture.",
        "Tier 1: Deterministic Python regex (<5ms) for E-Stop and direct moves.",
        "Tier 2: Local Ollama llama3.2:3b (~500ms) for single-turn tool calling.",
        "Verified Metric: <5ms response on all emergency stop commands in router_agent.py."
    ], ACCENT_CYAN)

    add_card(s2, Inches(4.8), Inches(1.6), Inches(3.6), Inches(5.2), "2. Disconnected Field Reliability", [
        "Problem: Subterranean and disaster zones have zero internet connection.",
        "BUPI Solution: 100% Local-First Edge Operations.",
        "Local Faster-Whisper on CPU/GPU.",
        "Local Mosquitto MQTT & WebSockets.",
        "20Hz autonomous goal loop executes offline without a single cloud packet.",
        "Verified Metric: Zero cloud dependencies required for Mode 2 robotic mission."
    ], ACCENT_GREEN)

    add_card(s2, Inches(8.8), Inches(1.6), Inches(3.6), Inches(5.2), "3. Hardware Heterogeneity", [
        "Problem: Traditional robotic codebases hardcode pinouts and sensor logic.",
        "BUPI Solution: Physical Sensor Specialization & Dynamic Ingestion.",
        "Bot 1 Scout handles PIR human sensing & pathfinding.",
        "Bot 2 Specialist handles MQ-2 gas & microclimate triage.",
        "Dynamic C++ ingestion compiles & flashes new peripherals on the fly."
    ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 3: Layered Software Architecture
    # -------------------------------------------------------------
    s3 = prs.slides.add_slide(blank_layout)
    apply_background(s3)
    add_header(s3, "Verified Layered Software Architecture")

    layers = [
        ("Layer 1: Presentation & Cockpit", "100% Electron (Chromium / Node.js). 3D Mascot (Three.js/Rive) + Central Hub (11 Tabs). Headless PyQt6.", ACCENT_CYAN),
        ("Layer 2: Voice Audio Pipeline", "16kHz Faster-Whisper (tiny.en) + WebRTC VAD + Edge-TTS with offline SAPI5 pyttsx3 fallback.", ACCENT_CYAN),
        ("Layer 3: 3-Tier Intelligence Engine", "Tier 1 (<5ms regex) -> Tier 2 (Ollama llama3.2:3b tool caller) -> Tier 3 (Hierarchical CrewAI fallback).", ACCENT_GREEN),
        ("Layer 4: Autonomy & Mission Planning", "AutonomousGoalAgent (20Hz loop, 11 policies) + InstructionDecomposer + 5-Stage Obstacle Detour.", ACCENT_GREEN),
        ("Layer 5: Safety & Epistemic Fusion", "15.0s Telemetry TTL Watchdog + Gas Safety Barrier + IMU 1.20g Gait Step Counting & RSSI Path Loss.", ACCENT_AMBER),
        ("Layer 6: Communication & Bridge Fabric", "Local Mosquitto MQTT (1883) + WebSocket Server (8767) + USB Serial COM3 (115200 baud) on Hotspot.", ACCENT_AMBER),
        ("Layer 7: Physical Embedded Swarm", "Bot 1 Scout (HC-SR04, PIR, MPU6050) & Bot 2 Specialist (MQ-2 Gas, DHT22 Climate, HC-SR04, MPU6050).", ACCENT_CYAN)
    ]

    top_y = 1.6
    for title, desc, acc in layers:
        card = s3.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(top_y), Inches(11.7), Inches(0.68))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = acc
        card.line.width = Pt(1)

        tb = s3.shapes.add_textbox(Inches(1.0), Inches(top_y + 0.05), Inches(11.3), Inches(0.6))
        tf = tb.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = title
        p1.font.size = Pt(11)
        p1.font.bold = True
        p1.font.color.rgb = acc
        p2 = tf.add_paragraph()
        p2.text = desc
        p2.font.size = Pt(9.5)
        p2.font.color.rgb = TEXT_MAIN
        top_y += 0.74

    # -------------------------------------------------------------
    # SLIDE 4: Production Runtime & Process Architecture
    # -------------------------------------------------------------
    s4 = prs.slides.add_slide(blank_layout)
    apply_background(s4)
    add_header(s4, "Production Runtime & Inter-Process Architecture")

    add_card(s4, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Multi-Process Execution Tree", [
        "Launcher: Run_Bupi_Robot.bat initializes system.",
        "Mosquitto MQTT Broker: Service started on port 1883.",
        "Ollama Daemon: Started via ollama serve on port 11434.",
        "Hotspot Gateway: ensure_hotspot.ps1 binds 192.168.137.1.",
        "Electron Main (main.js): Renders mascot & central hub.",
        "Python Mode 1 (main.py): Spawns STT, TTS, and hardware server.",
        "Python Mode 2 (run_mode2.py): Dedicated robotics decision daemon."
    ], ACCENT_CYAN)

    add_card(s4, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Asynchronous IPC Channels", [
        "Electron <--> Python Mode 1: Bidirectional stdin/stdout JSON lines.",
        "Mode 1 <--> Mode 2: Local Mosquitto MQTT broker.",
        "- bupi/internal/utterance: Spoken words routed to Mode 2.",
        "- bupi/internal/tts: Robot speech spoken via Mode 1 audio.",
        "- bupi/internal/estop: Broadcast emergency stop across processes.",
        "Host PC <--> ESP32 Nodes: WebSockets on ws://192.168.137.1:8767.",
        "Fallback Serial: USB UART COM3 auto-supervisor at 115200 baud."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 5: 3-Tier Decision Pipeline
    # -------------------------------------------------------------
    s5 = prs.slides.add_slide(blank_layout)
    apply_background(s5)
    add_header(s5, "3-Tier Decision Pipeline: Sub-Second Edge Intelligence")

    add_card(s5, Inches(0.8), Inches(1.6), Inches(3.6), Inches(5.2), "Tier 1: RouterAgent (<5ms)", [
        "Technology: Deterministic Python Regex.",
        "Location: agents/router_agent.py:80.",
        "Commands Handled: Emergency stop ('stop', 'halt', 'freeze'), direct movement, basic sensor queries.",
        "Properties: Zero AI hallucination, microsecond response, bypasses network latency.",
        "Escalation: Unmatched utterances pass to Tier 2."
    ], ACCENT_CYAN)

    add_card(s5, Inches(4.8), Inches(1.6), Inches(3.6), Inches(5.2), "Tier 2: Local Orchestrator (~500ms)", [
        "Technology: Local Ollama llama3.2:3b / llama3.1:8b.",
        "Location: agents/local_orchestrator.py:230.",
        "Capabilities: Single-turn function calling with 12 OpenAI-compatible tool schemas.",
        "Properties: 100% offline edge execution, tool parameter extraction, autonomous mission dispatch.",
        "Escalation: Connection errors or complexity escalate to Tier 3."
    ], ACCENT_GREEN)

    add_card(s5, Inches(8.8), Inches(1.6), Inches(3.6), Inches(5.2), "Tier 3: RoboticCrew (5-15s)", [
        "Technology: Hierarchical CrewAI Multi-Agent System.",
        "Location: agents/robotic_crew.py:123.",
        "Sequential Fallback Chain:",
        "1. Local Ollama llama3.2:3b",
        "2. Local Ollama llama3.1:8b",
        "3. Google Gemini 2.5 Flash",
        "4. Groq llama-3.3-70b-versatile",
        "5. NVIDIA DeepSeek / OpenRouter",
        "Multi-Agent Roles: Scout Analyst, Specialist, Commander."
    ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 6: Autonomous Goal Agent & 20Hz Closed Loop
    # -------------------------------------------------------------
    s6 = prs.slides.add_slide(blank_layout)
    apply_background(s6)
    add_header(s6, "Autonomous Goal Agent: 20Hz Closed-Loop Control")

    add_card(s6, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "20Hz Observe-Reason-Act Cycle", [
        "Frequency: Dedicated 20Hz thread (50ms period).",
        "Code Location: agents/autonomous_goal_agent.py:152.",
        "1. OBSERVE (5ms): Fetch latest telemetry from bupi_node_server.",
        "- Ultrasonic distance, MPU6050 IMU, PIR motion, MQ-2 gas.",
        "- Feed telemetry into kinematics odometry engine.",
        "2. REASON (10ms): Match against active policy & safety rules.",
        "- Dynamic stage check: distance met, target acquired, gas alert.",
        "3. ACT (5ms): Dispatch motor vectors via MQTT.",
        "- Stream live mission progress to Electron 2D arena canvas."
    ], ACCENT_CYAN)

    add_card(s6, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "11 Implemented Mission Policies", [
        "Decomposer: Natural language -> DynamicMissionPlan.",
        "Code Location: planner/instruction_decomposer.py:588.",
        "Supported Autonomous Behaviors:",
        "• EXPLORE_AND_MAP: Corridor exploration with sonar bounds.",
        "• SURVIVOR_SEARCH: Thermopile / PIR human detection search.",
        "• GAS_LEAK_INVESTIGATION: Gradient tracking to toxic gas source.",
        "• PATROL_PERIMETER: Perimeter surveillance pathing.",
        "• TARGET_APPROACH & RETURN_TO_ORIGIN: Coordinate traversal.",
        "• COLLABORATIVE_SWARM_SWEEP: Dual-rover tandem sweep."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 7: Reactive Obstacle Flank & Detour
    # -------------------------------------------------------------
    s7 = prs.slides.add_slide(blank_layout)
    apply_background(s7)
    add_header(s7, "Reactive Obstacle Flank & Detour Engine")

    add_card(s7, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Deterministic 5-Stage Geometric Detour", [
        "Location: core/obstacle_bypass_engine.py:40.",
        "Trigger: Ultrasonic range <= 15.0cm during mission.",
        "Stage 1: REVERSE 15cm from hazard point.",
        "Stage 2: PIVOT 60° right to clear obstacle boundary.",
        "Stage 3: ADVANCE 30cm along lateral flank.",
        "Stage 4: COUNTER-PIVOT -60° to restore original heading.",
        "Stage 5: RESUME MISSION along original vector.",
        "Zero AI Overhead: Pure deterministic state machine ensures immediate reaction without model stalls."
    ], ACCENT_CYAN)

    add_card(s7, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Kinematic & Safety Integration", [
        "Odometry Tracking: Integrates with kinematics_odometry.py to measure exact angular and linear displacement.",
        "Secondary Hazard Guard: If a second obstacle appears during the bypass maneuver, the engine aborts immediately into E-Stop.",
        "Safety Interlock: Verified dev build has firmware cutoff disabled (ENABLE_OBSTACLE_CUTOFF 0) to avoid bench stalls.",
        "Production Readiness: One-line flag toggle in bupi_bot1_scout.ino enables physical hardware barrier at 15cm."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 8: Heterogeneous Multi-Robot Swarm
    # -------------------------------------------------------------
    s8 = prs.slides.add_slide(blank_layout)
    apply_background(s8)
    add_header(s8, "Heterogeneous Multi-Robot Swarm: Scout & Specialist")

    bot_img_path = os.path.join(os.path.dirname(__file__), "assets", "bupi_dual_rovers.jpg")
    if os.path.exists(bot_img_path):
        # Embed High-Resolution Physical Hardware Photo (16:9 aspect ratio)
        s8.shapes.add_picture(bot_img_path, Inches(0.8), Inches(1.6), width=Inches(5.8), height=Inches(3.26))
        # Add Swarm Interlock Card underneath the photo
        add_card(s8, Inches(0.8), Inches(5.0), Inches(5.8), Inches(1.8), "Tandem Fusion & Swarm Interlock", [
            "SwarmCoordinator fuses scout corridor profile with specialist gas data.",
            "Tandem operation: Bot 1 navigates advance while Bot 2 profiles hazards.",
            "Evacuation Trigger: Gas > 350ppm broadcasts simultaneous emergency stop."
        ], ACCENT_GREEN)
        # Right Top: Bot 1 Scout
        add_card(s8, Inches(6.8), Inches(1.6), Inches(5.7), Inches(2.55), "Bot 1: Reconnaissance Scout (bupi_01)", [
            "Sensors: HC-SR04 Ultrasonic (GPIO 5/18), MPU6050 6-Axis IMU, PIR Motion Sensor.",
            "Actuation: TB6612FNG Dual H-Bridge driving 2x N20 Gearmotors (4WD chassis).",
            "Mission Role: Rapid corridor advance, thermal survivor detection, obstacle mapping."
        ], ACCENT_CYAN)
        # Right Bottom: Bot 2 Specialist
        add_card(s8, Inches(6.8), Inches(4.3), Inches(5.7), Inches(2.55), "Bot 2: Environmental Specialist (bupi_02)", [
            "Sensors: MQ-2 Toxic Gas, MQ-135 Air Quality, DHT22 Climate, HC-SR04, MPU6050.",
            "Actuation: TB6612FNG Dual H-Bridge driving 2x N20 Gearmotors (4WD chassis).",
            "Mission Role: Atmospheric hazard triage, microclimate & explosive gas plume profiling."
        ], ACCENT_AMBER)
    else:
        add_card(s8, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Bot 1: Reconnaissance Scout (bupi_01)", [
            "Microcontroller: ESP32 Dev Module (240MHz Xtensa LX6).",
            "Firmware: firmware/bupi_bot1_scout.ino.",
            "Sensors: HC-SR04 Ultrasonic (GPIO 5/18), MPU6050 6-Axis IMU (I2C 0x68), PIR Motion Sensor (GPIO 34/19).",
            "Actuation: TB6612FNG Dual H-Bridge driving 2x N20 Gearmotors.",
            "Mission Role: Rapid advance, survivor detection, corridor mapping.",
            "Sensor Note: Does NOT read MQ-2 gas or DHT22 climate."
        ], ACCENT_CYAN)

        add_card(s8, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Bot 2: Environmental Specialist (bupi_02)", [
            "Microcontroller: ESP32 Dev Module (240MHz Xtensa LX6).",
            "Firmware: firmware/bupi_bot2_specialist.ino.",
            "Sensors: MQ-2 Toxic Gas Sensor (GPIO 34 ADC), DHT22 Temp/Humidity (GPIO 4), HC-SR04, MPU6050.",
            "Actuation: TB6612FNG Dual H-Bridge driving 2x N20 Gearmotors.",
            "Mission Role: Atmospheric hazard triage, explosive gas profiling.",
            "Swarm Interlock: If gas > 350ppm, SwarmCoordinator triggers fleet-wide emergency halt across both rovers."
        ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 9: Multi-Layer Safety Architecture
    # -------------------------------------------------------------
    s9 = prs.slides.add_slide(blank_layout)
    apply_background(s9)
    add_header(s9, "Multi-Layer Safety Architecture & Watchdogs")

    safety_layers = [
        ("Layer 1: Deterministic Router E-Stop", "Bypasses all reasoning layers. Matches 'stop', 'halt', 'freeze' in <5ms to issue motor halt.", ACCENT_CYAN),
        ("Layer 2: 15.0s Telemetry TTL Watchdog", "Enforced in core/safety_validator.py:6. Rejects new movement if sensor telemetry is >15s stale.", ACCENT_CYAN),
        ("Layer 3: Gas Hazard Safety Barrier", "Enforced in core/safety_validator.py:125. Blocks forward motion & ventilation shutoff if gas > 300ppm.", ACCENT_AMBER),
        ("Layer 4: Node Heartbeat Monitor", "Enforced in bupi_node_server.py:184. Checks nodes every 5s; marks nodes OFFLINE after 15s silence.", ACCENT_AMBER),
        ("Layer 5: Microcontroller Motor Auto-Stop", "Enforced in firmware/bupi_bot1_scout.ino:676. Every command requires duration_ms; halts locally.", ACCENT_GREEN)
    ]

    top_y = 1.6
    for title, desc, acc in safety_layers:
        card = s9.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(top_y), Inches(11.7), Inches(0.9))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = acc
        card.line.width = Pt(1)

        tb = s9.shapes.add_textbox(Inches(1.0), Inches(top_y + 0.1), Inches(11.3), Inches(0.7))
        tf = tb.text_frame
        tf.word_wrap = True
        p1 = tf.paragraphs[0]
        p1.text = title
        p1.font.size = Pt(12)
        p1.font.bold = True
        p1.font.color.rgb = acc
        p2 = tf.add_paragraph()
        p2.text = desc
        p2.font.size = Pt(10.5)
        p2.font.color.rgb = TEXT_MAIN
        top_y += 1.02

    # -------------------------------------------------------------
    # SLIDE 10: Odometry & Sensor Fusion Reality
    # -------------------------------------------------------------
    s10 = prs.slides.add_slide(blank_layout)
    apply_background(s10)
    add_header(s10, "Epistemic Kinematics Fusion & Odometry Reality")

    add_card(s10, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Kinematics Odometry Mechanics", [
        "Engine: core/kinematics_odometry.py:140.",
        "IMU Gait Step Counter: Monitors total acceleration magnitude (sqrt(ax^2 + ay^2 + az^2)).",
        "- Step threshold: >= 1.20g with 180ms debounce.",
        "- Stride length: 0.075 m (7.5 cm) per registered step.",
        "Gyro Yaw Dead-Reckoning: Integrates MPU6050 Z-gyro angular velocity over dt.",
        "- Position update: x += stride * cos(theta), y += stride * sin(theta).",
        "Wi-Fi RSSI Distance: d = 10^((-42 - RSSI) / 25) with EWMA filter."
    ], ACCENT_CYAN)

    add_card(s10, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Ground-Truth Reality vs Past Claims", [
        "Audit Finding: 'Extended Kalman Filter (EKF)' is NOT present in repository.",
        "What Actually Runs: A clean epistemic kinematics fusion engine designed specifically for small vibration-prone rovers.",
        "Why This Design Works:",
        "- Eliminates wheel slip integration drift from encoder-less N20 DC motors.",
        "- IMU step detection verifies actual physical chassis motion.",
        "- Wi-Fi RSSI log-distance path loss bounds cumulative unbounded drift."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 11: Dynamic C++ Hardware Ingestion
    # -------------------------------------------------------------
    s11 = prs.slides.add_slide(blank_layout)
    apply_background(s11)
    add_header(s11, "Dynamic C++ Hardware Ingestion & Auto-Flasher")

    add_card(s11, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Self-Learning Hardware Pipeline", [
        "1. Snippet Input: User pastes raw Arduino C++ into Central Hub.",
        "2. FTS5 RAG Search: services/knowledge_super_agent.py queries SQLite FTS5 index for library pinout rules (<1ms).",
        "3. Sketch Synthesis: brain/ai_brain.py:393 injects Wi-Fi/MQTT handlers and command packet parsers.",
        "4. Memory Persistence: Appends command format to hardware_memory.txt.",
        "5. Auto-Flasher: actions/flasher.py compiles with arduino-cli and flashes to detected ESP32 COM port.",
        "6. Instant Control: LLMs read hardware_memory.txt and invoke universal_mqtt_tool without changing core code!"
    ], ACCENT_CYAN)

    add_card(s11, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Extensibility Proof & Limits", [
        "Verified Extensible Peripherals (Zero Python Changes):",
        "• Actuators: Servos, relays, displays, buzzers, LEDs.",
        "• Command Protocol: universal_mqtt_tool(topic, payload).",
        "Where Changes Are Needed:",
        "• Semantic Sensor Translation: Converting new analog raw values into natural language labels ('HAZARDOUS') requires an entry in core/sensor_translator.py.",
        "• Video Streams: Requires an <img> tag in notepad.html."
    ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 12: Communication Fabric & Network Topology
    # -------------------------------------------------------------
    s12 = prs.slides.add_slide(blank_layout)
    apply_background(s12)
    add_header(s12, "Communication Fabric & Network Topology")

    add_card(s12, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "Network Infrastructure (Hotspot 192.168.137.1)", [
        "Subnet: 192.168.137.0/24 (Windows Mobile Hotspot).",
        "Mosquitto MQTT: 127.0.0.1:1883 (TCP Broker).",
        "- Internal utterance, TTS feedback, and actuator broadcasts.",
        "WebSocket Server: 0.0.0.0:8767 (Unified Bridge).",
        "- Bi-directional JSON frame streaming at 20Hz.",
        "- Port 8765 does NOT exist (historical typo corrected).",
        "USB Serial Supervisor: COM3 at 115200 baud.",
        "- Auto-reconnect thread provides zero-loss wired backup."
    ], ACCENT_CYAN)

    add_card(s12, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Telemetry & Database Streaming", [
        "Rate: 20Hz streaming from microcontrollers to host.",
        "Batch DB Writer: bupi_node_server.py:1070 flushes sensor queues to SQLite bupi_telemetry.db every 1.5 seconds.",
        "Telemetry TTL: 15.0-second freshness window.",
        "Hotspot Watchdog: bupi_node_server.py:1074 checks Windows mobile hotspot state every 30 seconds.",
        "Network Isolation: Hotspot subnet insulates robot fleet from external internet latency spikes."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 13: Bit-World Engine (BWE) Digital Twin
    # -------------------------------------------------------------
    s13 = prs.slides.add_slide(blank_layout)
    apply_background(s13)
    add_header(s13, "Bit-World Engine (BWE) Digital Twin & HIL Simulator")

    add_card(s13, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.2), "BWE Simulation Capabilities", [
        "Engine: JavaScript kinematic physics engine in bwe/core/engine.js.",
        "Virtual Peripherals: GPIO, PWM, 12-bit ADC, I2C, SPI.",
        "Modular Plugins:",
        "- HC-SR04 Ultrasonic raycasting sensor (hcsr04.js).",
        "- MQ-2 Gas diffusion plume model (mq2.js).",
        "- Servo motor and SSD1306 OLED display actuators.",
        "Hardware-in-the-Loop (HIL): bwe/interface/hil_bridge.js connects physical ESP32 running esp32_bwe_mqtt_client.ino to virtual environment over USB Serial."
    ], ACCENT_CYAN)

    add_card(s13, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.2), "Digital Twin Parity with Physical Fleet", [
        "Identical Schemas: Virtual sensor packets emulate ESP32 JSON telemetry format identically.",
        "Identical Mission Logic: AutonomousGoalAgent executes missions against simulated robots without any code changes.",
        "Interactive State Injection: Drag-and-drop simulated survivors and obstacles on spatial_twin_2d.html.",
        "Pre-Deployment Validation: Test multi-stage missions and obstacle bypasses safely in software before field deployment."
    ], ACCENT_GREEN)

    # -------------------------------------------------------------
    # SLIDE 14: Future Roadmap: Raspberry Pi & Fleet
    # -------------------------------------------------------------
    s14 = prs.slides.add_slide(blank_layout)
    apply_background(s14)
    add_header(s14, "Scalability Roadmap: Raspberry Pi Edge & Heterogeneous Fleet")

    add_card(s14, Inches(0.8), Inches(1.6), Inches(3.6), Inches(5.2), "Phase 1: Current Reality", [
        "Dual ESP32 Differential Rovers (Scout & Specialist).",
        "Host PC 3-Tier Intelligence Engine.",
        "Local Mosquitto & WebSocket Bridge.",
        "BWE Digital Twin Simulator.",
        "Epistemic Kinematics Odometry.",
        "Dynamic C++ Hardware Ingestion."
    ], ACCENT_CYAN)

    add_card(s14, Inches(4.8), Inches(1.6), Inches(3.6), Inches(5.2), "Phase 2: RPi Edge Compute", [
        "Introduce intermediate Raspberry Pi 5 Linux node on rover chassis.",
        "Run lightweight MQTT forwarder.",
        "Run local YOLOv8-nano / OpenCV for real-time survivor visual recognition.",
        "Edge Whisper audio pre-processing.",
        "Zero Host Core Changes: Communication remains standard MQTT/WS."
    ], ACCENT_GREEN)

    add_card(s14, Inches(8.8), Inches(1.6), Inches(5.2), Inches(5.2), "Phase 3: Heterogeneous Fleet", [
        "Tracked Rubble Crawlers: Reuses differential motor schema with higher torque PWM.",
        "Aerial Quadcopters (UAVs): Extend kinematics engine to 3D (x, y, z); MAVLink flight controller bridge.",
        "4-DOF Robotic Manipulators: Cartesian inverse kinematics pick-and-place tools.",
        "Static Subterranean Beacons: Fixed gas and climate monitoring relays."
    ], ACCENT_AMBER)

    # -------------------------------------------------------------
    # SLIDE 15: Ground-Truth Truth Table & Conclusion
    # -------------------------------------------------------------
    s15 = prs.slides.add_slide(blank_layout)
    apply_background(s15)
    add_header(s15, "Ground-Truth Verification Truth Table & Conclusion")

    table_data = [
        ("Subsystem", "Verified Status", "Production Code Reality"),
        ("3-Tier Decision Pipeline", "VERIFIED IN CODE", "<5ms Regex -> ~500ms Ollama -> 5-15s CrewAI"),
        ("Autonomous Goal Agent", "VERIFIED IN CODE", "20Hz closed-loop loop, 11 policies, 5-stage detour"),
        ("Heterogeneous Swarm", "VERIFIED IN CODE", "Bot 1 Scout (PIR) & Bot 2 Specialist (Gas/Climate)"),
        ("Safety & TTL Watchdogs", "VERIFIED IN CODE", "15.0s TTL watchdog, Gas safety, Motor auto-stop"),
        ("Dynamic C++ Ingestion", "VERIFIED IN CODE", "Self-learning C++ parsing, FTS5 RAG & auto-flasher"),
        ("Desktop UI & Mascot", "VERIFIED IN CODE", "100% Electron Chromium (Mascot & 11-Tab Hub)"),
        ("BWE Digital Twin & HIL", "VERIFIED IN CODE", "JavaScript simulation engine & physical HIL bridge"),
        ("Odometry Engine", "VERIFIED IN CODE", "1.20g IMU gait step counter & Wi-Fi RSSI path loss")
    ]

    # Create Summary Table
    rows = len(table_data)
    cols = 3
    table_shape = s15.shapes.add_table(rows, cols, Inches(0.8), Inches(1.6), Inches(11.7), Inches(4.5))
    table = table_shape.table
    table.columns[0].width = Inches(3.2)
    table.columns[1].width = Inches(2.6)
    table.columns[2].width = Inches(5.9)

    for r_idx, row in enumerate(table_data):
        for c_idx, val in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG if r_idx > 0 else RGBColor(14, 165, 233)
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(10 if r_idx > 0 else 11)
            p.font.bold = (r_idx == 0 or c_idx == 1)
            if r_idx == 0:
                p.font.color.rgb = RGBColor(255, 255, 255)
            elif c_idx == 1:
                p.font.color.rgb = ACCENT_GREEN
            else:
                p.font.color.rgb = TEXT_MAIN

    # Footer conclusion text
    foot_box = s15.shapes.add_textbox(Inches(0.8), Inches(6.3), Inches(11.7), Inches(0.8))
    tf_f = foot_box.text_frame
    p_f = tf_f.paragraphs[0]
    p_f.text = "BUPI delivers a battle-tested, local-first, fail-safe robotics architecture that bridges the gap between natural language human interaction and reliable physical edge autonomy for Problem Statement 26201."
    p_f.font.size = Pt(12)
    p_f.font.bold = True
    p_f.font.color.rgb = ACCENT_CYAN

    # Save presentation
    output_pptx = os.path.join(os.path.dirname(__file__), "BUPI_26201_Architecture_Presentation.pptx")
    prs.save(output_pptx)
    print(f"Successfully generated PowerPoint presentation: {output_pptx}")

if __name__ == "__main__":
    create_presentation()
