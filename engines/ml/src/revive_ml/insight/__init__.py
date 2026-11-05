"""revive_ml.insight: explanation, confidence, what-if, value of information, fleet planning, impact, passport.

Additive: every function reads an engine report (pipeline.assess) and never changes it. workflow.assess_with_insight
returns the unchanged report plus a new `insight` key. Ported to apps/web-studio/assets/js/engines/insight.js.
"""
from revive_ml.insight.confidence import confidence
from revive_ml.insight.explain import explain, rule_gap
from revive_ml.insight.fleet_opt import assign
from revive_ml.insight.impact import impact, scale
from revive_ml.insight.passport import passport
from revive_ml.insight.voi import next_best_actions
from revive_ml.insight.whatif import break_even, reroute, robustness
from revive_ml.insight.workflow import assess_with_insight, insight_for

__all__ = ["assess_with_insight", "assign", "break_even", "confidence", "explain", "impact", "insight_for",
           "next_best_actions", "passport", "reroute", "robustness", "rule_gap", "scale"]
