import os
import re
import json
import requests
import base64
try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
from google import genai
from google.genai import types

class DummyEmbeddingFunction:
    def __call__(self, input: list[str]) -> list[list[float]]:
        return [[0.0] for _ in input]
        
    def name(self) -> str:
        return "DummyEmbeddingFunction"

class KnowledgeSuperAgent:
    def __init__(self):
        # Load all Groq API keys for synthesis key rotation
        self.groq_keys = []
        for k, v in os.environ.items():
            if k.startswith("GROQ_API_KEY") and v.strip():
                self.groq_keys.append(v.strip())
        self.current_groq_key_idx = 0

        # Load all Google API keys for synthesis key rotation
        self.google_keys = []
        for k, v in os.environ.items():
            if k.startswith("GOOGLE_AI_STUDIO_KEY") and v.strip():
                self.google_keys.append(v.strip())
        self.current_google_key_idx = 0
        
        # Load optional API tokens
        self.github_token = os.environ.get("GITHUB_TOKEN", "").strip()
        self.nexar_token = os.environ.get("NEXAR_TOKEN", "").strip()
        
        # Local paths
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.arduino_index_path = os.path.join(self.project_root, "brain", "arduino_library_index.json")
        self.json_cache_path = os.path.join(self.project_root, "brain", "sensor_knowledge_cache.json")
        self.db_path = os.path.join(self.project_root, "brain", "chroma_db")
        
        # Initialize database cache (ChromaDB with JSON fallback)
        self.use_chromadb = False
        try:
            if not HAS_CHROMADB:
                raise ImportError("chromadb module is not installed.")
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self.chroma_client = chromadb.PersistentClient(path=self.db_path)
            try:
                self.collection = self.chroma_client.get_or_create_collection(
                    "bupi_sensor_knowledge",
                    embedding_function=DummyEmbeddingFunction()
                )
            except Exception as conflict_err:
                if "Embedding function conflict" in str(conflict_err):
                    print("[Super Agent] Re-creating ChromaDB collection due to embedding function conflict...", flush=True)
                    try:
                        self.chroma_client.delete_collection("bupi_sensor_knowledge")
                    except Exception:
                        pass
                    self.collection = self.chroma_client.get_or_create_collection(
                        "bupi_sensor_knowledge",
                        embedding_function=DummyEmbeddingFunction()
                    )
                else:
                    raise conflict_err
            self.use_chromadb = True
            print("[Super Agent] ChromaDB initialized successfully with dummy embedding function.", flush=True)
        except Exception as e:
            print(f"[Super Agent Warning] Could not initialize ChromaDB ({e}). Falling back to JSON cache.", flush=True)
            self._init_json_cache()

    def _init_json_cache(self):
        os.makedirs(os.path.dirname(self.json_cache_path), exist_ok=True)
        if not os.path.exists(self.json_cache_path):
            with open(self.json_cache_path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _read_json_cache(self) -> dict:
        self._init_json_cache()
        try:
            with open(self.json_cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_json_cache(self, data: dict):
        self._init_json_cache()
        try:
            with open(self.json_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Super Agent Error] Could not write JSON cache: {e}", flush=True)

    # -------------------------------------------------------------
    # 1. Sketch Parser
    # -------------------------------------------------------------
    def extract_sensors_and_libraries(self, code: str) -> list:
        """
        Parses sketch source code and extracts potential sensor terms, library includes, and modules.
        """
        detected = set()
        
        # Match #include <Header.h> or #include "Header.h"
        includes = re.findall(r'#include\s*[<"]\s*([\w\-]+)\.h\s*[>"]', code, re.I)
        for inc in includes:
            # Exclude standard ESP32/WiFi/Arduino libraries
            if inc.lower() not in ["wifi", "webserver", "wire", "spi", "arduino", "client", "pubsubclient", "paho", "mqtt", "fs", "sd", "eeprom"]:
                detected.add(inc)

        # Look for typical sensor patterns (e.g. DHT11, DHT22, MQ135, MQ2, HC-SR04, BMP280, MPU6050, NeoPixel)
        sensor_patterns = [
            r'\b(dht\d+)',
            r'\b(mq[-_]?\d+)',
            r'\b(hc[-_]?sr\d+)',
            r'\b(bmp\d+)',
            r'\b(bme\d+)',
            r'\b(mpu\d+)',
            r'\b(neopixel)',
            r'\b(sgp\d+)',
            r'\b(vl53l\dx)',
            r'\b(max\d+)'
        ]
        
        for pat in sensor_patterns:
            matches = re.findall(pat, code, re.I)
            for m in matches:
                # Clean name (e.g. MQ-135 -> MQ135)
                clean_name = re.sub(r'[-_]', '', m).upper()
                detected.add(clean_name)
                
        return list(detected)

    # -------------------------------------------------------------
    # 2. Remote API Client Integrations
    # -------------------------------------------------------------
    def _search_arduino_registry(self, query: str) -> list:
        """
        Downloads/Loads the official Arduino Library Index and searches for matching libraries.
        """
        try:
            # Download if not present
            if not os.path.exists(self.arduino_index_path):
                os.makedirs(os.path.dirname(self.arduino_index_path), exist_ok=True)
                print("[Super Agent] Downloading Arduino Library Index...", flush=True)
                r = requests.get("https://downloads.arduino.cc/libraries/library_index.json", timeout=15)
                if r.status_code == 200:
                    with open(self.arduino_index_path, "w", encoding="utf-8") as f:
                        f.write(r.text)
                else:
                    return []
            
            with open(self.arduino_index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            libraries = data.get("libraries", [])
            matches = []
            for lib in libraries:
                lib_name = lib.get("name", "")
                lib_sentence = lib.get("sentence", "")
                if query.lower() in lib_name.lower() or query.lower() in lib_sentence.lower():
                    matches.append({
                        "name": lib.get("name"),
                        "version": lib.get("version"),
                        "author": lib.get("author"),
                        "sentence": lib_sentence,
                        "paragraph": lib.get("paragraph"),
                        "url": lib.get("website"),
                        "includes": lib.get("includes", [])
                    })
                    if len(matches) >= 3:
                        break
            return matches
        except Exception as e:
            print(f"[Super Agent Error] Arduino Registry query failed: {e}", flush=True)
            return []

    def _search_platformio_registry(self, query: str) -> list:
        """
        Queries PlatformIO Registry API for library metadata and header/include patterns.
        """
        try:
            r = requests.get(
                "https://api.registry.platformio.org/v3/search",
                params={"query": query, "limit": 3},
                timeout=8
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                results = []
                for it in items:
                    results.append({
                        "name": it.get("name"),
                        "description": it.get("description"),
                        "examples": [ex.get("name") for ex in it.get("examples", [])[:2]],
                        "headers": it.get("headers", []),
                        "platforms": [p.get("name") for p in it.get("platforms", [])],
                        "frameworks": it.get("frameworks", [])
                    })
                return results
        except Exception as e:
            print(f"[Super Agent Error] PlatformIO Registry query failed: {e}", flush=True)
        return []

    def _search_github_examples(self, query: str) -> str:
        """
        Searches GitHub for ESP32/Arduino examples of the sensor and returns README content.
        """
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
            
        try:
            # Search repositories
            search_url = "https://api.github.com/search/repositories"
            params = {"q": f"ESP32 {query} arduino", "sort": "stars"}
            r = requests.get(search_url, params=params, headers=headers, timeout=8)
            if r.status_code != 200:
                return ""
                
            items = r.json().get("items", [])
            if not items:
                return ""
                
            top_repo = items[0]["full_name"]
            
            # Fetch README content
            readme_url = f"https://api.github.com/repos/{top_repo}/readme"
            r_readme = requests.get(readme_url, headers=headers, timeout=8)
            if r_readme.status_code == 200:
                content_b64 = r_readme.json().get("content", "")
                if content_b64:
                    return base64.b64decode(content_b64).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[Super Agent Error] GitHub Example search failed: {e}", flush=True)
        return ""

    def _get_wikipedia_summary(self, query: str) -> str:
        """
        Queries Wikipedia Page Summary API to gather a conceptual definition of what the component is.
        """
        try:
            r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}", timeout=8)
            if r.status_code == 200:
                return r.json().get("extract", "")
        except Exception:
            pass
        return ""

    def _get_nexar_specs(self, query: str) -> dict:
        """
        Queries Nexar GraphQL API (Octopart catalog) to retrieve part descriptions and specs.
        """
        if not self.nexar_token:
            return {}
            
        gql_query = """
        query SearchMPN($q: String!) {
          supSearchMpn(q: $q, limit: 1) {
            results {
              part {
                name
                shortDescription
                specs {
                  attribute { name }
                  displayValue
                }
              }
            }
          }
        }
        """
        try:
            r = requests.post(
                "https://api.nexar.com/graphql",
                json={"query": gql_query, "variables": {"q": query}},
                headers={"Authorization": f"Bearer {self.nexar_token}"},
                timeout=8
            )
            if r.status_code == 200:
                results = r.json().get("data", {}).get("supSearchMpn", {}).get("results", [])
                if results:
                    part = results[0].get("part", {})
                    return {
                        "name": part.get("name"),
                        "description": part.get("shortDescription"),
                        "specs": {s.get("attribute", {}).get("name"): s.get("displayValue") for s in part.get("specs", [])}
                    }
        except Exception as e:
            print(f"[Super Agent Error] Nexar API query failed: {e}", flush=True)
        return {}

    # -------------------------------------------------------------
    # 3. Knowledge Synthesis & Local Caching
    # -------------------------------------------------------------
    def get_knowledge(self, sensor_name: str) -> dict:
        """
        Main query pipeline: Checks cache first (ChromaDB or JSON), researches online if missing,
        synthesizes via Gemini, caches, and returns the structured card.
        """
        sensor_name = sensor_name.upper().strip()
        
        # 1. Query Cache
        cached_card = self._query_cache(sensor_name)
        if cached_card:
            print(f"[Super Agent] Cache hit for '{sensor_name}'!", flush=True)
            return cached_card
            
        print(f"[Super Agent] Cache miss for '{sensor_name}'. Starting research...", flush=True)
        
        # 2. Run Technical Research
        arduino_info = self._search_arduino_registry(sensor_name)
        pio_info = self._search_platformio_registry(sensor_name)
        wiki_info = self._get_wikipedia_summary(sensor_name)
        github_readme = self._search_github_examples(sensor_name)
        nexar_specs = self._get_nexar_specs(sensor_name)
        
        # 3. Build synthesis prompt
        prompt = f"""You are a Hardware Research Agent. Based on the gathered information about the sensor/component '{sensor_name}':

Arduino Library Registry Match:
{json.dumps(arduino_info, indent=2)}

PlatformIO Registry Match:
{json.dumps(pio_info, indent=2)}

Wikipedia Description:
{wiki_info}

Octopart/Nexar Component Specs:
{json.dumps(nexar_specs, indent=2)}

GitHub README excerpt:
{github_readme[:2500] if github_readme else "No examples found"}

Synthesize these technical details into a standardized hardware knowledge card.
Include:
- sensor_name: The clean identifier of the sensor.
- description: What it measures, what it is, and what it does.
- required_libraries: List of required `#include` statements.
- standard_wiring: Dict outlining typical ESP32 wiring (VCC, GND, Signal/Data/I2C/SPI pins).
- arduino_initialization: Simple code snippet showing object instantiation and begin statements.
- arduino_read_pattern: Simple code snippet demonstrating reading raw values.
- mqtt_publish_format: Simple JSON structure/example showing recommended payload layout for telemetry.
- common_mistakes: List of common issues (e.g. wrong voltage, pull-up resistors required, blocking delays).

Return ONLY a valid JSON object matching these keys. Do not include markdown codeblocks or extra text.
"""

        # 4. Synthesize with Gemini first, fallback to Groq using key rotation
        synthesized_text = ""

        # 4a. Try Gemini keys first
        if self.google_keys:
            max_attempts = len(self.google_keys) * 2
            for attempt in range(max_attempts):
                key = self.google_keys[self.current_google_key_idx]
                try:
                    print(f"[Super Agent] Trying Gemini key {self.current_google_key_idx + 1} with gemini-2.5-flash...", flush=True)
                    client = genai.Client(api_key=key)
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    synthesized_text = resp.text.strip()
                    print(f"[Super Agent] Gemini synthesis succeeded!", flush=True)
                    break
                except Exception as e:
                    print(f"[Super Agent Error] Gemini key {self.current_google_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                    self.current_google_key_idx = (self.current_google_key_idx + 1) % len(self.google_keys)

        # 4b. Fallback to Groq keys
        if not synthesized_text and self.groq_keys:
            from openai import OpenAI
            max_attempts = len(self.groq_keys) * 2
            for attempt in range(max_attempts):
                key = self.groq_keys[self.current_groq_key_idx]
                try:
                    print(f"[Super Agent] Falling back to Groq key {self.current_groq_key_idx + 1}...", flush=True)
                    client = OpenAI(
                        base_url="https://api.groq.com/openai/v1",
                        api_key=key
                    )
                    resp = client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        response_format={"type": "json_object"}
                    )
                    synthesized_text = resp.choices[0].message.content.strip()
                    break
                except Exception as e:
                    print(f"[Super Agent Warning] Groq key {self.current_groq_key_idx + 1} failed ({e}). Rotating key...", flush=True)
                    self.current_groq_key_idx = (self.current_groq_key_idx + 1) % len(self.groq_keys)

        # Fallback raw parse if synthesis completely fails
        if not synthesized_text:
            print("[Super Agent Error] Gemini synthesis completely failed. Building generic fallback card.", flush=True)
            fallback_card = {
                "sensor_name": sensor_name,
                "description": f"Research failed. Generic placeholder card for {sensor_name}.",
                "required_libraries": [f"#include <{sensor_name}.h>"],
                "standard_wiring": {"VCC": "3.3V / 5V", "GND": "GND", "Signal": "GPIO / ADC"},
                "arduino_initialization": f"// Instantiate {sensor_name}\nvoid setup() {{}}",
                "arduino_read_pattern": "// Read values from sensor",
                "mqtt_publish_format": {"sensor": sensor_name, "value": 0.0},
                "common_mistakes": ["Verify voltage requirements", "Check wiring configuration"]
            }
            self._save_to_cache(sensor_name, fallback_card)
            return fallback_card
            
        # Clean potential markdown fences from the response
        if synthesized_text.startswith("```json"):
            synthesized_text = synthesized_text[7:]
        elif synthesized_text.startswith("```"):
            synthesized_text = synthesized_text[3:]
        if synthesized_text.endswith("```"):
            synthesized_text = synthesized_text[:-3]
        synthesized_text = synthesized_text.strip()
        
        try:
            card_json = json.loads(synthesized_text)
            self._save_to_cache(sensor_name, card_json)
            return card_json
        except Exception as e:
            print(f"[Super Agent Error] Failed to parse synthesized card JSON ({e}): {synthesized_text[:300]}", flush=True)
            # Safe recovery card
            recovery_card = {
                "sensor_name": sensor_name,
                "description": f"Failed to parse synthesis. Technical card for {sensor_name}.",
                "required_libraries": [f"#include <{sensor_name}.h>"],
                "standard_wiring": {"VCC": "3.3V", "GND": "GND", "Signal": "GPIO"},
                "arduino_initialization": "",
                "arduino_read_pattern": "",
                "mqtt_publish_format": {"raw": 0},
                "common_mistakes": ["Verify manual datasheet parameters"]
            }
            self._save_to_cache(sensor_name, recovery_card)
            return recovery_card

    # -------------------------------------------------------------
    # 4. Cache Operations
    # -------------------------------------------------------------
    def _query_cache(self, sensor_name: str) -> dict:
        if self.use_chromadb:
            try:
                results = self.collection.get(ids=[sensor_name])
                if results and results.get("documents"):
                    return json.loads(results["documents"][0])
            except Exception as e:
                print(f"[Super Agent Error] ChromaDB query failed ({e}). Falling back to JSON.", flush=True)
                
        # Fallback JSON Cache check
        json_cache = self._read_json_cache()
        return json_cache.get(sensor_name)

    def _save_to_cache(self, sensor_name: str, card: dict):
        card_str = json.dumps(card)
        
        # Save to ChromaDB
        if self.use_chromadb:
            try:
                # Delete existing ID to prevent duplicates/errors
                try:
                    self.collection.delete(ids=[sensor_name])
                except Exception:
                    pass
                self.collection.add(
                    documents=[card_str],
                    ids=[sensor_name],
                    metadatas=[{"sensor": sensor_name}]
                )
                print(f"[Super Agent] Saved '{sensor_name}' knowledge card to ChromaDB.", flush=True)
            except Exception as e:
                print(f"[Super Agent Error] ChromaDB save failed ({e}). Saving to JSON.", flush=True)

        # Always save to JSON cache as backup
        json_cache = self._read_json_cache()
        json_cache[sensor_name] = card
        self._write_json_cache(json_cache)
        print(f"[Super Agent] Saved '{sensor_name}' knowledge card to JSON cache.", flush=True)

    def search_online_components(self, query: str) -> list:
        """
        Searches Arduino, PlatformIO, and Nexar registries for components matching the query.
        Returns a list of unified component dicts.
        """
        results = []
        seen_ids = set()
        
        # 1. Search Nexar (Octopart) if token exists
        if self.nexar_token:
            gql_query = """
            query SearchMPN($q: String!) {
              supSearchMpn(q: $q, limit: 5) {
                results {
                  part {
                    name
                    shortDescription
                    specs {
                      attribute { name }
                      displayValue
                    }
                  }
                }
              }
            }
            """
            try:
                r = requests.post(
                    "https://api.nexar.com/graphql",
                    json={"query": gql_query, "variables": {"q": query}},
                    headers={"Authorization": f"Bearer {self.nexar_token}"},
                    timeout=5
                )
                if r.status_code == 200:
                    parts_data = r.json().get("data", {}).get("supSearchMpn", {}).get("results", [])
                    for item in parts_data:
                        part = item.get("part", {})
                        part_name = part.get("name", "")
                        if part_name and part_name.lower() not in seen_ids:
                            seen_ids.add(part_name.lower())
                            results.append({
                                "id": part_name,
                                "name": part.get("shortDescription") or f"Component {part_name}",
                                "type": "component",
                                "source": "Nexar (Octopart)",
                                "spec": {
                                    "type": "component",
                                    "protocol": "digital",
                                    "notes": part.get("shortDescription") or ""
                                }
                            })
            except Exception as e:
                print(f"[Super Agent Error] Nexar search failed: {e}", flush=True)

        # 2. Search PlatformIO Registry
        try:
            r = requests.get(
                "https://api.registry.platformio.org/v3/search",
                params={"query": query, "limit": 5},
                timeout=5
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                for it in items:
                    name = it.get("name", "")
                    if name and name.lower() not in seen_ids:
                        seen_ids.add(name.lower())
                        results.append({
                            "id": name,
                            "name": it.get("description") or f"Library {name}",
                            "type": "library",
                            "source": "PlatformIO",
                            "spec": {
                                "type": "sensor" if "sensor" in (it.get("description") or "").lower() else "actuator",
                                "protocol": "library",
                                "library": name,
                                "notes": it.get("description") or ""
                            }
                        })
        except Exception as e:
            print(f"[Super Agent Error] PlatformIO search failed: {e}", flush=True)

        # 3. Search Arduino Registry
        try:
            arduino_matches = self._search_arduino_registry(query)
            for lib in arduino_matches:
                name = lib.get("name", "")
                if name and name.lower() not in seen_ids:
                    seen_ids.add(name.lower())
                    results.append({
                        "id": name,
                        "name": lib.get("sentence") or f"Library {name}",
                        "type": "library",
                        "source": "Arduino",
                        "spec": {
                            "type": "sensor" if "sensor" in (lib.get("sentence") or "").lower() else "actuator",
                            "protocol": "library",
                            "library": name,
                            "notes": lib.get("sentence") or ""
                        }
                    })
        except Exception as e:
            print(f"[Super Agent Error] Arduino Registry search failed: {e}", flush=True)

        return results
