#!/usr/bin/env python3
"""
Synthetic LTR Judgment Generator for Genesys KB Search

Generates query-document relevance judgments by leveraging existing
BM25 and semantic search signals. Documents that rank highly in both
retrievers get higher grades (auto-labeling via rank agreement).

Output: judgments.json — list of {query, doc_id, grade, features}
"""

import json
import urllib.request
import urllib.error
import ssl
import sys

ES_HOST = "https://5b324682048f4a1197d257cf0705072a.us-east-2.aws.elastic-cloud.com:443"
API_KEY = "ZGFzLWw1MEJKaWxyaVN0MGhCT1E6aGpOb1pqVGlqVzlvZE9ONGR3YnE4UQ=="
INDEX = "content-sharepoint-ltr-lab"

SYNTHETIC_QUERIES = [
    # Password & authentication
    "how to reset password",
    "single sign on SSO configuration",
    "multi-factor authentication setup",
    "OAuth integration settings",
    # Agent workspace & routing
    "ACD automatic call distribution routing",
    "agent copilot configuration",
    "queue management and routing rules",
    "wrap up codes and after call work",
    # AI features
    "AI scoring best practices",
    "virtual agent bot setup",
    "AI summarization for calls",
    "agent assist knowledge base",
    "predictive engagement configuration",
    # Telephony & voice
    "WebRTC phone configuration",
    "SIP trunking setup",
    "IVR call flow design",
    "outbound dialing campaign",
    "BYOC bring your own carrier",
    # Digital channels
    "web messaging widget setup",
    "email routing configuration",
    "SMS messaging 10DLC",
    "Apple Messages for Business",
    # Workforce management
    "workforce management scheduling",
    "shift trading and time off",
    "forecasting contact volume",
    "real time adherence monitoring",
    # Analytics & reporting
    "conversation analytics dashboard",
    "quality management evaluation",
    "speech and text analytics",
    "API usage reporting",
    # Platform & admin
    "AWS regions for Genesys Cloud",
    "firewall requirements and CIDR",
    "data actions integration",
    "Salesforce integration setup",
    "billing and invoice details",
    # Troubleshooting intents
    "call quality issues troubleshooting",
    "agent cannot receive calls",
    "recording not working",
    "screen recording setup",
    # Cross-lingual (tests multilingual embedding)
    "como configurar el enrutamiento de llamadas",
    "comment configurer la messagerie web",
]

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def es_search(body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{ES_HOST}/{INDEX}/_search",
        data=data,
        headers={
            "Authorization": f"ApiKey {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())


def get_bm25_results(query, size=30):
    return es_search({
        "size": size,
        "query": {"match": {"body": query}},
        "_source": ["title", "name", "size", "lastModifiedDateTime", "file.mimeType"],
        "explain": False,
    })


def get_semantic_results(query, size=30):
    return es_search({
        "size": size,
        "query": {"semantic": {"field": "semantic_body", "query": query}},
        "_source": ["title", "name", "size", "lastModifiedDateTime", "file.mimeType"],
        "explain": False,
    })


def compute_grade(bm25_rank, semantic_rank, max_rank=30):
    """Grade based on rank agreement between BM25 and semantic."""
    bm25_present = bm25_rank is not None and bm25_rank < max_rank
    sem_present = semantic_rank is not None and semantic_rank < max_rank

    if bm25_present and sem_present:
        avg_rank = (bm25_rank + semantic_rank) / 2
        if avg_rank < 3:
            return 3  # perfect — top of both
        elif avg_rank < 8:
            return 2  # good — high in both
        else:
            return 1  # fair — present in both but not top
    elif bm25_present or sem_present:
        rank = bm25_rank if bm25_present else semantic_rank
        if rank < 5:
            return 2  # good — top of one retriever
        elif rank < 15:
            return 1  # fair
        else:
            return 0  # marginal
    else:
        return 0  # irrelevant


def generate_judgments():
    all_judgments = []

    for qid, query in enumerate(SYNTHETIC_QUERIES):
        print(f"[{qid+1}/{len(SYNTHETIC_QUERIES)}] {query}")

        try:
            bm25 = get_bm25_results(query)
            semantic = get_semantic_results(query)
        except urllib.error.URLError as e:
            print(f"  ERROR: {e}")
            continue

        bm25_hits = bm25.get("hits", {}).get("hits", [])
        sem_hits = semantic.get("hits", {}).get("hits", [])

        bm25_ranks = {h["_id"]: i for i, h in enumerate(bm25_hits)}
        sem_ranks = {h["_id"]: i for i, h in enumerate(sem_hits)}

        all_doc_ids = set(bm25_ranks.keys()) | set(sem_ranks.keys())

        doc_meta = {}
        for h in bm25_hits + sem_hits:
            if h["_id"] not in doc_meta:
                doc_meta[h["_id"]] = {
                    "bm25_score": 0.0,
                    "semantic_score": 0.0,
                    "title": h["_source"].get("title", ""),
                    "size": h["_source"].get("size", 0),
                    "mime_type": h["_source"].get("file", {}).get("mimeType", ""),
                }

        for h in bm25_hits:
            doc_meta[h["_id"]]["bm25_score"] = h["_score"]
        for h in sem_hits:
            doc_meta[h["_id"]]["semantic_score"] = h["_score"]

        for doc_id in all_doc_ids:
            bm25_rank = bm25_ranks.get(doc_id)
            sem_rank = sem_ranks.get(doc_id)
            grade = compute_grade(bm25_rank, sem_rank)

            meta = doc_meta[doc_id]
            judgment = {
                "qid": qid,
                "query": query,
                "doc_id": doc_id,
                "grade": grade,
                "features": {
                    "bm25_score": meta["bm25_score"],
                    "semantic_score": meta["semantic_score"],
                    "bm25_rank": bm25_rank if bm25_rank is not None else 999,
                    "semantic_rank": sem_rank if sem_rank is not None else 999,
                    "doc_size": meta["size"] if meta["size"] else 0,
                    "title": meta["title"],
                },
            }
            all_judgments.append(judgment)

        grade_dist = {}
        for j in all_judgments:
            if j["qid"] == qid:
                grade_dist[j["grade"]] = grade_dist.get(j["grade"], 0) + 1
        print(f"  docs: {len(all_doc_ids)}, grades: {grade_dist}")

    return all_judgments


if __name__ == "__main__":
    judgments = generate_judgments()

    output_path = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/judgments.json"
    with open(output_path, "w") as f:
        json.dump(judgments, f, indent=2)

    total = len(judgments)
    queries = len(set(j["qid"] for j in judgments))
    grades = {}
    for j in judgments:
        grades[j["grade"]] = grades.get(j["grade"], 0) + 1

    print(f"\nDone: {total} judgments across {queries} queries")
    print(f"Grade distribution: {grades}")
    print(f"Saved to: {output_path}")
