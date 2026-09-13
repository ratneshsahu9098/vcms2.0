import json
import requests
from datetime import date, timedelta


def get_ollama_url():
    from config import Config
    return Config.OLLAMA_BASE_URL


def get_model():
    from config import Config
    return Config.OLLAMA_MODEL


def check_ollama_running():
    try:
        r = requests.get(f"{get_ollama_url()}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def chat_completion(messages, model=None):
    model = model or get_model()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    r = requests.post(f"{get_ollama_url()}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["message"]["content"]


def chat_completion_stream(messages, model=None):
    model = model or get_model()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    r = requests.post(f"{get_ollama_url()}/api/chat", json=payload, stream=True, timeout=120)
    r.raise_for_status()
    for line in r.iter_lines():
        if line:
            data = json.loads(line)
            if "message" in data and "content" in data["message"]:
                yield data["message"]["content"]


# ---------------------------------------------------------------------------
# Fleet context builder
# ---------------------------------------------------------------------------

def build_fleet_context(vehicles, today=None):
    today = today or date.today()
    total = len(vehicles)
    expired, expiring_7, expiring_30, valid = 0, 0, 0, 0
    doc_stats = {"PUC": 0, "Fitness": 0, "Permit": 0, "Tax": 0, "Insurance": 0}
    owner_map = {}
    type_map = {}

    for v in vehicles:
        statuses = v.document_statuses()
        worst = v.overall_status()
        if worst == "status-red":
            expired += 1
        elif worst == "status-orange":
            expiring_7 += 1
        elif worst == "status-yellow":
            expiring_30 += 1
        else:
            valid += 1

        for label, info in statuses.items():
            if info["class"] in ("status-red", "status-orange", "status-yellow"):
                doc_stats[label] = doc_stats.get(label, 0) + 1

        owner_map.setdefault(v.owner_name, []).append(v.vehicle_number)
        type_map.setdefault(v.vehicle_type or "Unspecified", []).append(v.vehicle_number)

    expiring_details = []
    for v in vehicles:
        statuses = v.document_statuses()
        for label, info in statuses.items():
            expiry = info["expiry"]
            if expiry and expiry <= today + timedelta(days=30):
                days_left = (expiry - today).days
                status = "expired" if days_left < 0 else f"expires in {days_left}d"
                expiring_details.append({
                    "vehicle": v.vehicle_number,
                    "owner": v.owner_name,
                    "document": label,
                    "expiry": expiry.isoformat(),
                    "status": status,
                })
    expiring_details.sort(key=lambda x: x["expiry"])

    return {
        "total": total,
        "expired": expired,
        "expiring_within_7_days": expiring_7,
        "expiring_within_30_days": expiring_30,
        "valid": valid,
        "documents_with_issues": doc_stats,
        "owners": {k: len(v) for k, v in owner_map.items()},
        "vehicle_types": {k: len(v) for k, v in type_map.items()},
        "expiring_details": expiring_details[:30],
    }


# ---------------------------------------------------------------------------
# Chat assistant
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are VCMS AI Assistant for a Vehicle Compliance Management System.
You help fleet managers with questions about their vehicles, document expiries, compliance status, and recommendations.

You have access to the current fleet data below. Answer questions accurately based on this data.
Be concise and direct. Use tables or bullet points when helpful.
If asked about something not in the data, say so clearly.

Current Fleet Data:
{fleet_context}
"""


def ask_assistant(user_question, vehicles):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    system_msg = SYSTEM_PROMPT.format(fleet_context=context_str)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_question},
    ]
    return chat_completion(messages)


def ask_assistant_stream(user_question, vehicles):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    system_msg = SYSTEM_PROMPT.format(fleet_context=context_str)
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_question},
    ]
    return chat_completion_stream(messages)


# ---------------------------------------------------------------------------
# Document parser
# ---------------------------------------------------------------------------

PARSE_PROMPT = """Extract vehicle information from the following OCR text of an Indian vehicle document (RC, Insurance, PUC, or Fitness certificate).

Return a JSON object with these fields (use null for missing fields):
{{
    "vehicle_number": "string",
    "chassis_number": "string",
    "engine_number": "string",
    "owner_name": "string",
    "registration_date": "YYYY-MM-DD or null",
    "puc_expiry": "YYYY-MM-DD or null",
    "fitness_expiry": "YYYY-MM-DD or null",
    "permit_expiry": "YYYY-MM-DD or null",
    "insurance_expiry": "YYYY-MM-DD or null",
    "insurance_company": "string or null",
    "policy_number": "string or null",
    "vehicle_type": "string or null",
    "document_type": "RC/Insurance/PUC/Fitness/Unknown"
}}

Rules:
- Return ONLY the JSON object, no explanation
- Use DD-MM-YYYY or DD/MM/YYYY format dates and convert to YYYY-MM-DD
- Uppercase vehicle and chassis numbers
- If a field is not found, set it to null

OCR Text:
{ocr_text}
"""


def parse_document_text(ocr_text):
    messages = [
        {"role": "system", "content": "You are a document parser. Return only valid JSON."},
        {"role": "user", "content": PARSE_PROMPT.format(ocr_text=ocr_text)},
    ]
    response = chat_completion(messages)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
    return json.loads(response)


# ---------------------------------------------------------------------------
# AI Insights
# ---------------------------------------------------------------------------

INSIGHTS_PROMPT = """Analyze the following vehicle fleet compliance data and provide actionable insights.

Fleet Summary:
{fleet_context}

Provide your analysis in this exact JSON format:
{{
    "risk_summary": "1-2 sentence overall risk assessment",
    "top_issues": ["issue1", "issue2", "issue3"],
    "recommendations": ["recommendation1", "recommendation2", "recommendation3"],
    "vehicle_risks": [
        {{"vehicle": "number", "owner": "name", "risk_level": "high/medium/low", "reason": "why"}}
    ],
    "monthly_outlook": "what to expect in the coming month"
}}

Rules:
- Focus on the most critical compliance gaps
- Prioritize expired documents first, then expiring soon
- Vehicle risks should cover the top 10 most at-risk vehicles
- Be specific with dates and document names
- Return ONLY the JSON object
"""


def generate_insights(vehicles):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    messages = [
        {"role": "system", "content": "You are a fleet compliance analyst. Return only valid JSON."},
        {"role": "user", "content": INSIGHTS_PROMPT.format(fleet_context=context_str)},
    ]
    response = chat_completion(messages)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
    return json.loads(response)
