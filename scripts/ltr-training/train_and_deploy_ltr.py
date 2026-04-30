#!/usr/bin/env python3
"""
End-to-end LTR pipeline: train XGBRanker + deploy to Elasticsearch via eland.
"""

import json
import numpy as np
import xgboost as xgb
from elasticsearch import Elasticsearch
from eland.ml import MLModel
from eland.ml.ltr import LTRModelConfig, QueryFeatureExtractor

ES_HOST = "https://5b324682048f4a1197d257cf0705072a.us-east-2.aws.elastic-cloud.com:443"
API_KEY = "ZGFzLWw1MEJKaWxyaVN0MGhCT1E6aGpOb1pqVGlqVzlvZE9ONGR3YnE4UQ=="
MODEL_ID = "genesys-ltr-v1"
JUDGMENTS_PATH = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/judgments.json"

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


def train_and_deploy():
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

    ranker = xgb.XGBRanker(
        objective="rank:ndcg",
        eval_metric="ndcg@5",
        learning_rate=0.1,
        max_depth=4,
        min_child_weight=10,
        subsample=0.8,
        colsample_bytree=0.8,
        n_estimators=200,
        early_stopping_rounds=30,
        random_state=42,
    )

    ranker.fit(
        X_train, y_train, group=groups_train,
        eval_set=[(X_val, y_val)],
        eval_group=[groups_val],
        verbose=25,
    )

    print(f"\nBest iteration: {ranker.best_iteration}")
    print(f"Best NDCG@5:    {ranker.best_score:.4f}")

    importance = dict(zip(FEATURE_NAMES, ranker.feature_importances_))
    print(f"\nFeature importance:")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"  {feat}: {score:.4f}")

    # --- Deploy to ES ---
    print("\n--- Deploying to Elasticsearch ---")

    es = Elasticsearch(ES_HOST, api_key=API_KEY, verify_certs=False)
    print(f"Connected to ES: {es.info()['version']['number']}")

    try:
        es.ml.delete_trained_model(model_id=MODEL_ID, force=True)
        print(f"Deleted existing model: {MODEL_ID}")
    except Exception:
        pass

    ltr_config = LTRModelConfig(
        feature_extractors=[
            QueryFeatureExtractor(
                feature_name="bm25_score",
                query={"match": {"body": "{{query_string}}"}},
            ),
            QueryFeatureExtractor(
                feature_name="semantic_score",
                query={"match": {"title": "{{query_string}}"}},
            ),
            QueryFeatureExtractor(
                feature_name="bm25_rank",
                query={
                    "function_score": {
                        "query": {"match": {"body": "{{query_string}}"}},
                        "functions": [
                            {"script_score": {"script": {"source": "_score * 0.5"}}}
                        ],
                        "boost_mode": "replace",
                    }
                },
            ),
            QueryFeatureExtractor(
                feature_name="semantic_rank",
                query={
                    "function_score": {
                        "query": {"match": {"title": "{{query_string}}"}},
                        "functions": [
                            {"script_score": {"script": {"source": "_score * 0.5"}}}
                        ],
                        "boost_mode": "replace",
                    }
                },
            ),
            QueryFeatureExtractor(
                feature_name="doc_size",
                query={
                    "function_score": {
                        "query": {"match_all": {}},
                        "field_value_factor": {"field": "size", "missing": 0},
                    }
                },
            ),
        ]
    )

    MLModel.import_ltr_model(
        es_client=es,
        model=ranker,
        model_id=MODEL_ID,
        ltr_model_config=ltr_config,
        es_if_exists="replace",
    )

    print(f"\nModel deployed: {MODEL_ID}")

    model_info = es.ml.get_trained_models(model_id=MODEL_ID)
    model = model_info["trained_model_configs"][0]
    print(f"Model type: {list(model.get('inference_config', {}).keys())}")
    print(f"Features: {model.get('input', {}).get('field_names', [])}")

    print("\n=== READY TO TEST ===")
    print("Run this in Dev Tools:\n")
    print("""POST content-sharepoint-ltr-lab/_search
{
  "query": { "match": { "body": "how to reset password" } },
  "rescore": {
    "learning_to_rank": {
      "model_id": "genesys-ltr-v1",
      "params": { "query_string": "how to reset password" }
    },
    "window_size": 50
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}""")


if __name__ == "__main__":
    train_and_deploy()
