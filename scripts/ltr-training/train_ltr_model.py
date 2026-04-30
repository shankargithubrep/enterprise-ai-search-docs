#!/usr/bin/env python3
"""
Train XGBoost LambdaMART model for Elasticsearch LTR.

Input: judgments.json from generate_synthetic_judgments.py
Output: ltr_model_xgboost.json (ES-compatible model definition)

Features used:
  0: bm25_score      — BM25 relevance score from body field
  1: semantic_score   — semantic similarity score from Jina v5 Small
  2: bm25_rank        — position in BM25 result list (lower = better)
  3: semantic_rank    — position in semantic result list (lower = better)
  4: doc_size         — document byte size (proxy for content richness)
"""

import json
import numpy as np
import xgboost as xgb

JUDGMENTS_PATH = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/judgments.json"
MODEL_OUTPUT = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/ltr_model_xgboost.json"
ES_MODEL_OUTPUT = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/es_ltr_model_payload.json"

FEATURE_NAMES = ["bm25_score", "semantic_score", "bm25_rank", "semantic_rank", "doc_size"]


def load_data():
    with open(JUDGMENTS_PATH) as f:
        judgments = json.load(f)

    features = []
    labels = []
    qids = []

    for j in judgments:
        feat = j["features"]
        features.append([
            feat["bm25_score"],
            feat["semantic_score"],
            feat["bm25_rank"],
            feat["semantic_rank"],
            feat["doc_size"],
        ])
        labels.append(j["grade"])
        qids.append(j["qid"])

    return np.array(features), np.array(labels), np.array(qids)


def build_group_sizes(qids):
    groups = []
    current_qid = qids[0]
    count = 0
    for qid in qids:
        if qid == current_qid:
            count += 1
        else:
            groups.append(count)
            current_qid = qid
            count = 1
    groups.append(count)
    return groups


def train():
    X, y, qids = load_data()
    groups = build_group_sizes(qids)

    print(f"Training data: {X.shape[0]} samples, {X.shape[1]} features, {len(groups)} queries")
    print(f"Label distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    n_queries = len(groups)
    split_idx = int(n_queries * 0.8)
    split_sample = sum(groups[:split_idx])

    X_train, X_val = X[:split_sample], X[split_sample:]
    y_train, y_val = y[:split_sample], y[split_sample:]
    groups_train = groups[:split_idx]
    groups_val = groups[split_idx:]

    print(f"Train: {X_train.shape[0]} samples, {len(groups_train)} queries")
    print(f"Val:   {X_val.shape[0]} samples, {len(groups_val)} queries")

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dtrain.set_group(groups_train)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_NAMES)
    dval.set_group(groups_val)

    params = {
        "objective": "rank:ndcg",
        "eval_metric": "ndcg@5",
        "eta": 0.1,
        "max_depth": 4,
        "min_child_weight": 10,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "seed": 42,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=200,
        evals=[(dtrain, "train"), (dval, "val")],
        verbose_eval=25,
        early_stopping_rounds=30,
    )

    print(f"\nBest iteration: {model.best_iteration}")
    print(f"Best NDCG@5:    {model.best_score:.4f}")

    importance = model.get_score(importance_type="gain")
    print(f"\nFeature importance (gain):")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"  {feat}: {score:.2f}")

    model.save_model(MODEL_OUTPUT)
    print(f"\nXGBoost model saved: {MODEL_OUTPUT}")

    build_es_model(model)

    return model


def build_es_model(model):
    """Build the ES PUT _ml/trained_models payload."""
    model_json_path = MODEL_OUTPUT
    model.save_model(model_json_path)
    with open(model_json_path) as f:
        xgb_model = json.load(f)

    es_payload = {
        "inference_config": {
            "learning_to_rank": {
                "feature_extractors": [
                    {
                        "query_extractor": {
                            "feature_name": "bm25_score",
                            "query": {"match": {"body": "{{query_string}}"}},
                        }
                    },
                    {
                        "query_extractor": {
                            "feature_name": "semantic_score",
                            "query": {"match": {"body": "{{query_string}}"}},
                        }
                    },
                    {
                        "query_extractor": {
                            "feature_name": "bm25_rank",
                            "query": {"match": {"body": "{{query_string}}"}},
                        }
                    },
                    {
                        "query_extractor": {
                            "feature_name": "semantic_rank",
                            "query": {"match": {"body": "{{query_string}}"}},
                        }
                    },
                    {
                        "query_extractor": {
                            "feature_name": "doc_size",
                            "query": {"function_score": {
                                "query": {"match_all": {}},
                                "field_value_factor": {
                                    "field": "size",
                                    "missing": 0
                                }
                            }},
                        }
                    },
                ],
            }
        },
        "input": {
            "field_names": FEATURE_NAMES,
        },
        "definition": xgb_model,
    }

    with open(ES_MODEL_OUTPUT, "w") as f:
        json.dump(es_payload, f, indent=2)

    print(f"ES model payload saved: {ES_MODEL_OUTPUT}")
    print(f"\nTo deploy, run in Dev Tools:")
    print(f'  PUT _ml/trained_models/genesys-ltr-v1')
    print(f'  <paste contents of {ES_MODEL_OUTPUT}>')


if __name__ == "__main__":
    train()
