"""revive_ml.intelligence: the ML workflow around the assessment engine (additive; pipeline.py is unchanged).

    mapper     trained column mapper: which column is voltage/current/time/capacity..., units, confidence
    identity   chemistry, maker and pack spec from the upload; what is still needed from the user
    advisor    second-use ranking per battery (chemistry family + health + duty + engine economics)
    workflow   analyze_upload(...) and assess_with_advice(...)
"""
from revive_ml.intelligence.advisor import AdvisorInput, advise, characteristics, from_report
from revive_ml.intelligence.identity import detect_identity, infer_spec, profiles
from revive_ml.intelligence.mapper import map_columns, standardise
from revive_ml.intelligence.workflow import UploadError, analyze_upload, assess_with_advice, read_tables

__all__ = ["AdvisorInput", "UploadError", "advise", "analyze_upload", "assess_with_advice", "characteristics",
           "detect_identity", "from_report", "infer_spec", "map_columns", "profiles", "read_tables", "standardise"]
