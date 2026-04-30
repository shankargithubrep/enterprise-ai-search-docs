#!/usr/bin/env python3
"""
Deploy trained XGBoost LTR model to Elasticsearch using eland.

Converts XGBoost model to ES tree format and uploads via trained_models API.
Defines feature extractors that ES uses at query time to compute features.
"""

import xgboost as xgb
from elasticsearch import Elasticsearch
from eland.ml import MLModel
from eland.ml.ltr import LTRModelConfig, QueryFeatureExtractor

ES_HOST = "https://5b324682048f4a1197d257cf0705072a.us-east-2.aws.elastic-cloud.com:443"
API_KEY = "ZGFzLWw1MEJKaWxyaVN0MGhCT1E6aGpOb1pqVGlqVzlvZE9ONGR3YnE4UQ=="
MODEL_ID = "genesys-ltr-v1"
XGB_MODEL_PATH = "/Users/shankarsubramaniam/enterprise-ai-search-docs/scripts/ltr-training/ltr_model_xgboost.json"


def deploy():
    es = Elasticsearch(ES_HOST, api_key=API_KEY, verify_certs=False)

    print(f"Connected to ES: {es.info()['version']['number']}")

    try:
        es.ml.delete_trained_model(model_id=MODEL_ID, force=True)
        print(f"Deleted existing model: {MODEL_ID}")
    except Exception:
        pass

    booster = xgb.Booster()
    booster.load_model(XGB_MODEL_PATH)
    print(f"Loaded XGBoost model: {booster.num_boosted_rounds()} rounds")

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
        model=booster,
        model_id=MODEL_ID,
        ltr_model_config=ltr_config,
        es_if_exists="replace",
    )

    print(f"\nModel deployed: {MODEL_ID}")

    model_info = es.ml.get_trained_models(model_id=MODEL_ID)
    model = model_info["trained_model_configs"][0]
    print(f"Model type: {list(model.get('inference_config', {}).keys())}")
    print(f"Features: {model.get('input', {}).get('field_names', [])}")

    print(f"\nTest query for Dev Tools:")
    print("""
POST content-sharepoint-ltr-lab/_search
{
  "query": {
    "match": { "body": "how to reset password" }
  },
  "rescore": {
    "learning_to_rank": {
      "model_id": "genesys-ltr-v1",
      "params": {
        "query_string": "how to reset password"
      }
    },
    "window_size": 50
  },
  "size": 5,
  "_source": ["title", "webUrl"]
}
""")


if __name__ == "__main__":
    deploy()
